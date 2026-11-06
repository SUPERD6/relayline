"""Read-only optimization evidence summary. Never invokes a model or scans folders.

Pass each authorized JSONL explicitly; output contains basenames and aggregates only.
Missing costs/outcomes stay unknown. Historical report prose is not raw evidence.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import statistics


def number(value):
    return (float(value) if isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and value >= 0 else None)


def total(rows, field):
    values = [number(r.get(field)) for r in rows]
    return sum(values) if rows and all(v is not None for v in values) else None


def aggregate(rows):
    cost = total(rows, "usd")
    if any(r.get("cost_complete") is False for r in rows):
        cost = None
    wall = total(rows, "wall_s")
    right = sum(r.get("ok") is True for r in rows)
    return {"attempted": len(rows), "right": right,
            "outcome_unknown": sum(type(r.get("ok")) is not bool for r in rows),
            "usd": cost, "cost_per_success": cost / right if cost is not None and right else None,
            "wall_median_s": statistics.median(r["wall_s"] for r in rows) if wall is not None else None,
            "wall_total_s": wall, "lead_usd": total(rows, "lead_usd"),
            "child_usd_including_review": total(rows, "ccx_usd"),
            "delegated": sum(r.get("delegated") is True for r in rows),
            "environment_errors": sum(r.get("environment_error") is True for r in rows)}


def ratio(a, b):
    return a / b if a is not None and b is not None and b > 0 else None


def comparison(rows, candidate, long=False):
    arms = {arm: aggregate([r for r in rows if r.get("arm") == arm])
            for arm in ("self", candidate)}
    s, c = arms["self"], arms[candidate]
    ratios = {"cost_per_success": ratio(c["cost_per_success"], s["cost_per_success"]),
              "total_cost": ratio(c["usd"], s["usd"]),
              "wall_median": ratio(c["wall_median_s"], s["wall_median_s"]),
              "lead_cost": ratio(c["lead_usd"], s["lead_usd"])}
    checks = ([ratios["total_cost"] is not None and ratios["total_cost"] <= .8,
               c["right"] >= s["right"],
               ratios["wall_median"] is not None and ratios["wall_median"] <= 2] if long else
              [c["right"] >= s["right"] - 1,
               ratios["cost_per_success"] is not None and ratios["cost_per_success"] <= 1.2])
    valid = all(a["attempted"] and not a["outcome_unknown"] and a["usd"] is not None
                and not a["environment_errors"] for a in arms.values())
    return {"arms": arms, "ratios": ratios,
            "gates": checks, "verdict": "Pass" if valid and all(checks) else "Fail" if valid else "Unknown"}


def summarize(rows, kind):
    if kind == "review":
        cells = {label: Counter(r.get("verdict", "unknown") for r in rows
                                if r.get("hidden_ok") is outcome)
                 for label, outcome in (("wrong", False), ("right", True))}
        wrong, right = cells["wrong"], cells["right"]
        blocked = lambda cell: cell["issues"]
        unknown = lambda cell: sum(v for k, v in cell.items() if k not in ("pass", "issues"))
        worst = {"caught": blocked(wrong), "false_blocks": blocked(right) + unknown(right)}
        best = {"caught": blocked(wrong) + unknown(wrong), "false_blocks": blocked(right)}
        valid = (len(rows) == 29 and sum(wrong.values()) == 15 and sum(right.values()) == 14
                 and total(rows, "usd") is not None)
        verdict = ("Unknown" if not valid else "Pass" if worst["caught"] >= 8 and worst["false_blocks"] <= 2
                   else "Fail" if best["caught"] < 8 or best["false_blocks"] > 2 else "Unknown")
        return {"rows": len(rows), "cells": cells, "usd": total(rows, "usd"),
                "worst": worst, "best": best, "verdict": verdict,
                "tests_written": total(rows, "tests_written"), "tests_run": total(rows, "tests_run"),
                "budget_error_rows": sum(any("budget" in str(c.get("error", "")).lower()
                                             for c in r.get("reviewer_calls", [])) for r in rows),
                "pin": sorted({r.get("pin_commit", "Unknown") for r in rows}),
                "reviewers": sorted({r.get("by", "Unknown") for r in rows}),
                "unknown_reasons": Counter(reason for r in rows for reason in r.get("unknown_reasons", []))}
    long = kind == "long"
    candidate = "ccxlong" if long else "ccx3cand"
    clean = [r for r in rows if r.get("env_clean") is True]
    result = {"rows": len(rows), "clean": len(clean),
              "all": comparison(rows, candidate, long), "env_clean": comparison(clean, candidate, long),
              "pins": sorted({r.get("pinned_commit") or r.get("fingerprint", {}).get("commit", "Unknown") for r in rows}),
              "concurrency": sorted({r.get("fingerprint", {}).get("concurrency", 0) for r in rows}),
              "session_match_false": sum(r.get("session_match") is False for r in rows),
              "cost_check_false": sum(r.get("cost_cumulative_check") is False for r in rows)}
    minimum = 6 if long else 24
    enough = all(result["env_clean"]["arms"][arm]["attempted"] >= minimum for arm in ("self", candidate))
    expected = 8 if long else 30
    complete = all(result["all"]["arms"][arm]["attempted"] == expected for arm in ("self", candidate))
    identity = lambda r: (r.get("round"), r.get("episode"), r.get("turn"), r.get("task"))
    keys = {arm: [identity(r) for r in rows if r.get("arm") == arm] for arm in ("self", candidate)}
    paired = set(keys["self"]) == set(keys[candidate]) and all(len(set(k)) == len(k) for k in keys.values())
    if long:
        episodes = Counter((r.get("arm"), r.get("round"), r.get("episode")) for r in rows)
        complete = complete and len(episodes) == 4 and all(n == 4 for n in episodes.values())
    result["verdict"] = (result["all"]["verdict"] if enough and complete and paired
                         and result["all"]["verdict"] == result["env_clean"]["verdict"] else "Unknown")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--long", type=Path)
    parser.add_argument("--short", type=Path)
    parser.add_argument("--review", type=Path)
    args = parser.parse_args()
    output = {}
    for kind, path in (("long", args.long), ("short", args.short), ("review", args.review)):
        if path is None:
            continue
        data = path.read_bytes()
        rows = [json.loads(line) for line in data.decode("utf-8-sig").splitlines() if line.strip()]
        output[kind] = {"source": path.name, "sha256": hashlib.sha256(data).hexdigest(),
                        **summarize(rows, kind)}
    print(json.dumps(output, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
