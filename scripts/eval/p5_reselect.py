"""Explicit cache-only P5 reselection, with parent and reference full checks."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import tempfile

import long_check as LC
import long_environment as LE
import tasks_long

REPOS = ("more-itertools", "boltons", "pluggy")


def validate(cache, python, task, raw_dir=None):
    result = LE.validate_task(cache, python, task, raw_dir)
    result["reference_full"] = {"rc": None, "summary": "not run: preliminary validation failed"}
    if result["valid"]:
        with tempfile.TemporaryDirectory(prefix="p5-reference-full-") as tmp:
            repo = Path(tmp)/"repo"
            LE.build(LC.material(cache, task)["reference"], repo)
            result["reference_full"] = LE.baseline(
                repo, python, repo/".ccx-eval-tmp-acceptance",
                raw_dir/(task["commit"]+"-reference-full.txt") if raw_dir else None)
        result["valid"] = result["reference_full"]["rc"] == 0
    return result


def select(cache, python, previous, raw_dir=None):
    excluded = {t["commit"] for t in tasks_long.T}
    excluded.update(t["commit"] for t in previous.get("audited_tasks", []))
    # Subsequent reproduction must retain all eight original exclusions.
    excluded.update(previous.get("excluded_commits", []))
    report = LC.validate(cache, python, count=8, repos=REPOS, raw_dir=raw_dir,
                         exclude=excluded, validator=validate)
    report.update(about="P5 fresh reselection, no model outcomes used", checkout_policy=LE.POLICY,
                  baseline_rule="original parent full acceptance exit 0; hidden parent fails; hidden and full reference exit 0",
                  models_called=False, status="Pass" if report["complete"] else "Unknown")
    for row in report["accepted"]:
        row["brief"] = ("Implement the following library change, preserving existing public behavior outside this request. "
                        "Update relevant exports, documentation and annotations if needed.\n\n" + row["subject"])
    return report


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ext-cache", type=Path, required=True)
    p.add_argument("--ext-python", required=True)
    p.add_argument("--previous", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--raw-dir", type=Path, required=True)
    a = p.parse_args(argv)
    if not a.ext_cache.is_dir() or a.output.resolve() == a.previous.resolve():
        p.error("existing cache and separate previous/output manifests required")
    result = select(a.ext_cache, a.ext_python, json.loads(a.previous.read_text(encoding="utf-8")), a.raw_dir)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(result, indent=2)+"\n", encoding="utf-8", newline="")
    return 0 if result["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
