"""Split one delegation's cost and wall time into four handover items; read-only, no CLI or model calls (#378).

Usage: handover_overhead.py --results FILE [--artifacts DIR] [--ledger FILE] [--out JSON]

The four items (issue #378):
  brief         the lead writing the delegation message (brief): the lead messages that call `ccx run|resume`
  startup       the sub-agent CLI starting up before it works
  agent         the sub-agent doing the task (non-review ledger runs)
  check_review  checking and reviewing: review runs, the lead's turns after a delegation returned (reading the result,
                accepting or re-delegating, final answer), and ccx's own acceptance check

Inputs: result rows (JSONL, as unified_summary reads them: lead_usd, ccx_usd, ccx_review_usd, side_ledger, streams),
the lead stream (`--artifacts`, the directory the rows' `streams` paths are relative to; hash-checked like
lead_overhead.py) and optionally ledger rows (`--ledger`, JSONL, for each run's `seconds`). Rows of arms that never
delegated (self) are counted but skipped.

What is measured and what is not:
  cost.brief / cost.check_review (lead part)   ALLOCATED, not measured: the row's measured lead_usd is shared out over the
      lead's messages by usage weight (default input 1, cache write 1.25, cache read 0.1, output 5: assumed ratios, not a
      price table; change with --weights, the values used are in the --out file); the sum always equals lead_usd.
      cost.check_review is also written as check_review_review (measured) + check_review_lead_allocated. cost.agent and the review cost are measured (ledger ae_usd).
  wall.brief      measured as (end of the delegation message) - (last timestamped event before it). The first message of a
      stream has nothing before it, so a first delegation is Unknown ("lead stream has no start timestamp").
  wall.call       measured: `ccx` tool_use to its tool_result in the lead stream. It contains startup + agent + check +
      review, which the data cannot separate; with ledger rows the agent's own `seconds` are subtracted, and the
      remainder is reported as one combined bound (startup + check + review + ccx bookkeeping), never as four numbers.
  startup, and a separate check/review wall: Unknown. ccx writes no launch-to-first-event timestamp per attempt and keeps
      check_seconds only for a failed check; reviews run in the background and overlap the call.
Shares use only items known for every counted unit (an Unknown item is listed and left out of the denominator).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from statistics import median

sys.path.insert(0, str(Path(__file__).resolve().parent))
from result_rows import number, rows as read_rows  # noqa: E402

ITEMS = ("brief", "startup", "agent", "check_review")
# Assumed ratios between Claude token kinds, used only to share the measured lead_usd out over messages: NOT a price
# table. Override with --weights; the values used are written to --out.
WEIGHTS = {"input_tokens": 1.0, "cache_creation_input_tokens": 1.25, "cache_read_input_tokens": 0.1,
           "output_tokens": 5.0}
WEIGHT_KEYS = {"input": "input_tokens", "cache_write": "cache_creation_input_tokens",
               "cache_read": "cache_read_input_tokens", "output": "output_tokens"}
SHELL_TOOLS = ("Bash", "PowerShell")      # the lead's shell tools; on Windows a ccx call may come through PowerShell
DELEGATE = re.compile(r'(?:^|[\s/\\"])(?:ccx(?:\.py)?|p4_receipt\.py)"?\s+(?:run|resume)\b')
UNKNOWN = "Unknown"


def ts(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def load_stream(row: dict, root: Path):
    """The lead's events, or (None, why). Raises on a hash mismatch or a path outside root, like lead_overhead."""
    s = row.get("streams")
    if not isinstance(s, dict) or not s.get("dir") or not s.get("path"):
        return None, "row has no streams field"
    if s.get("run"):
        cands = [root / s["run"] / s["dir"] / s["path"] / "lead.jsonl"]
    else:      # round-1 rows carry no run directory name: take the one run directory that holds this unit
        cands = sorted(root.glob(f"*/{s['dir']}/{s['path']}/lead.jsonl"))
    cands = [c for c in cands if c.is_file()]
    if len(cands) != 1:
        return None, "lead stream file missing" if not cands else "lead stream path is ambiguous (several runs)"
    path = cands[0].resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("stream path escapes artifact directory")
    raw = path.read_bytes()
    want = next((f.get("sha256") for f in s.get("files") or [] if f.get("file") == "lead.jsonl"), None)
    if want and hashlib.sha256(raw).hexdigest() != want:
        raise ValueError("stream hash mismatch")
    return [json.loads(x) for x in raw.decode("utf-8").splitlines() if x.strip()], None


