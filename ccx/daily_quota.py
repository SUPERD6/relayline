"""Quota events for `ccx report --daily --quota-events`: decision 3 of docs/research/2026-11-17-eval-rule-decisions.md
("quota run-out does not stop work", maintainer-confirmed 2026-11-19), applied to the real-use records.

Read-only. Every event gets a verdict (success / failure / not_attempted / unknown) with a reason, and every field says
whether it was judged by the machine (ledger, run.json, relay packets and continue records) or came from a person's
note (the notes file below). Nothing is called, nothing goes over the network.

Notes file `<hub>/ccx/daily/quota-notes.jsonl`, one JSON object per line, written by hand (the format is fixed in
advance so that nothing is judged after the fact):
  {"kind": "wait",    "id": RUN_OR_PACKET, "ts": WHEN, "note": "..."}  the person chose to wait for the reset
  {"kind": "confirm", "id": PACKET, "ts": WHEN, "basis": "window_full" | "reset_ge_1h", "note": "..."}
                                                                       usage reading or reset time for an unconfirmed packet
  {"kind": "intact",  "id": PACKET, "ts": WHEN}   the person checked that no uncommitted change was lost
  {"kind": "done",    "id": PACKET, "ts": WHEN}   the person marked the continued work finished
  {"kind": "lost",    "id": RUN_OR_PACKET, "ts": WHEN}   uncommitted work was lost: the whole claim is Fail
  {"kind": "exclude", "id": RUN_OR_PACKET, "ts": WHEN, "note": "simulated | replay | deliberate"}   not counted
`ts` is epoch seconds or an ISO 8601 time.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

from . import ledger
from .config import Paths
from .ways import INTERNAL
from .workspace import worktree_repo

RULE_START = "2026-11-19"          # decision 3 applies to events from this day on
N_HOURS = 4                        # continue within this long (decision 3, maintainer-confirmed)
MIN_EVENTS = 5
MIN_RATE = 0.8
UNCONFIRMED_WINDOW = 3600          # a human confirmation counts only within an hour of the packet
_N = N_HOURS * 3600
_NOT_DONE_STATES = ("prepared", "interrupted")          # a continue record in these states is no continuation
_RUNNING_STATES = ("starting", "running")


def notes_path(p: Paths) -> Path:
    return p.state / "daily" / "quota-notes.jsonl"


def _t(v) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v) if 0 < v < 4e9 else None
    if isinstance(v, str):
        try:
            dt = datetime.fromisoformat(v.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
        return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).timestamp()
    return None


def _day(ts: float, tz) -> str:
    return datetime.fromtimestamp(ts, tz).strftime("%Y-%m-%d")


def load_notes(p: Paths) -> list[dict]:
    out: list[dict] = []
    try:
        text = notes_path(p).read_text(encoding="utf-8")
    except OSError:
        return out
    for line in text.splitlines():
        try:
            n = json.loads(line)
        except ValueError:
            continue
        if isinstance(n, dict) and isinstance(n.get("kind"), str) and n.get("id"):
            n["_ts"] = _t(n.get("ts"))
            out.append(n)
    return out


def _notes(notes: list[dict], kind: str, ident: str) -> list[dict]:
    return [n for n in notes if n["kind"] == kind and str(n["id"]) == ident]


def _ev(role: str, source: str, ident: str, ts: float, day: str, frm: str, to: str, verdict: str, reason: str,
        machine: list[str], human: list[str], **kw) -> dict:
    return {"id": ident, "role": role, "source": source, "ts": ts, "day": day, "from": frm, "to": to,
            "verdict": verdict, "reason": reason, "judged_by": {"machine": machine, "human": human}, **kw}


# ---- sub-agent events -------------------------------------------------------------------------------------------

def _rung_key(row: dict) -> tuple:
    first = (row.get("rungs") or [None])[0]
    parts = str(first).split(":") if first else []
    return (row.get("to"), parts[1] if len(parts) > 1 else None)


def _quota_agent(rec: dict, row: dict) -> str:
    qs = rec.get("quota_stop") if isinstance(rec.get("quota_stop"), dict) else {}
    fb = rec.get("quota_fallback") if isinstance(rec.get("quota_fallback"), dict) else {}
    return str(qs.get("agent") or fb.get("from") or row.get("to") or "?")


def _is_new_event(p: Paths, row: dict, rec: dict) -> bool:
    """Original tasks only: a continuation that merely inherited the earlier run's quota fields is not a new event."""
    atts = [a for a in rec.get("attempts") or [] if isinstance(a, dict)] if isinstance(rec.get("attempts"), list) else []
    own = bool(rec.get("quota_stop") or any(a.get("kind") == "quota" or a.get("quota_stop") for a in atts))
    hit = bool(own or rec.get("quota_fallback"))
    if not hit:
        return False
    if not rec.get("resumed_from"):
        return True
    if own:
        return True
    try:
        parent = ledger.load_run(p, rec["resumed_from"])
    except (FileNotFoundError, KeyError, ValueError, OSError):
        return False                        # cannot tell: do not invent an event
    return not (isinstance(parent, dict) and parent.get("quota_fallback") == rec.get("quota_fallback"))


