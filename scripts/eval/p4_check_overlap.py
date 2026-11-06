"""Read-only P4 check-overlap audit. Never treats agent logs as reusable acceptance."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

from common import read_jsonl


def objects(value):
    """Inspect structured tool receipts, including JSON encoded in tool output."""
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from objects(child)
    elif isinstance(value, str):
        try:
            parsed = json.loads(value)
        except ValueError:
            return
        if isinstance(parsed, (dict, list)):
            yield from objects(parsed)


def analyze(results, artifacts):
    rows = []
    inputs = read_jsonl(results)
    for row in inputs:
        if row.get("arm") != "ccxlong":
            continue
        root = artifacts / row["streams"]["dir"] / "streams"
        checks = {}
        for event in read_jsonl(root / "lead.jsonl"):
            for obj in objects(event):
                check = obj.get("check")
                if obj.get("run_id") and isinstance(check, dict):
                    # ccx show can repeat a receipt; count each run once.
                    checks[obj["run_id"]] = check
        commands = []
        for stream in sorted((root / "subagents").glob("*/events.*.log")):
            for event in read_jsonl(stream):
                item = event.get("item") or {}
                if (event.get("type") == "item.completed" and item.get("type") == "command_execution"
                        and re.search(r"\bpytest\b", item.get("command", ""))):
                    # Retain only the pytest segment, not a host-specific shell path.
                    segment = re.search(r"(?:python\s+-m\s+)?pytest\b[^;\n]*", item["command"]).group().rstrip("\"'")
                    runtime = re.findall(r"\bin ([0-9.]+)s\b", item.get("aggregated_output", ""))
                    commands.append({"run_id": stream.parent.name, "event_file": stream.name,
                                     "command": segment, "exit_code": item.get("exit_code"),
                                     "pytest_reported_seconds": float(runtime[-1]) if runtime else None})
        known = [c["seconds"] for c in checks.values()
                 if isinstance(c.get("seconds"), (int, float)) and not isinstance(c["seconds"], bool)]
        matching = [c for c in commands if c["run_id"] in checks
                    and c["command"] == checks[c["run_id"]].get("cmd")
                    and c["exit_code"] == checks[c["run_id"]].get("exit")]
        # One candidate per run, not every rerun of the same command.
        candidates = {c["run_id"]: c for c in matching}
        rows.append({"task": row["task"], "controller_checks": list(checks.values()),
                     "child_pytest_commands": commands, "controller_known_seconds": round(sum(known), 3),
                     "controller_unknown_timing": len(checks) - len(known),
                     "command_exit_candidates": list(candidates.values()),
                     "unit_wall_s": row.get("wall_s"), "safe_reusable_checks": 0,
                     "tree_binding": "Unknown: no before/after tree fingerprint in retained events"})
    known = round(sum(r["controller_known_seconds"] for r in rows), 3)
    wall = sum(r["unit_wall_s"] or 0 for r in rows)
    candidates = [c for r in rows for c in r["command_exit_candidates"]]
    return {"evidence": "engineering check: historical event replay; no model calls",
            "source_results": results.name, "source_results_sha256": hashlib.sha256(results.read_bytes()).hexdigest(),
            "source_artifact_run": artifacts.name,
            "historical_code_pins": sorted({r["pinned_commit"] for r in inputs if r.get("pinned_commit")}),
            "rows": rows, "units": len(rows), "controller_known_seconds": known,
            "controller_unknown_timing": sum(r["controller_unknown_timing"] for r in rows),
            "command_exit_candidates": len(candidates),
            "passing_command_exit_candidates": sum(c["exit_code"] == 0 for c in candidates),
            "candidate_pytest_reported_seconds": round(sum(c["pytest_reported_seconds"] or 0 for c in candidates), 3),
            "delegated_wall_seconds": round(wall, 3),
            "controller_known_fraction_of_wall": known / wall if wall and not any(r["controller_unknown_timing"] for r in rows) else None,
            "safe_reusable_seconds": 0, "potential_savings_seconds": "Unknown",
            "decision": "Do not implement reuse: command/exit/tree binding is absent; timing alone cannot authorize skipping acceptance.",
            "limitation": "Known controller time is an upper bound on that observed portion only, not proven duplicate work; missing receipt timing is Unknown."}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--results", type=Path, required=True)
    p.add_argument("--artifacts-root", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args(argv)
    result = analyze(a.results, a.artifacts_root)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(result, indent=2)+"\n", encoding="utf-8", newline="")
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
