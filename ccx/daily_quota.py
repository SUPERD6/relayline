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
`ts` is epoch seconds or an ISO 8601 time; an ISO time without a zone is read in the page's time zone (`--tz`, local
when not given). `done` is read from this file only (`ccx verify` does not count), and only the first real continuation
of a packet is judged. A missing `done` or `intact` once the window is over is a failure with `failure_basis`
"missing_human_record" (counted separately, with a sensitivity line that is not quotable).
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


def _t(v, tz=None) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v) if 0 < v < 4e9 else None
    if isinstance(v, str):
        try:
            dt = datetime.fromisoformat(v.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
        if dt.tzinfo is None and tz is not None:
            dt = dt.replace(tzinfo=tz)
        return dt.timestamp()          # a naive time with no tz given is this machine's local time
    return None


def _day(ts: float, tz) -> str:
    return datetime.fromtimestamp(ts, tz).strftime("%Y-%m-%d")


def load_notes(p: Paths, tz=None) -> tuple[list[dict], int]:
    """(notes, number of unreadable lines)."""
    out: list[dict] = []
    bad = 0
    try:
        text = notes_path(p).read_text(encoding="utf-8-sig")
    except OSError:
        return out, 0
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            n = json.loads(line)
        except ValueError:
            bad += 1
            continue
        if isinstance(n, dict) and isinstance(n.get("kind"), str) and n.get("id"):
            n["_ts"] = _t(n.get("ts"), tz)
            out.append(n)
        else:
            bad += 1
    return out, bad


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


def _atts(rec: dict) -> list[dict]:
    return [a for a in rec.get("attempts") or [] if isinstance(a, dict)] if isinstance(rec.get("attempts"), list) else []


def _own_hit(rec: dict) -> bool:
    return bool(rec.get("quota_stop") or any(a.get("kind") == "quota" or a.get("quota_stop") for a in _atts(rec)))


def _raw_hit(rec: dict) -> bool:
    return bool(_own_hit(rec) or rec.get("quota_fallback"))


def _vend(*names) -> list[str]:
    out: list[str] = []
    for n in names:
        if n and (not out or out[-1] != n):
            out.append(n)
    return out


def _quota_agent(rec: dict, row: dict) -> str:
    qs = rec.get("quota_stop") if isinstance(rec.get("quota_stop"), dict) else {}
    fb = rec.get("quota_fallback") if isinstance(rec.get("quota_fallback"), dict) else {}
    return str(qs.get("agent") or fb.get("from") or row.get("to") or "?")


def _load(p: Paths, rid) -> dict | None:
    try:
        rec = ledger.load_run(p, rid)
    except (FileNotFoundError, KeyError, ValueError, OSError, TypeError):
        return None
    return rec if isinstance(rec, dict) else None


def _is_new_root(p: Paths, rec: dict) -> bool:
    """One original task is one event: a run is a root when no run it was resumed from hit the limit. A chain that
    cannot be read (a parent run.json is missing) counts only if this run hit the limit by itself."""
    cur, n = rec, 0
    while cur.get("resumed_from") and n < 20:
        cur = _load(p, cur["resumed_from"])
        if cur is None:
            return _own_hit(rec)
        if _raw_hit(cur):
            return False
        n += 1
    return True


def _running_resumes(p: Paths, ctx: dict) -> dict[str, list[str]]:
    """resumed_from -> ids of runs still running. The ledger gets a row only when a run ends, so a continuation that is
    still going is only visible in its run.json."""
    if "running" not in ctx:
        found: dict[str, list[str]] = {}
        try:
            dirs = [d for d in p.runs.iterdir() if d.is_dir()]
        except OSError:
            dirs = []
        for d in dirs:
            rec = _load(p, d.name)
            if rec and rec.get("resumed_from") and (rec.get("status") == "running" or rec.get("state") == "running"):
                found.setdefault(str(rec["resumed_from"]), []).append(d.name)
        ctx["running"] = found
    return ctx["running"]


def _sub_verdict(p: Paths, row: dict, rec: dict, ctx: dict, depth: int = 0) -> dict:
    rid, notes, now, hard = row["run_id"], ctx["notes"], ctx["now"], ctx["hard"]
    t0 = row["ts"]                                   # the 4 hours run from the event run's ts (decision 3)
    frm = _quota_agent(rec, row)
    fb = rec.get("quota_fallback") if isinstance(rec.get("quota_fallback"), dict) else None
    to = str((fb or {}).get("to") or row.get("to") or "?")
    day = _day(t0, ctx["tz"])
    mk = lambda v, why, mach=(), hum=(), to_=None, **kw: _ev(  # noqa: E731
        "sub_agent", "run.json", rid, t0, day, frm, to_ or to, v, why, list(mach), list(hum), chain=[rid],
        vendors=_vend(frm, to_ or to), **kw)
    if _notes(notes, "lost", rid):
        return mk("failure", "人工记录：丢了未提交的改动", hum=["lost"], claim_fail=True)
    waited = [n for n in _notes(notes, "wait", rid) if n["_ts"] and t0 <= n["_ts"] <= t0 + _N]
    if waited:
        return mk("not_attempted", "用户选择等额度重置（当时写进记录）", hum=["wait"])

    def finish(cont_row: dict, why: str, mach: list[str]) -> dict:
        crid = cont_row.get("run_id")
        to = str(cont_row.get("to") or "?") if crid != rid else None       # the vendor that finished the work
        if crid != rid and _notes(notes, "lost", crid or ""):
            return mk("failure", "人工记录：接续运行丢了未提交的改动", mach, ["lost"], claim_fail=True, continued_by=crid, to_=to)
        if cont_row.get("status") == "running" or cont_row.get("state") == "running":
            return mk("unknown", "接续运行还没结束", mach, continued_by=crid, to_=to)
        v = hard.get(crid or "")
        if v is not None and not v.get("ok"):
            return mk("failure", "接续运行被 ccx verify 判为错", mach + ["verify"], continued_by=crid, to_=to)
        if cont_row.get("ok") and cont_row.get("status") == "done":
            return mk("success", why, mach + ["ok"], continued_by=crid, to_=to)
        return mk("failure", "接续运行没有以 ok 结束（活没做完）", mach, continued_by=crid, to_=to)

    if fb and fb.get("to") and fb.get("to") != fb.get("from"):
        return finish(row, "同一个运行经 quota_fallback 改派到别家并做完", ["quota_fallback"])
    later = [r for r in ctx["all_runs"] if r.get("run_id") != rid and r.get("cwd") == row.get("cwd") and r["ts"] > t0]
    cont, crec, same_target = None, None, None
    for r in sorted(later, key=lambda x: x["ts"]):
        rr = _load(p, r["run_id"])
        if rr is not None and rr.get("resumed_from") == rid:
            if _rung_key(r) == _rung_key(row):
                same_target = same_target or r
                continue
            cont, crec = r, rr
            break
    horizon = cont["ts"] if cont else t0 + _N
    redo = [r for r in later if row.get("label") and r.get("label") == row.get("label") and t0 < r["ts"] < horizon
            and r is not cont and not _resumed(p, r)]
    if redo:
        return mk("failure", "事件后另起了同标签的运行重做，不是接续", ["ledger"], redo_run=redo[0].get("run_id"))
    if cont:
        if cont["ts"] - t0 > _N:
            return mk("failure", f"接续在事件 {N_HOURS} 小时之后才开始", ["ledger"], continued_by=cont.get("run_id"))
        if _own_hit(crec) and depth < 10:            # the continuation hit the limit too: the chain's last result decides
            v = _sub_verdict(p, cont, crec, ctx, depth + 1)
            v.update(id=rid, ts=t0, day=day, chain=[rid] + v["chain"])
            v["from"] = frm
            v["vendors"] = _vend(frm, *v["vendors"])          # every vendor the chain went through; `to` is the one that finished
            v["judged_by"]["machine"] = ["resumed_from"] + v["judged_by"]["machine"]
            return v
        return finish(cont, "在别家或别的模型接续并做完", ["resumed_from"])
    live = _running_resumes(p, ctx).get(rid)
    if live:
        return mk("unknown", "接续运行还在运行（账本要运行结束才写）", ["run.json"], continued_by=live[0])
    why = "有接续运行但没换家也没换模型" if same_target is not None else "quota_stop 之后既没改派也没接续"
    if now - t0 >= _N:
        return mk("failure", f"{why}（已过 {N_HOURS} 小时）", ["ledger"])
    return mk("unknown", f"{why}；{N_HOURS} 小时窗口还没结束", ["ledger"])


def _resumed(p: Paths, row: dict) -> bool:
    rr = _load(p, row["run_id"])
    return rr is None or bool(rr.get("resumed_from"))          # unreadable: not counted as a redo


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
        d = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def _mtime(path: Path) -> float | None:
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def _packets(root: Path) -> tuple[list[tuple[Path, dict]], int]:
    out, bad = [], 0
    for f in sorted((root / ".ccx" / "relay").glob("*.json")):
        stem = f.stem
        if len(stem) != 32 or any(c not in "0123456789abcdef" for c in stem):
            continue                        # .notification / .continue-* / context-* are not packets
        d = _load_json(f)
        if d is not None and d.get("id") == stem:
            out.append((f, d))
        else:
            bad += 1
    return out, bad


def _continuations(folder: Path, pid: str) -> list[dict]:
    out = []
    for f in sorted(folder.glob(f"{pid}.continue-*.json")):
        d = _load_json(f)
        if d is not None:
            d["_start"] = _t(d.get("started_at")) or _mtime(f)       # records carry started_at; mtime is the fallback
            # newer records carry ended_at (#483); older ones fall back to mtime (the record is written last)
            d["_end"] = _t(d.get("ended_at")) or _mtime(f)
            out.append(d)
    return sorted(out, key=lambda c: c["_start"] or 0)


def _real(conts: list[dict]) -> list[dict]:
    return [c for c in conts if c.get("state") not in _NOT_DONE_STATES]


def _cap(path: Path, pk: dict) -> float:
    return _t(pk.get("captured_at")) or _mtime(path) or 0


_CHAIN_STATES = ("quota_stopped", "rate_limit_unconfirmed")


def _chains(pks: list[tuple[Path, dict]], convs: dict) -> list[list[str]]:
    """One original task is one event. Packets are grouped into chains (head first, then by time):
    - the packet a continuation wrote when it hit a limit itself (`handoff_packet`; unconfirmed ones too);
    - a same-session `quota_stopped` packet that was itself continued, captured after the continued packet's
      `captured_at` and no later than its continuation's start (the earlier one then counts as having switched to it:
      a failure);
    - a same-session `quota_stopped` packet that was never continued (a duplicate), captured from 4 hours before the
      continued packet's `captured_at` up to its continuation's start, joins the earliest-continued packet.
    The window is anchored at the continued packet's `captured_at`; its continuation's start only closes it."""
    by_id = {pk["id"]: pk for _, pk in pks}
    caps = {pk["id"]: _cap(path, pk) for path, pk in pks}
    parent: dict[str, str] = {}
    heads = [(real[0]["_start"] or 0, a["id"], real[0]) for _, a in pks if (real := _real(convs[a["id"]]))]
    for start, aid, c in sorted(heads, key=lambda x: (x[0], x[1])):
        h = c.get("handoff_packet")
        if h in by_id and h != aid and by_id[h].get("state") in _CHAIN_STATES:
            parent.setdefault(h, aid)
        sess = by_id[aid].get("source_session")
        if sess in (None, "", "Unknown") or not c["_start"]:
            continue
        for bid, b in by_id.items():
            if bid == aid or b.get("source_session") != sess or b.get("state") != "quota_stopped":
                continue
            if _real(convs[bid]):
                if caps[aid] < caps[bid] <= c["_start"]:
                    parent.setdefault(bid, aid)
            elif caps[aid] - _N <= caps[bid] <= c["_start"]:
                parent.setdefault(bid, aid)

    def top(i: str) -> str:
        for _ in range(30):
            if i not in parent:
                break
            i = parent[i]
        return i
    groups: dict[str, list[str]] = {}
    for i in by_id:
        groups.setdefault(top(i), []).append(i)
    return [sorted(ids, key=lambda i: caps[i]) for ids in groups.values()]


def _lead_verdict(path: Path, pk: dict, ctx: dict, via: str, depth: int = 0) -> dict:
    pid, notes, now = pk["id"], ctx["notes"], ctx["now"]
    byid = ctx["byid"]
    conts = ctx["convs"][pid]
    cap = _cap(path, pk)
    day = _day(cap, ctx["tz"])
    frm = str(pk.get("source") or "?")
    to = "claude" if frm == "codex" else "codex" if frm == "claude" else "?"
    real = _real(conts)
    if real:
        to = str(real[0].get("to") or to)
    mach = ["relay packet"] + (["continue record"] if real else [])
    mk = lambda v, why, mach=mach, hum=(), **kw: _ev("lead", via, pid, cap, day, frm, to, v, why,  # noqa: E731
                                                    list(mach), list(hum), chain=[pid], vendors=_vend(frm, to), **kw)
    if _notes(notes, "lost", pid):
        return mk("failure", "人工记录：丢了未提交的改动", hum=["lost"], claim_fail=True)
    if [n for n in _notes(notes, "wait", pid) if n["_ts"] and cap <= n["_ts"] <= cap + _N]:
        return mk("not_attempted", "用户选择等额度重置（当时写进记录）", hum=["wait"])
    git = pk.get("git") if isinstance(pk.get("git"), dict) else {}
    if git.get("snapshot_status") or git.get("head") in (None, "Unknown"):
        return mk("failure", "packet 没法接续（Git 快照是 Unknown）")
    sess = pk.get("source_session")
    if real and real[0]["_start"] and sess not in (None, "", "Unknown"):
        sib = [o for o, (pth, op) in byid.items() if o != pid and op.get("source_session") == sess
               and op.get("state") == "quota_stopped" and _real(ctx["convs"][o])       # it must have been continued itself
               and cap < _cap(pth, op) <= real[0]["_start"]]
        if sib:
            return mk("failure", "同一会话在接续开始前又出了另一个 packet，改用它接续（不算接着做）", siblings=sib)
    if not real:
        if any(c.get("state") in _RUNNING_STATES for c in conts):
            return mk("unknown", "接续还在运行")
        why = "接续记录只有 prepared / interrupted，不算接续" if conts else "没有接续记录"
        if now - cap >= _N:
            return mk("failure", f"{why}（已过 {N_HOURS} 小时）")
        return mk("unknown", f"{why}；{N_HOURS} 小时窗口还没结束")
    c = real[0]                                     # only the first real continuation is judged
    if c["_start"] and c["_start"] - cap > _N:
        return mk("failure", f"接续在事件 {N_HOURS} 小时之后才开始")
    if c.get("state") in _RUNNING_STATES:
        return mk("unknown", "接续还在运行")
    h = c.get("handoff_packet")
    if h in byid and h != pid and byid[h][1].get("state") in _CHAIN_STATES and depth < 10:   # it hit a limit too
        v = _lead_verdict(byid[h][0], byid[h][1], ctx, via, depth + 1)
        v.update(id=pid, ts=cap, day=day, chain=[pid] + v["chain"])
        v["from"] = frm
        v["vendors"] = _vend(frm, *v["vendors"])
        return v
    if c.get("state") == "postprocess_error":        # the child ended; relay's own post-processing crashed (#487)
        return mk("unknown", "接续进程已结束但 relay 后处理出错（postprocess_error），改动是否完成没法判，需人工检查")
    if c.get("state") != "exited" or c.get("exit_code") != 0:
        return mk("failure", f"接续以 {c.get('state')} 结束（退出码 {c.get('exit_code')}），活没做完")
    if c.get("changes_observed") is not True:
        return mk("failure", "接续没有观察到改动（changes_observed 不是真）")
    need_intact = c.get("workspace_changed") is not False or git.get("content_fingerprint") == "Unknown"
    intact = bool(_notes(notes, "intact", pid))
    end = c["_end"] or now
    done = [n for n in _notes(notes, "done", pid) if n["_ts"] and end <= n["_ts"] <= end + _N]
    hum = (["intact"] if need_intact and intact else []) + (["done"] if done else [])
    if (intact or not need_intact) and done:
        return mk("success", "在另一家接续、没丢东西、做完并有人工标记", hum=hum)
    missing = ([] if intact or not need_intact else ["intact（workspace_changed 不是 false 或指纹 Unknown）"]) + \
              ([] if done else [f"done（接续结束后 {N_HOURS} 小时内）"])
    if now - end >= _N:
        return mk("failure", "窗口已过，缺人工记录：" + "、".join(missing), hum=hum, failure_basis="missing_human_record")
    return mk("unknown", "等人工补记录：" + "、".join(missing), hum=hum, awaiting_human=True, awaiting=missing)


def _confirmed(pk: dict, cap: float, notes: list[dict], conts: list[dict]) -> dict | None:
    real = _real(conts)
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


def _tally(evs: list[dict], lost_excluded: bool = False) -> dict:
    counted = [e for e in evs if e["verdict"] != "not_attempted"]
    n = len(counted)
    k = sum(e["verdict"] == "success" for e in counted)
    unk = sum(e["verdict"] == "unknown" for e in counted)
    mh = sum(e.get("failure_basis") == "missing_human_record" for e in counted)
    rate = k / n if n else None
    claim_fail = lost_excluded or any(e.get("claim_fail") for e in evs)
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
            "missing_human_record_failures": mh,
            "sensitivity_if_missing_were_success": {
                "rate": ((k + mh) / n if n else None), "quotable": False,
                "note": "不可引用：假设缺人工记录的失败都算成功，只用来看这类失败对比例的影响"},
            "lower_bound_95": clopper_pearson_lower(k, n), "meets_min_events": n >= MIN_EVENTS,
            "meets_min_rate": rate is not None and rate >= MIN_RATE, "claim_fail": claim_fail,
            "verdict": verdict, "verdict_reason": why}