def _sub_verdict(p: Paths, row: dict, rec: dict, ctx: dict) -> dict:
    rid, notes, now, hard = row["run_id"], ctx["notes"], ctx["now"], ctx["hard"]
    start = row["ts"]
    t0 = start + (row.get("seconds") or 0 if isinstance(row.get("seconds"), (int, float)) else 0)
    frm = _quota_agent(rec, row)
    fb = rec.get("quota_fallback") if isinstance(rec.get("quota_fallback"), dict) else None
    to = str((fb or {}).get("to") or row.get("to") or "?")
    day = _day(start, ctx["tz"])
    mk = lambda v, why, mach=(), hum=(), **kw: _ev("sub_agent", "run.json", rid, t0, day, frm, to, v, why,  # noqa: E731
                                                  list(mach), list(hum), **kw)
    if _notes(notes, "lost", rid):
        return mk("failure", "人工记录：丢了未提交的改动", hum=["lost"], claim_fail=True)
    waited = [n for n in _notes(notes, "wait", rid) if n["_ts"] and t0 <= n["_ts"] <= t0 + _N]
    if waited:
        return mk("not_attempted", "用户选择等额度重置（当时写进记录）", hum=["wait"])

    def finish(cont_row: dict, why: str, mach: list[str]) -> dict:
        crid = cont_row.get("run_id")
        if cont_row.get("status") == "running" or cont_row.get("state") == "running":
            return mk("unknown", "接续运行还没结束", mach, continued_by=crid)
        v = hard.get(crid or "")
        if v is not None and not v.get("ok"):
            return mk("failure", "接续运行被 ccx verify 判为错", mach + ["verify"], continued_by=crid)
        if cont_row.get("ok") and cont_row.get("status") == "done":
            return mk("success", why, mach + ["ok"], continued_by=crid)
        return mk("failure", "接续运行没有以 ok 结束（活没做完）", mach, continued_by=crid)

    if fb and fb.get("to") and fb.get("to") != fb.get("from"):
        return finish(row, "同一个运行经 quota_fallback 改派到别家并做完", ["quota_fallback"])
    later = [r for r in ctx["all_runs"] if r.get("run_id") != rid and r.get("cwd") == row.get("cwd")
             and _t(r.get("ts")) and r["ts"] > start]
    cont, same_target = None, None
    for r in sorted(later, key=lambda x: x["ts"]):
        try:
            rr = ledger.load_run(p, r["run_id"])
        except (FileNotFoundError, KeyError, ValueError, OSError):
            continue
        if isinstance(rr, dict) and rr.get("resumed_from") == rid:
            if _rung_key(r) == _rung_key(row):
                same_target = same_target or r
                continue
            cont = r
            break
    horizon = cont["ts"] if cont else t0 + _N
    redo = [r for r in later if r.get("label") == row.get("label") and t0 < r["ts"] < horizon
            and (r is not cont) and not _resumed(p, r)]
    if redo:
        return mk("failure", "事件后另起了同标签的运行重做，不是接续", ["ledger"], redo_run=redo[0].get("run_id"))
    if cont:
        if cont["ts"] - t0 > _N:
            return mk("failure", f"接续在事件 {N_HOURS} 小时之后才开始", ["ledger"], continued_by=cont.get("run_id"))
        return finish(cont, "在别家或别的模型接续并做完", ["resumed_from"])
    if same_target is not None:
        why = "有接续运行但没换家也没换模型"
    else:
        why = "quota_stop 之后既没改派也没接续"
    if now - t0 >= _N:
        return mk("failure", f"{why}（已过 {N_HOURS} 小时）", ["ledger"])
    return mk("unknown", f"{why}；{N_HOURS} 小时窗口还没结束", ["ledger"])


