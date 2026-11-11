"""Read-only summaries of retained strength/P4 results; standard library, no model calls.

Strength/P4 valid = no error, ccx receipt status is not "error" (a run that failed
itself, e.g. kind=auth, is Unknown, not a task failure), ok is not None, and usd is
known (finite, nonnegative number, not bool). P4 rows carry no top-level status, so
the status rule leaves them unchanged. Outcomes must be bool or None. Successes count valid True
outcomes. Costs include every attempt, including failures and errors; total_usd
and usd_per_success are null if any cost is unknown. usd_per_success is also null
when there are zero successes. known_total_usd retains the known partial cost.
results.jsonl is authoritative, including interrupted runs; report.json's rows
are a fallback only when results.jsonl is absent (never combine both).

--pair A,B defines b = A right and B wrong, c = A wrong and B right. Strength's
usd_per_success_ratio is A's usd_per_success / B's usd_per_success (first arm /
second arm); it is null if either value is null or the denominator is zero,
including when B has zero successes.

--subset settled uses shared_context_ab.TASKS' existing neutral flags: the
known non-neutral tasks, excluding t7-neutral and unknown task IDs. P4 ratios
are B/A of known costs and median wall times, for all and env_clean separately;
cost_unknown remains visible, so a partial cost ratio is not a complete-cost claim.
This script reports observations only, without deciding preregistered gates.

Examples:
  python scripts/eval/unified_summary.py strength OUT --pair on,off --subset settled
  python scripts/eval/unified_summary.py p4 --tag RUN --out DIR --pair self,ccxlong --text
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import p4_long_session as P4
from p5_costs import money
from seven_ab import mcnemar_p
from shared_context_ab import TASKS

VALID_DEFINITION = ("no error, ccx receipt status is not \"error\", ok is not None, "
                    "usd is known (finite nonnegative number, not bool)")
SETTLED_TASKS = {task["id"] for task in TASKS if not task["neutral"]}


def read_rows(path: Path) -> list[dict]:
    """Strict JSONL: never silently drop a malformed or interrupted record."""
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").split("\n") if line.strip()]
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError("result rows must be JSON objects")
    return rows


def strength_rows(out: Path) -> list[dict]:
    if (out / "results.jsonl").is_file():
        return read_rows(out / "results.jsonl")
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    rows = report["rows"]
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("report rows must be a list of JSON objects")
    return rows


def valid(row: dict) -> bool:
    return (not row.get("error") and row.get("status") != "error" and row.get("ok") is not None
            and money(row.get("usd")) is not None)


def check_outcomes(rows: list[dict], scope: str) -> None:
    for index, row in enumerate(rows, 1):
        if row.get("ok") is not None and type(row["ok"]) is not bool:
            raise ValueError(f"{scope} ok must be bool or null: row {index}, "
                             f"arm={row.get('arm')!r}, task={row.get('task')!r}, rep={row.get('rep')!r}")


def strength(rows: list[dict], pair: tuple[str, str] | None = None, subset: str | None = None) -> dict:
    if subset not in (None, "settled"):
        raise ValueError("unknown strength subset")
    check_outcomes(rows, "strength")
    selected = [row for row in rows if subset is None or row.get("task") in SETTLED_TASKS]
    arms = {}
    for arm in sorted({row["arm"] for row in selected} | set(pair or ())):
        group = [row for row in selected if row["arm"] == arm]
        successes = sum(valid(row) and row["ok"] is True for row in group)
        unknown = sum(money(row.get("usd")) is None for row in group)
        known = round(sum(money(row.get("usd")) or 0 for row in group), 8)
        total = None if unknown else known
        arms[arm] = {"attempted": len(group), "valid": sum(map(valid, group)), "successes": successes,
                     "total_usd": total, "known_total_usd": known, "cost_unknown": unknown,
                     "usd_per_success": total / successes if successes and total is not None else None}
    result = {"command": "strength", "subset": subset or "all", "valid_definition": VALID_DEFINITION,
              "successes_definition": "valid rows with ok true",
              "cost_definition": "all attempts; total_usd is null when any cost is unknown",
              "arms": arms}
    if pair:
        pair_rows = [row for row in selected if row["arm"] in pair]
        with_agent = any("agent" in row for row in pair_rows)
        keys = ("task", "agent", "rep") if with_agent else ("task", "rep")
        paired = {}
        for row in pair_rows:
            if any(row.get(key) is None for key in keys):
                raise ValueError("missing pairing key: " + ", ".join(keys))
            entry = paired.setdefault(tuple(row[key] for key in keys), {})
            if row["arm"] in entry:
                raise ValueError("duplicate strength arm/pair key")
            entry[row["arm"]] = row
        a, b_arm = pair
        pairs = [entry for entry in paired.values() if a in entry and b_arm in entry
                 and valid(entry[a]) and valid(entry[b_arm])]
        b = sum(entry[a]["ok"] and not entry[b_arm]["ok"] for entry in pairs)
        c = sum(not entry[a]["ok"] and entry[b_arm]["ok"] for entry in pairs)
        a_cost, b_cost = (arms[arm]["usd_per_success"] for arm in pair)
        result["pair"] = {"a": a, "b_arm": b_arm, "keys": list(keys), "n_pairs": len(pairs),
                          "b": b, "c": c, "mcnemar_p": mcnemar_p(b, c),
                          "usd_per_success_ratio": a_cost / b_cost if a_cost is not None and b_cost else None}
    return result


def p4(rows: list[dict], tag: str, pair: tuple[str, str]) -> dict:
    selected = [row for row in rows if row.get("tag") == tag and row.get("arm") in pair]
    if not selected:
        raise ValueError(f"no P4 rows selected for tag={tag!r} and pair={pair!r}; check --tag and --out")
    for arm in pair:
        if not any(row.get("arm") == arm for row in selected):
            raise ValueError(f"no P4 rows for arm={arm!r}, tag={tag!r}; check --pair, --tag and --out")
    check_outcomes(selected, "p4")
    result = {"command": "p4", "tag": tag, "pair": list(pair), "ratio_direction": "B/A",
              "valid_definition": VALID_DEFINITION,
              "cost_definition": "known cost only; see cost_unknown before interpreting ratios"}
    for name, subset in (("all", selected), ("env_clean", [r for r in selected if r.get("env_clean") is True])):
        arms = {}
        for arm in pair:
            group = [row for row in subset if row["arm"] == arm]
            stats = P4.arm_summary(group)
            arms[arm] = {key: stats[key] for key in
                         ("attempted", "right", "cost_known_usd", "cost_unknown", "wall_median_s")}
            arms[arm]["env_clean"] = sum(row.get("env_clean") is True for row in group)
            arms[arm]["valid"] = sum(map(valid, group))
            if arm == P4.DE.ARM:
                arms[arm]["dispatch"] = {**P4.DE.metrics(group), "stop_reason": P4.DE.stop_reason(group)}
        a, b = (arms[arm] for arm in pair)
        result[name] = {"arms": arms, "ratios": {
            "cost": P4._ratio(b["cost_known_usd"], a["cost_known_usd"]),
            "wall_median": P4._ratio(b["wall_median_s"], a["wall_median_s"])}}
    return result


def table(headers: list[str], rows: list[list]) -> str:
    cells = [headers, *[["null" if value is None else str(value) for value in row] for row in rows]]
    widths = [max(len(row[i]) for row in cells) for i in range(len(headers))]
    return "\n".join("  ".join(value.ljust(width) for value, width in zip(row, widths)) for row in cells)


def text_report(result: dict) -> str:
    if result["command"] == "strength":
        fields = ["attempted", "valid", "successes", "total_usd", "known_total_usd", "cost_unknown", "usd_per_success"]
        lines = ["valid = " + result["valid_definition"], "successes = " + result["successes_definition"],
                 result["cost_definition"], "subset = " + result["subset"],
                 table(["arm", *fields], [[arm, *[stats[key] for key in fields]] for arm, stats in result["arms"].items()])]
        if "pair" in result:
            pair = result["pair"]
            fields = ["a", "b_arm", "n_pairs", "b", "c", "mcnemar_p", "usd_per_success_ratio"]
            lines.append(table(fields, [[pair[key] for key in fields]]))
            lines.append("pair keys = " + ", ".join(pair["keys"]))
            lines.append("b = first arm right, second arm wrong; usd_per_success_ratio = first arm / second arm")
        return "\n".join(lines)
    lines = ["tag = " + result["tag"], "ratios = B/A", "valid = " + result["valid_definition"],
             result["cost_definition"]]
    for subset in ("all", "env_clean"):
        lines.append(subset)
        fields = ["attempted", "valid", "env_clean", "right", "cost_known_usd", "cost_unknown", "wall_median_s"]
        lines.append(table(["arm", *fields], [[arm, *[stats[key] for key in fields]]
                                           for arm, stats in result[subset]["arms"].items()]))
        ratios = result[subset]["ratios"]
        lines.append(table(["B/A", "cost", "wall_median"], [["ratio", ratios["cost"]["ratio"], ratios["wall_median"]["ratio"]]]))
        for arm, stats in result[subset]["arms"].items():
            if "dispatch" in stats:
                dispatch = stats["dispatch"]
                lines.append(arm + " dispatch")
                lines.append(table(list(dispatch), [list(dispatch.values())]))
    return "\n".join(lines)


def parse_pair(value: str) -> tuple[str, str]:
    arms = tuple(arm.strip() for arm in value.split(","))
    if len(arms) != 2 or not all(arms) or arms[0] == arms[1]:
        raise argparse.ArgumentTypeError("pair must be two distinct nonempty arms: A,B")
    return arms


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--text", action="store_true", help="print a human-readable table instead of JSON")
    sub = parser.add_subparsers(dest="command", required=True)
    s = sub.add_parser("strength")
    s.add_argument("out_dir", type=Path)
    s.add_argument("--pair", type=parse_pair)
    s.add_argument("--subset", choices=("settled",))
    p = sub.add_parser("p4")
    p.add_argument("--tag", required=True)
    p.add_argument("--out", type=Path, default=P4.parser().get_default("out"), help="results directory or JSONL file; default: P4 results.jsonl")
    p.add_argument("--pair", required=True, type=parse_pair)
    for command in (s, p):
        command.add_argument("--text", action="store_true", default=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        if args.command == "strength":
            result = strength(strength_rows(args.out_dir), args.pair, args.subset)
        else:
            path = args.out / "results.jsonl" if args.out.is_dir() else args.out
            result = p4(read_rows(path), args.tag, args.pair)
        output = text_report(result) if args.text else json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
