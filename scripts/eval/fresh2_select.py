"""A second split from Stage 3's frozen eligible pool; never reads model results."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path

import ext_repo
import fresh_select

SALT = "p3r2-2026-11-05-slim-small"
BASE_FILE = Path(__file__).with_name("fresh_selection.json")
# Offline grading only: the existing r5 grader requires every hidden test to
# run; official alphametics has one skipped test at this pin. Never a model result.
GRADING_REJECTIONS = {"alphametics": "official example: 9 passed, 1 skipped; existing grader rejects skipped tests"}


def digest(slug: str) -> str:
    return hashlib.sha256((slug + SALT).encode("utf-8")).hexdigest()


def ranked() -> list[str]:
    base = json.loads(BASE_FILE.read_text(encoding="utf-8"))
    excluded = {t["slug"] for t in base["tasks"] + base["grading_rejections"]}
    return sorted(set(base["eligible_ranked"]) - excluded, key=lambda s: (digest(s), s))


def select(read) -> dict:
    """`read(relative_path)` reads only the pinned public source, not outcomes.

    The pool already passed Stage 3's shape/dependency/difficulty filters at this
    exact pin. Reuse that frozen pool, not model accuracy or cost information.
    """
    base = json.loads(BASE_FILE.read_text(encoding="utf-8"))
    difficulty = {e["slug"]: e["difficulty"] for e in json.loads(read("config.json"))["exercises"]["practice"]}
    tasks = []
    for slug in [s for s in ranked() if s not in GRADING_REJECTIONS][:30]:
        folder = f"exercises/practice/{slug}"
        cfg = json.loads(read(f"{folder}/.meta/config.json"))["files"]
        tests = cfg["test"]
        n_tests = sum(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test_")
                      for f in tests for n in ast.walk(ast.parse(read(f"{folder}/{f}"))))
        tasks.append({"id": "fresh2-" + slug, "slug": slug, "language": "python",
                      "exercism_difficulty": difficulty[slug], "tests": n_tests,
                      "solution": cfg["solution"], "test": tests, "sha256": digest(slug)})
    return {"about": "Second fresh split; fixed salt and frozen eligibility, no model outcomes used.",
            "source": base["source"], "exclusion_source": base["exclusion_source"],
            "previous_split_excluded": [t["slug"] for t in base["tasks"]],
            "eligibility_source": "fresh_selection.json eligible_ranked at the same source pin",
            # Hash UTF-8 text with LF endings, independent of Git checkout conversion.
            "eligibility_sha256": hashlib.sha256(BASE_FILE.read_text(encoding="utf-8").encode("utf-8")).hexdigest(),
            "rule": {**base["rule"], "salt": SALT}, "eligible_count": len(ranked()),
            "eligible_ranked": ranked(),
            "grading_rejections": base["grading_rejections"] + [
                {"slug": s, "reason": why} for s, why in GRADING_REJECTIONS.items()],
            "limitations": base["limitations"], "tasks": tasks}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--exercism-repo", type=Path, help="local bare clone")
    src.add_argument("--source-tree", type=Path, help="offline files fetched at the source pin; no agent outputs")
    ap.add_argument("--out", type=Path, default=Path(__file__).with_name("fresh2_selection.json"))
    a = ap.parse_args(argv)
    def read(rel):
        if a.source_tree:
            return (a.source_tree / rel).read_text(encoding="utf-8")
        return ext_repo._git(a.exercism_repo, "show", f"{fresh_select.EXERCISM_PIN}:{rel}")
    data = select(read)
    with a.out.open("w", encoding="utf-8", newline="") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"selected {len(data['tasks'])}/{data['eligible_count']} eligible exercises")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