def _resumed(p: Paths, row: dict) -> bool:
    try:
        rr = ledger.load_run(p, row["run_id"])
    except (FileNotFoundError, KeyError, ValueError, OSError):
        return True                        # unreadable: not counted as a redo
    return not isinstance(rr, dict) or bool(rr.get("resumed_from"))


# ---- lead (relay packet) events ---------------------------------------------------------------------------------

def _roots(rows: list[dict], extra) -> list[Path]:
    seen: dict[str, Path] = {}
    cands = [Path(x) for x in extra or ()]
    for r in rows:
        cwd = r.get("cwd")
        if cwd:
            try:
                cands.append(Path(str(worktree_repo(cwd) or cwd)))
            except (OSError, ValueError):
                cands.append(Path(str(cwd)))
    for c in cands:
        try:
            key = str(c.resolve())
        except OSError:
            continue
        if (c / ".ccx" / "relay").is_dir():
            seen.setdefault(key, c)
    return list(seen.values())


def _load_json(path: Path) -> dict | None:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def _mtime(path: Path) -> float | None:
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def _packets(root: Path) -> list[tuple[Path, dict]]:
    out = []
    for f in sorted((root / ".ccx" / "relay").glob("*.json")):
        stem = f.stem
        if len(stem) != 32 or any(c not in "0123456789abcdef" for c in stem):
            continue                        # .notification / .continue-* / context-* are not packets
        d = _load_json(f)
        if d is not None and d.get("id") == stem:
            out.append((f, d))
    return out


def _continuations(folder: Path, pid: str) -> list[dict]:
    out = []
    for f in sorted(folder.glob(f"{pid}.continue-*.json")):
        d = _load_json(f)
        if d is not None:
            d["_start"] = _t(d.get("started_at")) or _mtime(f)       # records carry started_at; mtime is the fallback
            d["_end"] = _mtime(f)                                    # the record is written last: its mtime is the end
            out.append(d)
    return sorted(out, key=lambda c: c["_start"] or 0)