def lead_messages(events):
    """[{id, first_ts, last_ts, usage, delegates: [tool_use_id], prev_ts}] for the lead's own assistant messages,
    in order. A streamed message arrives as several events with one message id: usage comes from the last."""
    out, index, prev = [], {}, None
    for e in events:
        t = ts(e.get("timestamp")) if e.get("timestamp") else None
        if e.get("type") == "assistant" and not e.get("parent_tool_use_id"):
            m = e.get("message") or {}
            mid = m.get("id") or e.get("uuid")
            if mid not in index:
                index[mid] = {"id": mid, "first_ts": t, "last_ts": t, "usage": {}, "delegates": [], "prev_ts": prev}
                out.append(index[mid])
            rec = index[mid]
            rec["last_ts"] = t if t is not None else rec["last_ts"]
            rec["usage"] = m.get("usage") or rec["usage"]
            for c in m.get("content") if isinstance(m.get("content"), list) else []:
                if (c.get("type") == "tool_use" and c.get("name") in SHELL_TOOLS
                        and DELEGATE.search(str((c.get("input") or {}).get("command", "")))
                        and c.get("id") not in rec["delegates"]):
                    rec["delegates"].append(c.get("id"))
        if t is not None:
            prev = t
    return out


def tool_result_times(events):
    out = {}
    for e in events:
        c = (e.get("message") or {}).get("content")
        if e.get("type") == "user" and isinstance(c, list) and e.get("timestamp"):
            for x in c:
                if x.get("type") == "tool_result" and x.get("tool_use_id"):
                    out[x["tool_use_id"]] = ts(e["timestamp"])
    return out


def weight(usage, weights=None):
    w = weights or WEIGHTS
    return sum(w[k] * float(usage.get(k) or 0) for k in w)


def parse_weights(text):
    """'input=1,cache_write=1.25,cache_read=0.1,output=5' -> WEIGHTS-shaped dict (all four keys required)."""
    out = {}
    for part in text.split(","):
        k, _, v = part.partition("=")
        if k.strip() not in WEIGHT_KEYS or not v.strip():
            raise ValueError(f"--weights: expected {','.join(WEIGHT_KEYS)} as name=number, got {part!r}")
        out[WEIGHT_KEYS[k.strip()]] = float(v)
    if len(out) != 4 or any(x < 0 for x in out.values()) or not any(out.values()):
        raise ValueError("--weights: give all four of input, cache_write, cache_read, output, nonnegative")
    return out


def entries_of(row):
    return [e for e in row.get("side_ledger") or [] if not e.get("type")]


def is_review(entry):
    return str(entry.get("label") or "").startswith("review:")


def known(value, why):
    return {"value": value, "unknown": None} if value is not None else {"value": None, "unknown": why}


