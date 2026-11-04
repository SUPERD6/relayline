"""Offline development-data engineering check; reads only named r5 results.jsonl families."""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import re
import statistics

FAMILIES = ("pg1-*", "pg3*", "hc2-*", "p0self-*", "holdout-*")


def analyze(root):
    groups = defaultdict(list)
    inputs = []
    for path in sorted({p for family in FAMILIES for p in root.glob(f"{family}results.jsonl")}):
        inputs.append(path.relative_to(root).as_posix())
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            arm = row.get("arm", "").split("@", 1)[0]
            if arm not in ("self", "ccx2"):
                continue
            # Actual diff is post-outcome: descriptive only, unavailable when routing.
            n = row.get("files_changed")
            files = "Unknown" if n is None else "<=1" if n <= 1 else "2-3" if n <= 3 else ">3"
            ds = row.get("diffstat") or ""
            nums = re.findall(r"(\d+) (?:insertion|deletion)", ds)
            size = sum(map(int, nums)) if nums else None
            band = "Unknown" if size is None else "<=50" if size <= 50 else ">50"
            for feature, value in (("all", "all"), ("files_changed", files), ("diff_lines", band)):
                groups[(path.stem, row.get("taskset", "Unknown"), feature, value, arm)].append(row)
    cells = []
    for key, all_rows in sorted(groups.items()):
        for subset in ("all", "clean"):
            rows = all_rows if subset == "all" else [r for r in all_rows if r.get("env_clean") is True]
            right = sum(r.get("ok") is True and not r.get("error") for r in rows)
            costs = [r.get("usd") for r in rows]
            known = all(isinstance(c, (int, float)) for c in costs)
            total = sum(costs) if known else None
            overhead = [r["lead_only_usd"] for r in rows if isinstance(r.get("lead_only_usd"), (int, float))]
            cells.append(dict(zip(("run", "source", "feature", "band", "arm"), key)) |
                         {"subset": subset, "n": len(rows), "right": right, "usd": total,
                          "tasks": len({r.get("task") for r in rows}),
                          "pins": sorted({str((r.get("fingerprint") or {}).get("pinned_commit", "Unknown"))
                                          for r in rows}),
                          "tags": sorted({str(r.get("tag", "Unknown")) for r in rows}),
                          "cost_per_success": total / right if right and known else None,
                          "clean_n": sum(r.get("env_clean") is True for r in rows),
                          "lead_only_usd_median": statistics.median(overhead) if overhead else None})
    return {"evidence": "engineering check", "data": "historical development set (including reused holdout)",
            "inputs": inputs, "cells": cells, "conclusion": "Unknown: no causal or same-version effect claim",
            "recommendation": {"small_self_files": 1, "small_self_overhead_usd": 0.035,
                               "small_self_run": False, "strict_escalate": False},
            "limitations": ["Actual files/diffstat are post-outcome, not routing-time estimates",
                            "Source, model, version and conditions differ; do not pool runs",
                            "Failures and missing costs retained; zero successes has null cost per success",
                            "No paired threshold validation; conservative existing values retained"]}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("root", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    result = analyze(args.root)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="")
    for cell in result["cells"]:
        if cell["feature"] == "all":
            print(json.dumps(cell))