def _lead_verdict(path: Path, pk: dict, ctx: dict, conts: list[dict], via: str) -> dict:
    pid, notes, now = pk["id"], ctx["notes"], ctx["now"]
    cap = _t(pk.get("captured_at")) or _mtime(path) or 0
    day = _day(cap, ctx["tz"])
    frm = str(pk.get("source") or "?")
    to = "claude" if frm == "codex" else "codex" if frm == "claude" else "?"
    real = [c for c in conts if c.get("state") not in _NOT_DONE_STATES]
    if real:
        to = str(real[0].get("to") or to)
    mach = ["relay packet"] + (["continue record"] if real else [])
    mk = lambda v, why, mach=mach, hum=(), **kw: _ev("lead", via, pid, cap, day, frm, to, v, why,  # noqa: E731
                                                    list(mach), list(hum), **kw)
    if _notes(notes, "lost", pid):
        return mk("failure", "人工记录：丢了未提交的改动", hum=["lost"], claim_fail=True)
    if [n for n in _notes(notes, "wait", pid) if n["_ts"] and cap <= n["_ts"] <= cap + _N]:
        return mk("not_attempted", "用户选择等额度重置（当时写进记录）", hum=["wait"])
    git = pk.get("git") if isinstance(pk.get("git"), dict) else {}
    if git.get("snapshot_status") or git.get("head") in (None, "Unknown"):
        return mk("failure", "packet 没法接续（Git 快照是 Unknown）")
    siblings = [o for o in ctx.get("packets", []) if o is not pk and pk.get("source_session") not in (None, "", "Unknown")
                and o.get("source_session") == pk.get("source_session") and o.get("_has_real_cont")]
    if siblings and real:
        return mk("failure", "同一会话改用了另一个 packet 接续（不算接着做）", siblings=[s["id"] for s in siblings])
    if not real:
        if any(c.get("state") in _RUNNING_STATES for c in conts):
            return mk("unknown", "接续还在运行")
        why = "接续记录只有 prepared / interrupted，不算接续" if conts else "没有接续记录"
        if now - cap >= _N:
            return mk("failure", f"{why}（已过 {N_HOURS} 小时）")
        return mk("unknown", f"{why}；{N_HOURS} 小时窗口还没结束")
    c = real[0]
    if c["_start"] and c["_start"] - cap > _N:
        return mk("failure", f"接续在事件 {N_HOURS} 小时之后才开始")
    if c.get("state") in _RUNNING_STATES:
        return mk("unknown", "接续还在运行")
    if c.get("state") != "exited" or c.get("exit_code") != 0:
        return mk("failure", f"接续以 {c.get('state')} 结束（退出码 {c.get('exit_code')}），活没做完")
    if c.get("changes_observed") is not True:
        return mk("failure", "接续没有观察到改动（changes_observed 不是真）")
    fp_unknown = git.get("content_fingerprint") == "Unknown"
    if c.get("workspace_changed") is not False or fp_unknown:
        if not [n for n in _notes(notes, "intact", pid)]:
            return mk("unknown", "workspace_changed 不是 false 或指纹是 Unknown：要用户核对没丢改动（人工，还没有记录）")
        hum = ["intact"]
    else:
        hum = []
    end = c["_end"] or now
    done = [n for n in _notes(notes, "done", pid) if n["_ts"] and end <= n["_ts"] <= end + _N]
    if done:
        return mk("success", "在另一家接续、没丢东西、做完并有人工标记", hum=hum + ["done"])
    if now - end >= _N:
        return mk("failure", f"接续结束后 {N_HOURS} 小时内没有人工标记做完", hum=hum)
    return mk("unknown", "接续已结束，等用户在 4 小时内标记做完（人工）", hum=hum)


def _confirmed(pk: dict, cap: float, notes: list[dict], conts: list[dict]) -> dict | None:
    real = [c for c in conts if c.get("state") not in _NOT_DONE_STATES]
    first = real[0]["_start"] if real else None
    for n in _notes(notes, "confirm", pk["id"]):
        if n.get("basis") in ("window_full", "reset_ge_1h") and n["_ts"] and 0 <= n["_ts"] - cap <= UNCONFIRMED_WINDOW \
                and (first is None or n["_ts"] <= first):
            return n
    return None


# ---- the summary ------------------------------------------------------------------------------------------------

def clopper_pearson_lower(k: int, n: int, alpha: float = 0.05) -> float | None:
    """One-sided lower bound: the p at which P(X >= k | n, p) = alpha (4/5 -> about 0.34)."""
    if n <= 0:
        return None
    if k <= 0:
        return 0.0

    def tail(pp: float) -> float:
        return sum(math.comb(n, i) * pp ** i * (1 - pp) ** (n - i) for i in range(k, n + 1))
    lo, hi = 0.0, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if tail(mid) < alpha else (lo, mid)
    return (lo + hi) / 2


def _tally(evs: list[dict]) -> dict:
    counted = [e for e in evs if e["verdict"] != "not_attempted"]
    n = len(counted)
    k = sum(e["verdict"] == "success" for e in counted)
    unk = sum(e["verdict"] == "unknown" for e in counted)
    rate = k / n if n else None
    claim_fail = any(e.get("claim_fail") for e in evs)
    if claim_fail:
        verdict, why = "Fail", "有事件丢了未提交的改动，整个主张直接判 Fail（不看比例）"
    elif n < MIN_EVENTS:
        verdict, why = "Unknown", f"计入事件 {n} 次，不到 {MIN_EVENTS} 次"
    elif (k + unk) / n < MIN_RATE:
        verdict, why = "Fail", f"即使没定的全成功，成功率也不到 {MIN_RATE:.0%}"
    elif unk:
        verdict, why = "Unknown", f"还有 {unk} 个事件没判出来"
    elif rate >= MIN_RATE:
        verdict, why = "Pass", f"{k}/{n} ≥ {MIN_RATE:.0%}"
    else:
        verdict, why = "Fail", f"{k}/{n} < {MIN_RATE:.0%}"
    return {"events": len(evs), "counted": n, "success": k,
            "failure": sum(e["verdict"] == "failure" for e in counted), "unknown": unk,
            "not_attempted": len(evs) - n, "success_rate": rate,
            "lower_bound_95": clopper_pearson_lower(k, n), "meets_min_events": n >= MIN_EVENTS,
            "meets_min_rate": rate is not None and rate >= MIN_RATE, "claim_fail": claim_fail,
            "verdict": verdict, "verdict_reason": why}