def summarize(events: list[dict], split: str | None = None, through: str | None = None,
              lost_excluded: bool = False) -> dict:
    s = {"combined": _tally(events, lost_excluded),
         "by_role": {r: _tally([e for e in events if e["role"] == r], lost_excluded) for r in ("lead", "sub_agent")},
         "by_pair": {}}
    for e in events:
        s["by_pair"].setdefault(f"{e['role']}:{e['from']}->{e['to']}", []).append(e)
    s["by_pair"] = {k: _tally(v, lost_excluded) for k, v in sorted(s["by_pair"].items())}
    s["lead_note"] = (None if s["by_role"]["lead"]["counted"] else
                      "没有计入的主导事件：主张只覆盖子 agent，主导一侧是 Unknown")
    if not split:
        s["two_periods"] = {"ok": None, "reason": "没给 --quota-split，无法判断两个互不重叠的时段"}
    else:
        a = _tally([e for e in events if e["day"] < split], lost_excluded)
        b = _tally([e for e in events if e["day"] >= split], lost_excluded)
        ok = a["verdict"] == "Pass" and b["verdict"] == "Pass"
        s["two_periods"] = {"ok": ok, "split": split, "first": a, "second": b,
                            "reason": ("两个时段各 ≥ 5 次且都 ≥ 80%" if ok else
                                       "对外引用需要两个时段各 ≥ 5 次计入事件且都 ≥ 80%：现在不满足")}
    return s