def unit(row, events, why_no_stream, ledger_by_id, weights=None):
    cost, wall = {}, {}
    ents = entries_of(row)
    review_ents = [e for e in ents if is_review(e)]
    agent_ents = [e for e in ents if not is_review(e)]
    lead = number(row.get("lead_usd"))
    # --- agent and review cost: measured from the ledger entries
    if row.get("side_cost_status") not in (None, "Pass") or number(row.get("unknown_side_usd")) not in (None, 0.0):
        agent = review = None
        why = "side ledger has runs without a known cost (side_cost_status/unknown_side_usd)"
    else:
        why = None
        parts = [number(e.get("ae_usd")) for e in agent_ents]
        agent = sum(parts) if parts and all(x is not None for x in parts) else None
        parts = [number(e.get("ae_usd")) for e in review_ents]
        review = sum(parts) if all(x is not None for x in parts) else None
        if agent is None:
            why = "side_ledger has no non-review entry with ae_usd"
    cost["agent"] = known(agent, why)
    # --- lead cost allocation
    brief_c = post_c = None
    why_lead = None
    if lead is None:
        why_lead = "row has no lead_usd"
    elif events is None:
        why_lead = why_no_stream
    else:
        msgs = lead_messages(events)
        total_w = sum(weight(m["usage"], weights) for m in msgs)
        if not msgs or total_w <= 0:
            why_lead = "lead stream has no usable assistant usage"
        else:
            first = next((i for i, m in enumerate(msgs) if m["delegates"]), None)
            if first is None:
                why_lead = "lead stream has no ccx run/resume call"
            else:
                brief_c = lead * sum(weight(m["usage"], weights) for m in msgs if m["delegates"]) / total_w
                post_c = lead * sum(weight(m["usage"], weights) for m in msgs[first + 1:] if not m["delegates"]) / total_w
    cost["brief"] = known(brief_c, why_lead)
    cost["startup"] = known(None, "no per-attempt launch-to-first-event cost or timestamp is recorded")
    if review is None or post_c is None:
        cost["check_review"] = known(None, why_lead or "review cost unknown")
    else:
        cost["check_review"] = known(review + post_c, None)
    # the two parts of check_review, kept apart: the review runs are measured, the lead's turns are allocated
    cost["check_review_review"] = known(review, "review cost unknown")
    cost["check_review_lead_allocated"] = known(post_c, why_lead)
    other = None if lead is None or brief_c is None or post_c is None else round(lead - brief_c - post_c, 9)
    cost["lead_other"] = known(None if other is None or other < -1e-6 else max(0.0, other),
                               why_lead if other is None else "data anomaly: allocated parts exceed lead_usd")
    # --- wall
    spans, gaps, gap_unknown = [], [], 0
    if events is not None:
        msgs = lead_messages(events)
        back = tool_result_times(events)
        for m in msgs:
            for tid in m["delegates"]:
                start = m["last_ts"] if m["last_ts"] is not None else m["first_ts"]
                if start is not None and back.get(tid) is not None:
                    spans.append((start, back[tid]))
                if m["prev_ts"] is None or start is None:
                    gap_unknown += 1
                else:
                    gaps.append(start - m["prev_ts"])
    n_calls = sum(len(m["delegates"]) for m in lead_messages(events)) if events is not None else None
    wall["brief"] = (known(sum(gaps), None) if events is not None and gaps and not gap_unknown else
                     known(None, why_no_stream if events is None else
                           "lead stream has no start timestamp, so the first delegation message has no duration"
                           if gap_unknown else "lead stream has no ccx run/resume call"))
    wall["brief"]["delegations"] = {"known": len(gaps), "unknown": gap_unknown}
    wall["brief"]["gaps_s"] = [round(g, 3) for g in gaps]
    # calls issued in parallel (one message, several ccx calls, or overlapping ones) overlap in time: count the union
    call_total, end = (0.0, None) if spans and len(spans) == n_calls else (None, None)
    for a, b in sorted(spans) if call_total is not None else []:
        a = a if end is None else max(a, end)
        call_total += max(0.0, b - a)
        end = b if end is None else max(end, b)
    wall["call"] = known(call_total, why_no_stream if events is None else "a ccx tool call has no matching tool_result")
    agent_s = None
    if ledger_by_id is not None:
        secs = [number((ledger_by_id.get(e.get("run_id")) or {}).get("seconds")) for e in agent_ents]
        agent_s = sum(secs) if secs and all(s is not None for s in secs) else None
    wall["agent"] = known(agent_s, "no ledger rows given (--ledger)" if ledger_by_id is None
                          else "a run of this unit is missing from the ledger or has no seconds")
    wall["startup"] = known(None, "no per-attempt launch-to-first-event timestamp is recorded")
    wall["check_review"] = known(None, "check_seconds is kept only for a failed check; reviews run in the background "
                                       "and overlap the call")
    resid = call_total - agent_s if call_total is not None and agent_s is not None else None
    wall["startup_check_review_combined"] = known(None if resid is None or resid < 0 else resid,
                                                  "needs the call wall and the agent seconds" if resid is None
                                                  else "agent seconds exceed the call wall (clocks differ)")
    return {"cost": cost, "wall": wall, "attempts": len(agent_ents), "delegations": n_calls,
            "reviews": len(review_ents), "episode_wall_s": number(row.get("episode_wall_s", row.get("wall_s")))}


def stats(values):
    return {"n": len(values), "median": median(values) if values else None, "sum": sum(values) if values else None}


def summarize(units):
    """Per item: median over units where it is known, n, how many are Unknown and why; share of the known items."""
    out = {}
    for kind in ("cost", "wall"):
        names = list(ITEMS) + (["lead_other", "check_review_review", "check_review_lead_allocated"] if kind == "cost"
                               else ["call", "startup_check_review_combined"])
        block = {}
        for name in names:
            vals = [u[kind][name]["value"] for u in units if name in u[kind] and u[kind][name]["value"] is not None]
            whys = sorted({u[kind][name]["unknown"] for u in units if name in u[kind]
                           and u[kind][name]["value"] is None})
            block[name] = {**stats(vals), "unknown_units": len(units) - len(vals), "unknown_reasons": whys}
        if kind == "wall":
            gaps = [g for u in units for g in u["wall"]["brief"]["gaps_s"]]
            block["brief_per_delegation_known"] = stats(gaps)
        # shares over the items known for every unit, summed per unit (so the shares add to 100%)
        full = [n for n in names if n in ITEMS or n == "lead_other"]
        usable = [n for n in full if all(u[kind].get(n, {}).get("value") is not None for u in units) and units]
        den = sum(block[n]["sum"] for n in usable) if usable else 0
        enough = len(usable) >= 2 and den > 0     # one known item would show 100%: no share without a comparison
        block["_shares"] = {"over": usable, "left_out_unknown": [n for n in full if n not in usable],
                            "share": {n: (block[n]["sum"] / den if enough else None) for n in usable},
                            "note": None if enough else "fewer than two items known for every unit: no shares"}
        out[kind] = block
    return out