def summarize(events: list[dict], split: str | None = None, through: str | None = None) -> dict:
    s = {"combined": _tally(events),
         "by_role": {r: _tally([e for e in events if e["role"] == r]) for r in ("lead", "sub_agent")},
         "by_pair": {}}
    for e in events:
        s["by_pair"].setdefault(f"{e['role']}:{e['from']}->{e['to']}", []).append(e)
    s["by_pair"] = {k: _tally(v) for k, v in sorted(s["by_pair"].items())}
    s["lead_note"] = (None if s["by_role"]["lead"]["counted"] else
                      "没有计入的主导事件：主张只覆盖子 agent，主导一侧是 Unknown")
    if not split:
        s["two_periods"] = {"ok": None, "reason": "没给 --quota-split，无法判断两个互不重叠的时段"}
    else:
        a = _tally([e for e in events if e["day"] < split])
        b = _tally([e for e in events if e["day"] >= split])
        ok = a["verdict"] == "Pass" and b["verdict"] == "Pass"
        s["two_periods"] = {"ok": ok, "split": split, "first": a, "second": b,
                            "reason": ("两个时段各 ≥ 5 次且都 ≥ 80%" if ok else
                                       "对外引用需要两个时段各 ≥ 5 次计入事件且都 ≥ 80%：现在不满足")}
    return s


# ---- entry ------------------------------------------------------------------------------------------------------

def build(p: Paths, day: str, tz, now: float, workspaces=(), split: str | None = None,
          include_evals: bool = False) -> dict:
    """Events from RULE_START through `day`, judged as of `now`."""
    notes = load_notes(p)
    all_rows = ledger.rows(p)
    hard: dict[str, dict] = {}
    for r in all_rows:
        if r.get("type") == "verify" and r.get("run_id") and not r.get("soft"):
            hard[r["run_id"]] = r
    plain = [r for r in all_rows if not r.get("type") and r.get("run_id") and _t(r.get("ts"))]
    ctx = {"notes": notes, "now": now, "tz": tz, "hard": hard, "all_runs": plain}
    events: list[dict] = []
    excluded = 0
    for r in plain:
        label = str(r.get("label") or "")
        if (not include_evals and ledger.is_eval(r)) or label.startswith("review:") or r.get("ephemeral") \
                or label.startswith(INTERNAL):
            continue
        d = _day(r["ts"], tz)
        if d < RULE_START or d > day:
            continue
        try:
            rec = ledger.load_run(p, r["run_id"])
        except (FileNotFoundError, KeyError, ValueError, OSError):
            continue
        if not isinstance(rec, dict) or not _is_new_event(p, r, rec):
            continue
        if _notes(notes, "exclude", r["run_id"]):
            excluded += 1
            continue
        events.append(_sub_verdict(p, r, rec, ctx))
    unconfirmed = 0
    roots = _roots(plain, workspaces)
    for root in roots:
        folder = root / ".ccx" / "relay"
        pks = _packets(root)
        convs = {pk["id"]: _continuations(folder, pk["id"]) for _, pk in pks}
        for _, pk in pks:
            pk["_has_real_cont"] = any(c.get("state") not in _NOT_DONE_STATES for c in convs[pk["id"]])
        ctx["packets"] = [pk for _, pk in pks]
        for path, pk in pks:
            sig = pk.get("quota_signal") if isinstance(pk.get("quota_signal"), dict) else {}
            cap = _t(pk.get("captured_at")) or _mtime(path)
            if cap is None or not (RULE_START <= _day(cap, tz) <= day):
                continue
            if _notes(notes, "exclude", pk["id"]):
                excluded += 1
                continue
            if pk.get("state") == "quota_stopped" or (sig.get("kind") == "quota" and pk.get("state") != "rate_limit_unconfirmed"):
                events.append(_lead_verdict(path, pk, ctx, convs[pk["id"]], "relay packet"))
            elif pk.get("state") == "rate_limit_unconfirmed" or sig.get("kind") == "rate_limit_unconfirmed":
                if _confirmed(pk, cap, notes, convs[pk["id"]]):
                    ev = _lead_verdict(path, pk, ctx, convs[pk["id"]], "relay packet + 人工确认")
                    ev["judged_by"]["human"].append("confirm")
                    events.append(ev)
                else:
                    unconfirmed += 1
    events.sort(key=lambda e: (e["ts"], e["id"]))
    return {"rule": "docs/research/2026-11-17-eval-rule-decisions.md 决定 3", "rule_start": RULE_START,
            "n_hours": N_HOURS, "through": day, "now": now, "events": events,
            "not_counted": {"unconfirmed_packets": unconfirmed, "excluded_by_note": excluded},
            "relay_workspaces": [str(r) for r in roots], "notes_file": str(notes_path(p)),
            "summary": summarize(events, split, day)}