# ---- entry ------------------------------------------------------------------------------------------------------

def build(p: Paths, day: str, tz, now: float, workspaces=(), split: str | None = None,
          include_evals: bool = False) -> dict:
    """Events from RULE_START through `day`, judged as of `now`. One original task is one event (a resume chain, or a
    lead packet and the packets its continuation wrote, counts once, judged by the chain's last result)."""
    if split:
        try:
            split = datetime.strptime(split, "%Y-%m-%d").strftime("%Y-%m-%d")
        except ValueError:
            raise ValueError(f"--quota-split must be YYYY-MM-DD (got {split!r})") from None
    notes, bad_files = load_notes(p, tz)
    all_rows = ledger.rows(p)
    hard: dict[str, dict] = {}
    for r in all_rows:
        if r.get("type") == "verify" and r.get("run_id") and not r.get("soft"):
            hard[r["run_id"]] = r
    plain = [r for r in all_rows if not r.get("type") and r.get("run_id") and _t(r.get("ts"))]
    ctx = {"notes": notes, "now": now, "tz": tz, "hard": hard, "all_runs": plain}
    events: list[dict] = []
    excluded = eval_events = capacity = 0
    lost_excluded = False
    for r in plain:
        label = str(r.get("label") or "")
        if label.startswith("review:") or r.get("ephemeral") or label.startswith(INTERNAL):
            continue
        d = _day(r["ts"], tz)
        if d < RULE_START or d > day:
            continue
        rec = _load(p, r["run_id"])
        if rec is None:
            continue
        if not include_evals and ledger.is_eval(r):
            eval_events += _raw_hit(rec)
            continue
        if rec.get("capacity_recovery"):
            capacity += 1
        if not _raw_hit(rec) or not _is_new_root(p, rec):
            continue
        ev = _sub_verdict(p, r, rec, ctx)
        gone = [i for i in ev["chain"] if _notes(notes, "exclude", i)]
        if gone:                                         # an exclude note on any run of the chain excludes the chain
            excluded += 1
            lost_excluded = lost_excluded or any(_notes(notes, "lost", i) for i in ev["chain"])
            continue
        events.append(ev)
    unconfirmed = chain_gone = 0
    roots = _roots(plain, workspaces)
    for root in roots:
        pks, bad = _packets(root)
        bad_files += bad
        convs = {pk["id"]: _continuations(root / ".ccx" / "relay", pk["id"]) for _, pk in pks}
        ctx["convs"], ctx["byid"] = convs, {pk["id"]: (path, pk) for path, pk in pks}

        def status(pid: str) -> str:
            path, pk = ctx["byid"][pid]
            sig = pk.get("quota_signal") if isinstance(pk.get("quota_signal"), dict) else {}
            cap = _t(pk.get("captured_at")) or _mtime(path)
            unconf = pk.get("state") == "rate_limit_unconfirmed" or sig.get("kind") == "rate_limit_unconfirmed"
            sure = pk.get("state") == "quota_stopped" or (sig.get("kind") == "quota" and not unconf)
            if cap is None or not (RULE_START <= _day(cap, tz) <= day) or not (sure or unconf):
                return "out"
            if _notes(notes, "exclude", pid):
                return "excluded"
            if not sure and not _confirmed(pk, cap, notes, convs[pid]):
                return "unconfirmed"
            return "sure" if sure else "confirmed"
        for chain in _chains(pks, convs):
            sts = {i: status(i) for i in chain}
            for i in chain:                               # a lost note on any packet fails the claim, counted or not
                if sts[i] != "out" and _notes(notes, "lost", i):
                    lost_excluded = True
            ok = [i for i in chain if sts[i] in ("sure", "confirmed")]
            if not ok:                                    # the first countable member would be promoted; none is
                seen = [v for v in sts.values() if v != "out"]
                if seen and all(v == "excluded" for v in seen):
                    excluded += 1                         # every member was excluded by a note: that is the exclusion
                elif len(chain) > 1 and seen:
                    chain_gone += 1
                elif sts[chain[0]] == "unconfirmed":
                    unconfirmed += 1
                elif sts[chain[0]] == "excluded":
                    excluded += 1
                continue
            # judged from the first countable member that was continued (a never-continued duplicate joins it); a chain
            # whose head is not countable starts at the first member that is
            continued = sorted((i for i in ok if _real(convs[i])), key=lambda i: _real(convs[i])[0]["_start"] or 0)
            head = continued[0] if continued else ok[0]
            path, pk = ctx["byid"][head]
            ev = _lead_verdict(path, pk, ctx, "relay packet" if sts[head] == "sure" else "relay packet + 人工确认")
            if sts[head] == "confirmed":
                ev["judged_by"]["human"].append("confirm")
            ev["members"] = chain
            if ev["verdict"] != "not_attempted":
                for i in chain:                           # a wait note on any member makes the whole chain not attempted
                    pth, op = ctx["byid"][i]
                    c0 = _cap(pth, op)
                    if [n for n in _notes(notes, "wait", i) if n["_ts"] and c0 <= n["_ts"] <= c0 + _N]:
                        ev.update(verdict="not_attempted", reason="用户选择等额度重置（写在链中的一个 packet 上）")
                        ev["judged_by"]["human"].append("wait")
                        break
            events.append(ev)
    events.sort(key=lambda e: (e["ts"], e["id"]))
    waiting = [{"id": e["id"], "role": e["role"], "awaiting": e["awaiting"]} for e in events if e.get("awaiting_human")]
    return {"rule": "docs/research/2026-11-17-eval-rule-decisions.md 决定 3", "rule_start": RULE_START,
            "n_hours": N_HOURS, "through": day, "now": now, "events": events, "awaiting_human_record": waiting,
            "not_counted": {"unconfirmed_packets": unconfirmed, "excluded_by_note": excluded,
                            "capacity_recovery_runs": capacity, "eval_hub_events": eval_events, "chains_without_countable_member": chain_gone,
                            "unreadable_note_or_packet_files": bad_files},
            "relay_workspaces": [str(r) for r in roots], "notes_file": str(notes_path(p)),
            "summary": summarize(events, split, day, lost_excluded)}