def analyze(rows, artifacts: Path | None, ledger_rows=None, weights=None):
    ledger_by_id = None if ledger_rows is None else {r.get("run_id"): r for r in ledger_rows if r.get("run_id")}
    units, skipped = [], 0
    for row in rows:
        if not entries_of(row) and not row.get("ccx_run_ids"):
            skipped += 1
            continue
        events, why = None, "no --artifacts directory given"
        if artifacts is not None:
            events, why = load_stream(row, artifacts)
        u = unit(row, events, why, ledger_by_id, weights)
        u.update(task=row.get("task"), arm=row.get("arm"), round=row.get("round"), episode=row.get("episode"))
        units.append(u)
    arms = sorted({u["arm"] for u in units}, key=str)
    used = {k: (weights or WEIGHTS)[v] for k, v in WEIGHT_KEYS.items()}
    return {"units": len(units), "skipped_no_delegation": skipped, "allocation_weights": used, "by_arm": {
        a: summarize([u for u in units if u["arm"] == a]) for a in arms}, "all": summarize(units),
        "per_unit": units, "notes": ("cost.brief and the lead part of cost.check_review are allocated from lead_usd by "
                                     "the ratios in allocation_weights (assumed, not a price table), not measured; "
                                     "parallel ccx calls count once (union of their intervals); see the module docstring for what is Unknown and which field would fix it")}


def fmt(v, money=False):
    if v is None:
        return UNKNOWN
    return f"${v:.4f}" if money else f"{v:.1f}s"


def report(result):
    w = result["allocation_weights"]
    lines = [f"units {result['units']}, skipped without delegation {result['skipped_no_delegation']}",
             "(allocated) = the measured lead_usd shared out over lead messages with assumed token-kind ratios "
             f"(not a price table): {', '.join(f'{k}={v:g}' for k, v in w.items())}; an estimate, not a measurement"]
    for arm, s in result["by_arm"].items():
        for kind in ("cost", "wall"):
            lines.append(f"\n[{arm}] {kind}")
            sh = s[kind]["_shares"]
            for name, b in s[kind].items():
                if name.startswith("_") or name == "brief_per_delegation_known":
                    continue
                share = sh["share"].get(name)
                med = fmt(b["median"], kind == "cost")
                why = f"  Unknown in {b['unknown_units']} unit(s): {'; '.join(b['unknown_reasons'])}" \
                    if b["unknown_units"] else ""
                label = name + (" (allocated)" if kind == "cost" and name in ("brief", "lead_other",
                                                                              "check_review_lead_allocated")
                                else " (part allocated)" if kind == "cost" and name == "check_review" else "")
                lines.append(f"  {label:32} median {med:>9}  n={b['n']}  share "
                             f"{'-' if share is None else f'{share:.0%}'}{why}")
            if kind == "wall":
                g = s[kind]["brief_per_delegation_known"]
                lines.append(f"  brief, per delegation message with a known start: median {fmt(g['median'])}, n={g['n']}")
            if sh.get("note"):
                lines.append(f"  {sh['note']}")
            if sh["left_out_unknown"]:
                lines.append(f"  shares leave out (Unknown): {', '.join(sh['left_out_unknown'])}")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--results", type=Path, required=True)
    ap.add_argument("--artifacts", type=Path)
    ap.add_argument("--ledger", type=Path, help="ledger rows (JSONL) for each run's seconds")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--weights", help="assumed token-kind ratios for the lead allocation, e.g. "
                                      "input=1,cache_write=1.25,cache_read=0.1,output=5 (the default; not a price table)")
    a = ap.parse_args(argv)
    result = analyze(read_rows(a.results), a.artifacts, read_rows(a.ledger) if a.ledger else None,
                     parse_weights(a.weights) if a.weights else None)
    if a.out:
        a.out.write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="")
    print(report(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