def render(q: dict) -> list[str]:
    s = q["summary"]
    c = s["combined"]

    def frac(t: dict) -> str:
        n = t["counted"]
        lb = t["lower_bound_95"]
        return (f"{t['success']}/{n}" + (f"（{t['success'] / n:.0%}，单侧 95% 下界 {lb:.0%}）" if n else "") +
                f"；失败 {t['failure']}、没判出 {t['unknown']}、未尝试 {t['not_attempted']}")
    L = ["## 额度事件（决定 3：额度用完不断工）", "",
         f"事件从 {q['rule_start']} 起算，到 {q['through']} 为止；{q['n_hours']} 小时内接续才算没断。"
         "证据等级 measured，但不是对照实验。每个事件标了机器判还是人工记录。", "",
         f"- 合并：{frac(c)}。结论 **{c['verdict']}**：{c['verdict_reason']}"]
    for r, name in (("lead", "主导"), ("sub_agent", "子 agent")):
        L.append(f"- {name}：{frac(s['by_role'][r])}")
    if s["lead_note"]:
        L.append(f"- {s['lead_note']}")
    tp = s["two_periods"]
    L.append(f"- 对外引用（两个时段各 ≥ {MIN_EVENTS} 次、都 ≥ {MIN_RATE:.0%}）："
             + ("满足" if tp["ok"] else "不满足" if tp["ok"] is False else "没法判断") + f"。{tp['reason']}")
    nc = q["not_counted"]
    L.append(f"- 不计入但列出：没有人工确认的 rate_limit_unconfirmed packet {nc['unconfirmed_packets']} 个；"
             f"人工记录排除（模拟、回放、故意制造）{nc['excluded_by_note']} 个")
    if s["by_pair"]:
        L += ["", "| 角色:来源->去向 | 成功/计入 | 失败 | 没判出 |", "|---|---|---|---|"]
        L += [f"| {k} | {t['success']}/{t['counted']} | {t['failure']} | {t['unknown']} |" for k, t in s["by_pair"].items()]
    if q["events"]:
        L += ["", "| 日期 | 角色 | 事件 | 来源->去向 | 判定 | 原因 | 机器 | 人工 |", "|---|---|---|---|---|---|---|---|"]
        for e in q["events"]:
            L.append(f"| {e['day']} | {'主导' if e['role'] == 'lead' else '子 agent'} | {e['id']} | {e['from']}->{e['to']} "
                     f"| {e['verdict']} | {e['reason'].replace('|', '/')} | {','.join(e['judged_by']['machine']) or '-'} "
                     f"| {','.join(e['judged_by']['human']) or '-'} |")
    L += ["", f"人工记录文件：`{q['notes_file']}`（格式见 docs/features.zh.md）。已知缺口：Codex 当主导时撞限不会被自动记下，除非带证据手工记录，否则是 Unknown。", ""]
    return L
