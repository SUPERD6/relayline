"""Offline descriptive task-type/model board from scored eval rows; no model calls."""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path

from result_rows import cost, model, rows

TASK_TYPES = {**dict.fromkeys(("mem-errors", "mem-money", "mem-log", "mem-dates", "mem-paths", "mem-json"),
                            "project-convention"),
              **dict.fromkeys(("t1-empty-mean", "t2-slug", "t3-timeout", "t4-loader-name", "t5-date", "t6-negative-qty"),
                             "shared-decision"), "t7-neutral": "self-contained"}


def board(records, task_types=None, outcome="ok"):
    task_types = {**TASK_TYPES, **(task_types or {})}
    scopes = ("all", "clean") if any(r.get("env_clean") is False for r in records) else ("all",)
    result = []
    for scope in scopes:
        groups = defaultdict(list)
        for r in records:
            if scope == "clean" and r.get("env_clean") is not True:
                continue
            kind = r.get("task_type") or task_types.get(r.get("task")) or "Unknown"
            # Do not blend different interventions, versions or evidence sources into one ranking.
            groups[(str(kind), model(r), str(r.get("arm", "Unknown")),
                    str(r.get("code_pin", r.get("commit", "Unknown"))), str(r.get("source", "Unknown")))].append(r)
        for (kind, name, arm, pin, source), group in sorted(groups.items()):
            oks = [r.get(outcome) for r in group]
            k = sum(v is True or (type(v) is int and v == 1) for v in oks)
            unknown = sum(not (type(v) is bool or (type(v) is int and v in (0, 1))) for v in oks)
            costs = [cost(r) for r in group]
            total = round(sum(x for x in costs if x is not None), 6)
            missing_cost = sum(x is None for x in costs)
            result.append({"task_type": kind, "model": name, "arm": arm, "code_pin": pin, "source": source,
                           "scope": scope, "n": len(group), "successes": k, "unknown_outcomes": unknown,
                           "pass_rate": k / len(group) if not unknown else None,
                           "known_total_usd": total, "unknown_costs": missing_cost,
                           "usd_per_success": round(total / k, 6) if k and not missing_cost and not unknown else None,
                           "sample_note": "样本少" if len(group) < 10 else "",
                           "evidence": "historical descriptive; not a current controlled ranking"})
    return result


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--results", action="append", required=True, type=Path)
    p.add_argument("--task-types", type=Path, help="JSON mapping task id to task type")
    p.add_argument("--outcome", default="ok", choices=("ok", "ok_first", "ok_final"))
    p.add_argument("--out", type=Path)
    a = p.parse_args(argv)
    records = [{**r, "source": path.name} for path in a.results for r in rows(path)]
    types = json.loads(a.task_types.read_text(encoding="utf-8")) if a.task_types else {}
    report = {"evidence": "engineering check", "outcome": a.outcome, "groups": board(records, types, a.outcome),
              "limitations": ["Missing model/task type/cost/outcome stays Unknown/null.",
                              "Costs require complete workflow totals including failures, lead, review and repairs.",
                              "No causal comparison; source, code pin and arm are separate strata."]}
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if a.out:
        a.out.write_text(text, encoding="utf-8", newline="")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
