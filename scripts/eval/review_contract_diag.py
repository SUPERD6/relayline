"""Experimental pg3b contract diagnostic; offline unless --run --generator claude is explicit."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from ccx.review_contract import outline
from ccx.review_pipeline import canonical, freeze, generate, validate, verify
from ccx.review_tests import normalized_quote, task_quote
sys.path.insert(0, str(Path(__file__).resolve().parent))
from contract_defects import defect_table, human_table

# Historical development cohort, transcribed from the pinned R2 diagnostic.
# These are NOT fresh evaluation samples or a new correctness determination.
WRONG = {1: "book-store", 3: "bottle-song", 6: "zipper", 8: "scale-generator",
         11: "simple-linked-list", 14: "rest-api", 15: "dot-dsl", 18: "grep",
         19: "phone-number", 20: "go-counting", 22: "paasio", 23: "beer-song",
         24: "tree-building", 26: "forth", 27: "react"}


def sources_for(evidence: Path, index: int, solutions: list[str]) -> dict:
    folder = evidence / f"p2-{index}"
    job = json.loads((folder / "job.json").read_text(encoding="utf-8"))
    tree = (folder / "tree").resolve()
    parts = []
    for name in solutions:
        if Path(name).is_absolute() or ".." in Path(name).parts:
            raise ValueError("unsafe solution path")
        # The replay's committed HEAD is the original stub, not the current solution.
        result = subprocess.run(["git", "-c", f"safe.directory={tree.as_posix()}", "-C", str(tree),
                                 "show", f"HEAD:{name}"], capture_output=True, text=True,
                                encoding="utf-8", timeout=20)
        if result.returncode:
            parts.append("Unknown: original interface unavailable")
        else:
            parts.append(f"### {name}\n{outline(result.stdout)}")
    return {"user_words": job.get("user_task") or "", "task": job["task_text"],
            "interface": "\n".join(parts)}


def score(contract: dict, rules: list[dict], hidden_root: Path | None) -> dict:
    """Literal human-table matching, never a second model judging its own answer.

    Rules must cite a nonempty hidden-test artifact with a matching SHA256. Every
    requirement needs an independently authored, valid, non-Unknown behavior with
    the specified quote AND expected fragments. Unknown oracle rows stay Unknown.
    """
    if not isinstance(rules, list) or not rules or not all(isinstance(rule, dict) for rule in rules):
        return {"coverage": "Unknown", "reason": "No human-reviewed hidden-test table", "covered_ids": []}
    if hidden_root is None:
        return {"coverage": "Unknown", "reason": "No hidden-test evidence root", "covered_ids": []}
    hits, missing = [], []
    for rule in rules:
        required = rule.get("requirements")
        try:
            artifact = (hidden_root / rule["hidden_artifact"]).resolve()
            if hidden_root.resolve() not in artifact.parents or not rule.get("hidden_test"):
                raise ValueError("invalid hidden reference")
            data = artifact.read_bytes()
            if (not data or hashlib.sha256(data).hexdigest() != rule.get("sha256")
                    or rule.get("confirmed") is not True or not isinstance(required, list) or not required):
                raise ValueError("unconfirmed hidden evidence")
        except (OSError, ValueError, KeyError, TypeError):
            return {"coverage": "Unknown", "reason": "Missing or unconfirmed hidden-test evidence", "covered_ids": []}
        for requirement in required:
            if not isinstance(requirement, dict):
                return {"coverage": "Unknown", "reason": "Invalid human-table requirement", "covered_ids": []}
            source, quote = requirement.get("source"), requirement.get("quote")
            expected = requirement.get("expected_contains")
            if (source not in ("task", "user_words") or not task_quote(quote, contract["sources"].get(source, ""))
                    or not isinstance(expected, list) or not expected
                    or not all(isinstance(x, str) and normalized_quote(x) for x in expected)):
                return {"coverage": "Unknown", "reason": "Invalid human-table requirement", "covered_ids": []}
            matching = [b["id"] for b in contract["behaviors"] if b["unknown"] is False
                        and b["source"] == source and normalized_quote(b["quote"]) == normalized_quote(quote)
                        and all(normalized_quote(x) in normalized_quote(b["expected"]) for x in expected)]
            if matching:
                hits.extend(matching)
            else:
                missing.append(rule["hidden_test"])
    if missing and any(b.get("unknown") is True for b in contract["behaviors"]):
        return {"coverage": "Unknown", "reason": "Expectations unresolved", "covered_ids": sorted(set(hits))}
    return {"coverage": "Fail" if missing else "Pass", "covered_ids": sorted(set(hits)),
            "missing_hidden_tests": sorted(set(missing))}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True, help="archived p2-r2-evidence directory")
    parser.add_argument("--contracts", type=Path, help="optional already frozen, independently authored contracts")
    parser.add_argument("--oracle", type=Path, help="controller-only human-reviewed hidden-test mapping JSON")
    parser.add_argument("--hidden-root", type=Path, help="controller-only hidden-test evidence artifacts")
    parser.add_argument("--out", type=Path, help="fresh output directory (never overwrite)")
    parser.add_argument("--budget", type=float, help="required for --run; reservation cap, at most $8 (offline: 8)")
    parser.add_argument("--unit-reservation", type=float, default=0.5, help="future reservation per unit; not a quote")
    parser.add_argument("--generator", choices=("offline", "claude"), default="offline")
    parser.add_argument("--model", default="haiku", help="explicit semantic generator model")
    parser.add_argument("--map-defects", action="store_true", help="extract hidden failures into an unconfirmed human table")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="default: inspect inputs and print estimate only")
    mode.add_argument("--generate", action="store_true", help="generate/freeze offline; no model calls")
    mode.add_argument("--run", action="store_true", help="explicit paid semantic generation; requires --budget")
    args = parser.parse_args(argv)
    if args.run and (args.budget is None or args.generator != "claude" or args.contracts):
        parser.error("--run requires --budget and --generator claude; --contracts is offline only")
    if args.budget is None:
        args.budget = 8.0
    if args.generate and args.generator != "offline":
        parser.error("--generate is offline; semantic calls require --run")
    if args.map_defects and args.hidden_root is None:
        parser.error("--map-defects requires --hidden-root")
    writing = args.generate or args.run
    if (not math.isfinite(args.budget) or not 0 < args.budget <= 8 or
            not math.isfinite(args.unit_reservation) or args.unit_reservation <= 0):
        parser.error("budget must be finite in (0, 8]; unit reservation must be finite and positive")
    reservation = len(WRONG) * args.unit_reservation
    if reservation > args.budget:
        parser.error("15-unit reservation exceeds the budget; no calls or output written")
    if writing and (args.out is None or args.out.exists()):
        parser.error("--generate/--run requires a fresh --out directory")
    selection = json.loads((Path(__file__).with_name("polyglot_selection.json")).read_text(encoding="utf-8"))
    solutions = {t["slug"]: t["solution"] for t in selection["tasks"]}
    rows = []
    # Freeze all contracts BEFORE loading any oracle/hidden evidence into the scorer.
    contracts = {}
    calls, spent, charged, stopped = 0, 0.0, 0.0, False
    for index, slug in WRONG.items():
        key = f"p2-{index}"
        row = {"key": key, "exercise": slug, "coverage": "Unknown", "hidden_ok": False,
               "cohort": "historical-development", "unknown_reasons": []}
        try:
            sources = sources_for(args.evidence, index, solutions[slug])
            row["missing_original"] = not bool(sources["user_words"])
            if writing:
                if args.contracts:
                    saved = json.loads((args.contracts / f"{key}.json").read_text(encoding="utf-8"))
                    if not verify(saved) or saved.get("sources") != sources:
                        raise ValueError("supplied contract hash or sources mismatch")
                    contract = validate(saved, sources)
                elif args.run:
                    if stopped or charged + args.unit_reservation > args.budget + 1e-9:
                        row["unknown_reasons"].append("Budget stopped; no call made")
                        rows.append(row)
                        continue
                    from ccx.contract_semantic import generate_semantic
                    result = generate_semantic(sources, budget=args.unit_reservation, model=args.model)
                    calls += result["model_calls"]
                    amount = result["cost_usd"]
                    row["cost_usd"] = amount
                    charged += args.unit_reservation if amount is None else amount
                    spent += amount or 0.0
                    stopped = amount is None or result["budget_exceeded"] or charged >= args.budget
                    contract = result["contract"]
                else:
                    contract = generate(sources)
                contracts[key] = freeze(contract, args.out / f"{key}.json")
                row["contract_hash"] = contracts[key]["contract_hash"]
        except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
            row["unknown_reasons"].append(f"Material unavailable: {type(exc).__name__}")
        rows.append(row)
    rules, oracle_problem = {}, None
    if args.oracle and writing:
        try:
            rules = json.loads(args.oracle.read_text(encoding="utf-8"))
            if not isinstance(rules, dict):
                raise ValueError("oracle must map unit keys to rule lists")
        except (OSError, ValueError) as exc:
            rules, oracle_problem = {}, f"Oracle unavailable: {type(exc).__name__}"
    for row in rows:
        if oracle_problem:
            row["unknown_reasons"].append(oracle_problem)
        if row["key"] in contracts:
            row.update(score(contracts[row["key"]], rules.get(row["key"], []), args.hidden_root))
    passed = sum(r["coverage"] == "Pass" for r in rows)
    report = {"evidence": "engineering check", "rows": rows, "covered": passed, "denominator": len(WRONG),
              "unknown": sum(r["coverage"] == "Unknown" for r in rows), "gate": "Unknown",
              "model_calls": calls, "spent_usd": spent if charged == spent else None,
              "known_spent_usd": spent, "charged_usd": charged, "budget_stopped": stopped,
              "reservation_usd": reservation,
              "budget_usd": args.budget, "expected_model_cost": "Unknown",
              "note": "Literal coverage diagnostic only; not catches, correctness, or a new efficacy result."}
    if args.map_defects:
        # Generation is complete before controller-only hidden outputs are read.
        table = defect_table(args.hidden_root, WRONG)
        report["defect_rows"] = sum(map(len, table.values()))
        report["defect_mapping"] = "pending human confirmation"
        if writing:
            args.out.mkdir(parents=True, exist_ok=True)
            (args.out / "oracle-template.json").write_text(canonical(table) + "\n", encoding="utf-8", newline="")
            (args.out / "human-review.md").write_text(human_table(table), encoding="utf-8", newline="")
    if writing:
        args.out.mkdir(parents=True, exist_ok=True)
        with (args.out / "report.json").open("x", encoding="utf-8", newline="") as stream:
            stream.write(canonical(report) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 2 if args.run and stopped else 0


if __name__ == "__main__":
    raise SystemExit(main())