def render(q: dict) -> list[str]:
    s = q["summary"]
    c = s["combined"]

    def frac(t: dict) -> str:
        n = t["counted"]
        lb = t["lower_bound_95"]
        return (f"{t['success']}/{n}" + (f"（{t['success'] / n:.0%}，单侧 95% 下界 {lb:.0%}）" if n else "") +
                f"；失败 {t['failure']}、没判出 {t['unknown']}、未尝试 {t['not_attempted']}")
    L = ["## 额度事件（决定 3：额度用完不断工）", "",
         f"事件从 {q['rule_start']} 起算，到 {q['through']} 为止；{q['n_hours']} 小时内接续才算没断。一个原始任务算一次，按任务链的最终结果判。"
         "证据等级 measured，但不是对照实验。每个事件标了机器判还是人工记录。", "",
         f"- 合并：{frac(c)}。结论 **{c['verdict']}**：{c['verdict_reason']}"]
    for r, name in (("lead", "主导"), ("sub_agent", "子 agent")):
        L.append(f"- {name}：{frac(s['by_role'][r])}")
    if s["lead_note"]:
        L.append(f"- {s['lead_note']}")
    if c["missing_human_record_failures"]:
        sens = c["sensitivity_if_missing_were_success"]["rate"]
        L.append(f"- 其中缺人工记录判失败的 {c['missing_human_record_failures']} 个；敏感性对照（不可引用）：如果这些都算成功，"
                 f"比例是 {sens:.0%}")
    tp = s["two_periods"]
    L.append(f"- 对外引用（两个时段各 ≥ {MIN_EVENTS} 次、都 ≥ {MIN_RATE:.0%}）："
             + ("满足" if tp["ok"] else "不满足" if tp["ok"] is False else "没法判断") + f"。{tp['reason']}")
    nc = q["not_counted"]
    L.append(f"- 不计入但列出：没有人工确认的 rate_limit_unconfirmed packet {nc['unconfirmed_packets']} 个；"
             f"capacity_recovery（模型忙，不是额度）的运行 {nc['capacity_recovery_runs']} 个；评测 hub 里的撞限 {nc['eval_hub_events']} 个；"
             f"人工记录排除（模拟、回放、故意制造）{nc['excluded_by_note']} 个；没有可计入成员的 packet 链 {nc['chains_without_countable_member']} 条；读不了的记录/packet 文件 {nc['unreadable_note_or_packet_files']} 个")
    if q["awaiting_human_record"]:
        L += ["", "还在窗口内、等人工补记录的事件："] + [f"- {w['id']}（{w['role']}）：{'、'.join(w['awaiting'])}"
                                                    for w in q["awaiting_human_record"]]
    if s["by_pair"]:
        L += ["", "| 角色:来源->去向 | 成功/计入 | 失败 | 没判出 |", "|---|---|---|---|"]
        L += [f"| {k} | {t['success']}/{t['counted']} | {t['failure']} | {t['unknown']} |" for k, t in s["by_pair"].items()]
    if q["events"]:
        L += ["", "| 日期 | 角色 | 事件 | 来源->去向 | 判定 | 原因 | 机器 | 人工 |", "|---|---|---|---|---|---|---|---|"]
        for e in q["events"]:
            L.append(f"| {e['day']} | {'主导' if e['role'] == 'lead' else '子 agent'} | {e['id']} | {e['from']}->{e['to']} "
                     f"| {e['verdict']} | {e['reason'].replace('|', '/')} | {','.join(e['judged_by']['machine']) or '-'} "
                     f"| {','.join(e['judged_by']['human']) or '-'} |")
    L += ["", f"人工记录文件：`{q['notes_file']}`（格式见 docs/features.zh.md）。已知缺口：Codex 当主导时撞限不会被自动记下，这一侧是 Unknown。", ""]
    return L
