"""Select/validate eight new history tasks from explicit existing git caches only."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import long_check as LC
import tasks_long
import long_environment as LE
from long_candidates import REPOS


def select(cache, python, raw_dir=None, baseline=False):
    excluded = {t["commit"] for t in tasks_long.T}
    report = LC.validate(cache, python, count=8, repos=REPOS, raw_dir=raw_dir, exclude=excluded,
                         **({"validator": LE.validate_task} if baseline else {}))
    report["about"] = "Stage 5: exclude all P4 dev/final tasks; unchanged code-only eligibility; no model outcomes"
    if baseline:
        report.update(checkout_policy=LE.POLICY, baseline_rule="original parent full acceptance command must exit 0 before hidden checks; exclusions independent of model outcomes")
    for row in report["accepted"]:
        # The request comes from commit metadata, never from a patch or a solution.
        message = row["subject"]
        row["brief"] = ("Implement the following library change, preserving existing public behavior outside this request. "
                        "Update relevant exports, documentation and annotations if needed.\n\n" + message)
    return report


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ext-cache", type=Path, required=True)
    p.add_argument("--ext-python", default=sys.executable)
    p.add_argument("--output", type=Path, default=tasks_long.P5_SELECTION_FILE)
    p.add_argument("--raw-dir", type=Path)
    a = p.parse_args(argv)
    if not a.ext_cache.is_dir():
        p.error("--ext-cache must be an existing directory; no download is allowed")
    result = select(a.ext_cache, a.ext_python, a.raw_dir, baseline=True)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="")
    print(f"selected {len(result['accepted'])}/8; complete={result['complete']}")
    return 0 if result["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
