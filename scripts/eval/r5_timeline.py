"""R8: where a round-5 unit's time, money and tokens went, per role and reason (eval side only: nothing in ccx's
runners or ledger changes for it).

A unit's time is split from two sources it already leaves behind:

  ccx's run records (<hub>/ccx/runs/<id>/run.json, read while the unit's hub still exists)
      role `sub`     a sub-agent attempt; reason: the first attempt of a run, a climb (after which kind: a failed
                     check, blocked, failed, ...), a retry on the same rung, or a run the lead sent back (resume);
                     also a builtin arm's Agent-tool worker (reason `built-in worker`, from the lead's stream: its
                     $ and tokens, not its seconds, which the stream does not split from the lead's)
      role `check`   ccx's acceptance check; reason: the run's final check, or an earlier rung's that failed
      role `review`  the independent review run
      role `fix`     a fix round after a review (its attempts and its check)
  the lead's stream-json (a Claude lead's own stream; no lead for direct / cheapest)
      role `lead`    reason `model` (the API time Claude Code reports, duration_api_ms), `waiting on ccx` (the
                     phase estimate r5.phase_wall makes: ccx blocks the lead, or it waits with show --wait) and
                     `tools and other` (what is left of the wall: its own tool calls, start-up, ...)

Seconds, $ (ccx's ae_usd per attempt; the lead's total_cost_usd) and tokens (all input classes plus output) are
summed per role and reason; `residual_s` is the wall the parts do not explain (negative: they overlap, e.g. a
review running alongside a check, which r5.phase_wall counts once). A check has no $ or tokens of its own.

r5.py stores each unit's timeline in its row (`timeline`) before the unit's hub and stream are removed. This script
reads them back:

  python scripts/eval/r5_timeline.py summary [--taskset holdout] [--tag ho2] [--include-unclean]
  python scripts/eval/r5_timeline.py unit --hub <unit hub> [--stream <lead stream.jsonl>] [--wall 812]

`summary` prints, per arm, each role/reason's total and median seconds, $ and tokens over the units that have a
timeline (only env_clean rows unless --include-unclean, as r5's summary); `unit` builds one from a hub left on disk.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import r2  # noqa: E402

LEAD_TOKEN_KEYS = ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens", "output_tokens")


def _events(text: str):
    for line in (text or "").splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(ev, dict):
                yield ev


def lead_stream(text: str) -> dict:
    """What a Claude lead's stream-json says about the lead itself: its requests (assistant messages of its own,
    built-in sub-agent messages left out, each message id once), its tokens per class, the API seconds, total
    seconds and $ of its result event, and the skills it loaded with the Skill tool."""
    msgs: dict = {}
    worker: dict = {}
    skills: list[str] = []
    calls: set = set()
    fin: dict = {}
    for ev in _events(text):
        if ev.get("type") == "result":
            fin = ev
        if ev.get("type") != "assistant":
            continue
        if ev.get("parent_tool_use_id") is not None:     # a built-in (Agent-tool) worker's message
            wm = ev.get("message") or {}
            if wm.get("id"):
                worker[wm["id"]] = wm.get("usage") or {}
            continue
        m = ev.get("message") or {}
        if m.get("id"):
            msgs[m["id"]] = m.get("usage") or {}
        for i, c in enumerate(m.get("content") or []):
            key = (c.get("id") if isinstance(c, dict) else None) or (m.get("id"), i)
            if isinstance(c, dict) and c.get("type") == "tool_use" and c.get("name") == "Skill" and key not in calls:
                calls.add(key)          # a message's events repeat its id; each call once
                skills.append(str((c.get("input") or {}).get("skill") or (c.get("input") or {}).get("name") or ""))
    usage = {k: sum(int(u.get(k, 0) or 0) for u in msgs.values()) for k in LEAD_TOKEN_KEYS}
    wtok = sum(int(u.get(k, 0) or 0) for u in worker.values() for k in LEAD_TOKEN_KEYS)
    return {"requests": len(msgs), "usage": usage, "tokens": sum(usage.values()),
            "worker_requests": len(worker), "worker_tokens": wtok,
            "api_s": round(float(fin.get("duration_api_ms") or 0) / 1000, 1) if fin else None,
            "duration_s": round(float(fin.get("duration_ms") or 0) / 1000, 1) if fin else None,
            "usd": round(float(fin.get("total_cost_usd") or 0), 6) if fin else None, "skills": skills}


def _tok(usage) -> int:
    return r2._tok(usage) if usage else 0


def _add(parts: dict, role: str, reason: str, s: float = 0.0, usd: float | None = 0.0, tokens: int = 0) -> None:
    cell = parts.setdefault(role, {}).setdefault(reason, {"s": 0.0, "usd": 0.0, "tokens": 0, "n": 0})
    cell["s"] = round(cell["s"] + float(s or 0), 1)
    cell["usd"] = round(cell["usd"] + float(usd or 0), 6)
    cell["tokens"] += int(tokens or 0)
    cell["n"] += 1


def attempt_reason(i: int, att: list[dict]) -> str:
    """Why the i-th attempt of a run happened: its first, a climb after the previous attempt's kind, or a retry of
    the same rung."""
    if i == 0:
        return "first attempt"
    prev, cur = att[i - 1], att[i]
    kind = prev.get("kind") or ("ok" if prev.get("ok") else "failed")
    if prev.get("rung") is not None and prev.get("rung") == cur.get("rung"):
        return f"retry after {kind}"
    return f"climb after {kind}"


def early_checks(rec: dict) -> list[tuple[dict, float]]:
    """(attempt, seconds) of the checks a run's attempts kept besides its final check (record["check"]).

    Before #392 an attempt kept check_seconds only for a failed check that climbed (and, with a check baseline, the
    last attempt also for the final check). Since #392 every check is on its attempt, the final one too: the last
    attempt's check is record["check"] (the same run, or the same object reused), so it is left out here whenever a
    final check with seconds exists and that attempt has check_started_at (#392) or did not fail its check."""
    att = rec.get("attempts") or []
    final = (rec.get("check") or {}).get("seconds")
    out = []
    for i, a in enumerate(att):
        if not a.get("check_seconds"):
            continue
        if i == len(att) - 1 and final and ("check_started_at" in a
                                            or a.get("kind") not in ("check_failed", "check_unverified")):
            continue                                   # that is the final check, counted from record["check"]
        out.append((a, float(a["check_seconds"])))
    return out


def run_parts(hub: Path, run_ids: list) -> tuple[dict, int]:
    """Role/reason parts of a unit's ccx runs (reviews found through a run's review link too); and how many run
    records could not be read."""
    parts: dict = {}
    ids, seen, missing = [str(x) for x in run_ids or []], set(), 0
    while ids:
        rid = ids.pop(0)
        if rid in seen:
            continue
        seen.add(rid)
        rec = r2.record(hub, rid)
        if not rec:
            missing += 1
            continue
        rv = (rec.get("review") or {}).get("run_id")
        if rv and str(rv) not in seen:
            ids.append(str(rv))
        att = rec.get("attempts") or []
        if str(rec.get("label") or "").startswith("review:"):
            for a in att:
                _add(parts, "review", "review", a.get("seconds"), a.get("ae_usd"), _tok(a.get("usage")))
            continue
        fix = bool(rec.get("review_of"))
        early = {id(a): s for a, s in early_checks(rec)}
        for i, a in enumerate(att):
            role = "fix" if fix else "sub"
            reason = "fix round after a review" if fix else \
                ("sent back by the lead (resume)" if i == 0 and rec.get("resumed_from") else attempt_reason(i, att))
            _add(parts, role, reason, a.get("seconds"), a.get("ae_usd"), _tok(a.get("usage")))
            if id(a) in early:
                _add(parts, "fix" if fix else "check", "check of a fix round" if fix else
                     "failed rung's check" if a.get("kind") == "check_failed" else "earlier rung's check",
                     early[id(a)], 0, 0)
        final = (rec.get("check") or {}).get("seconds")
        if final:
            _add(parts, "fix" if fix else "check", "check of a fix round" if fix else "final check", final, 0, 0)
    return parts, missing


def unit_timeline(hub: Path | None, run_ids: list, stream: str = "", wall_s: float | None = None,
                  phases: dict | None = None, worker_usd: float | None = None) -> dict:
    """One unit's timeline: parts per role and reason, the lead's own split (when it has a stream), totals and the
    residual wall. `phases`: r5.phase_wall of the same runs (its lead_wait_s is the lead's waiting).
    A builtin arm's Agent-tool worker is role `sub`, reason `built-in worker`, as ccx's sub-agent is: its tokens are
    its own messages in the lead's stream (parent_tool_use_id set) and its $ is `worker_usd` (the worker model's
    share of the result's modelUsage, r5's sub_usd), taken out of the lead's `model` $. Its seconds stay in the
    lead's parts: the result's API seconds hold both and the stream does not split them (s 0, said here)."""
    parts, missing = run_parts(Path(hub), run_ids) if hub and run_ids else ({}, 0)
    lead = lead_stream(stream) if stream else None
    if lead and lead["requests"]:
        wait = float((phases or {}).get("lead_wait_s") or 0)
        api = float(lead["api_s"] or 0)
        wall = float(wall_s if wall_s is not None else (lead["duration_s"] or 0))
        w_usd = float(worker_usd or 0)
        if lead.get("worker_requests") or w_usd:
            _add(parts, "sub", "built-in worker", 0, w_usd, lead.get("worker_tokens") or 0)
        _add(parts, "lead", "model", api, None if lead["usd"] is None else max(0.0, lead["usd"] - w_usd),
             lead["tokens"])
        if wait:
            _add(parts, "lead", "waiting on ccx", wait, 0, 0)
        _add(parts, "lead", "tools and other", max(0.0, wall - api - wait), 0, 0)
    total = round(sum(c["s"] for r in parts.values() for c in r.values()), 1)
    out = {"parts": parts, "total_s": total,
           "usd": round(sum(c["usd"] for r in parts.values() for c in r.values()), 6),
           "tokens": sum(c["tokens"] for r in parts.values() for c in r.values()), "missing_records": missing}
    if lead:
        out["lead"] = lead
    out["ccx_s"] = round(sum(c["s"] for role, r in parts.items() if role != "lead" for c in r.values()), 1)
    if wall_s is not None:
        # with a lead, its three parts are the wall (the ccx parts sit inside "waiting on ccx"): the residual is
        # what they leave out (negative: the model and waiting estimates together exceed the wall); without one,
        # the wall the ccx parts do not explain (negative: parts that ran at the same time)
        led = sum(c["s"] for c in parts.get("lead", {}).values())
        out["residual_s"] = round(float(wall_s) - (led if "lead" in parts else out["ccx_s"]), 1)
        if "lead" in parts:
            api_wait = sum(c["s"] for k, c in parts["lead"].items() if k != "tools and other")
            if api_wait > float(wall_s):
                out["residual_s"] = round(float(wall_s) - api_wait, 1)
    return out


def _med(xs: list[float]) -> float | None:
    w = sorted(xs)
    return w[len(w) // 2] if w else None


def summarize(rows: list[dict], arm_of=None) -> dict:
    """Per arm (arm_of(row), default the row's arm), per role and reason: units with that part, total and median
    seconds, $ and tokens over the units that carry a timeline."""
    arm_of = arm_of or (lambda r: str(r.get("arm")))
    out: dict = {}
    for r in rows:
        tl = r.get("timeline")
        if not tl:
            continue
        a = out.setdefault(arm_of(r), {"units": 0, "parts": {}})
        a["units"] += 1
        for role, reasons in (tl.get("parts") or {}).items():
            for reason, c in reasons.items():
                cell = a["parts"].setdefault(role, {}).setdefault(
                    reason, {"units": 0, "s": [], "usd": [], "tokens": []})
                cell["units"] += 1
                cell["s"].append(c.get("s") or 0)
                cell["usd"].append(c.get("usd") or 0)
                cell["tokens"].append(c.get("tokens") or 0)
    for a in out.values():
        for reasons in a["parts"].values():
            for reason, c in reasons.items():
                reasons[reason] = {"units": c["units"], "s": round(sum(c["s"]), 1), "s_med": _med(c["s"]),
                                   "usd": round(sum(c["usd"]), 6), "usd_med": _med(c["usd"]),
                                   "tokens": sum(c["tokens"]), "tokens_med": _med(c["tokens"])}
    return out


def lines(summary: dict) -> list[str]:
    out = []
    for arm, a in summary.items():
        out.append(f"{arm} ({a['units']} units with a timeline)")
        for role in sorted(a["parts"]):
            for reason, c in sorted(a["parts"][role].items(), key=lambda kv: -kv[1]["s"]):
                out.append(f"  {role:7} {reason:34} units={c['units']:3} s={c['s']:9.1f} (med {c['s_med']}) "
                           f"${c['usd']:.4f} tok={c['tokens']}")
    return out


def cmd_summary(a) -> int:
    import r5
    rows = r5.tagged(r5.read_jsonl(r5.results_file(a.taskset)), a.tag)
    if not a.include_unclean:
        rows, excluded = r5.clean_rows(rows)
        n = sum(excluded.values())
        if n:
            print(f"excluded {n} rows that are not env_clean ({excluded}); --include-unclean counts them",
                  file=sys.stderr)
    s = summarize(rows, r5.arm_of)
    print(json.dumps(s, ensure_ascii=False, indent=1))
    for ln in lines(s):
        print(ln, file=sys.stderr)
    return 0


def cmd_unit(a) -> int:
    hub = Path(a.hub)
    ids = [r["run_id"] for r in r2.ledger.rows(r2.Paths(hub)) if not r.get("type") and r.get("run_id")]
    stream = Path(a.stream).read_text(encoding="utf-8", errors="replace") if a.stream else ""
    print(json.dumps(unit_timeline(hub, ids, stream, a.wall), ensure_ascii=False, indent=1))
    return 0


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("summary")
    s.add_argument("--taskset", default="r5")
    s.add_argument("--tag", default=None)
    s.add_argument("--include-unclean", action="store_true")
    s.set_defaults(fn=cmd_summary)
    u = sub.add_parser("unit")
    u.add_argument("--hub", required=True)
    u.add_argument("--stream", default="")
    u.add_argument("--wall", type=float, default=None)
    u.set_defaults(fn=cmd_unit)
    return ap


def main(argv=None) -> int:
    a = parser().parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
