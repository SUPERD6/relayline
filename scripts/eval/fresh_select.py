"""Reproduce the fresh selection from two local bare clones, without model results.

Only metadata, import names and test counts are inspected; no solution is executed.
Run polyglot_check.py --taskset fresh separately to validate the grading.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
import sys

import ext_repo

EXERCISM_PIN = "6105f6d9d3ef66ce3d5c8f529d2882af3d76b706"
POLYGLOT_PIN = "7e0611e77b54e2dea774cdc0aa00cf9f7ed6144f"
SALT = "p3-2026-11-04"
# Determined only by the offline stub/example checker, before any model run.
# The originals remain in eligible_ranked; no model outcome can add an exclusion here.
GRADING_REJECTIONS = {"ledger": "stub already passes all 11 hidden tests",
                      "markdown": "stub already passes all 17 hidden tests"}


def digest(slug: str) -> str:
    return hashlib.sha256((slug + SALT).encode("utf-8")).hexdigest()


def imports(text: str) -> set[str]:
    tree = ast.parse(text)
    return {name for n in ast.walk(tree) for name in
            ([a.name.split(".")[0] for a in n.names] if isinstance(n, ast.Import) else
             [n.module.split(".")[0]] if isinstance(n, ast.ImportFrom) and n.module else [])}


def select(exercism: Path, polyglot: Path) -> dict:
    def read(rel):
        return ext_repo._git(exercism, "show", f"{EXERCISM_PIN}:{rel}")

    old = json.loads(Path(__file__).with_name("polyglot_selection.json").read_text(encoding="utf-8"))
    old_slugs = {t["slug"] for t in old["tasks"] + old["dropped"]}
    excluded = set(ext_repo._git(polyglot, "ls-tree", "--name-only",
                                f"{POLYGLOT_PIN}:python/exercises/practice").splitlines())
    if excluded != old_slugs or len(excluded) != 34:
        raise ValueError("the two pinned polyglot exclusion lists disagree")
    lo = min(t["exercism_difficulty"] for t in old["tasks"])
    hi = max(t["exercism_difficulty"] for t in old["tasks"])
    practice = json.loads(read("config.json"))["exercises"]["practice"]
    candidates, rejected = [], []
    for item in practice:
        slug, difficulty = item["slug"], item["difficulty"]
        if slug in excluded:
            continue
        folder = f"exercises/practice/{slug}"
        cfg = json.loads(read(f"{folder}/.meta/config.json"))["files"]
        solution, tests = cfg.get("solution") or [], cfg.get("test") or []
        examples = cfg.get("example") or cfg.get("exemplar") or []
        reason = None
        if not lo <= difficulty <= hi:
            reason = "outside pg1 difficulty range"
        elif len(solution) != 1 or len(examples) != 1 or not tests:
            reason = "requires one implementation, one example/exemplar and hidden tests"
        else:
            # Only import names decide dependency eligibility; solution contents are never stored.
            texts = {f: read(f"{folder}/{f}") for f in [*solution, *tests, *examples]}
            local = {Path(f).stem for f in [*solution, *tests]}
            deps = set().union(*(imports(text) for text in texts.values()))
            third_party = deps - sys.stdlib_module_names - local - {"__future__"}
            if third_party:
                reason = "non-stdlib imports: " + ", ".join(sorted(third_party))
        if reason:
            rejected.append({"slug": slug, "reason": reason})
            continue
        n_tests = sum(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test_")
                      for f in tests for n in ast.walk(ast.parse(texts[f])))
        candidates.append({"id": "fresh-" + slug, "slug": slug, "language": "python",
                           "exercism_difficulty": difficulty, "tests": n_tests,
                           "solution": solution, "test": tests, "sha256": digest(slug)})
    candidates.sort(key=lambda t: (t["sha256"], t["slug"]))
    selected = [t for t in candidates if t["slug"] not in GRADING_REJECTIONS][:30]
    if len(selected) < 30:
        raise ValueError(f"only {len(selected)} exercises after grading exclusions")
    return {
        "about": "Stage 3 fresh Python practice exercises; no model outcomes used for selection.",
        "source": {"repo": "https://github.com/exercism/python", "commit": EXERCISM_PIN, "license": "MIT"},
        "exclusion_source": {"repo": "https://github.com/Aider-AI/polyglot-benchmark", "commit": POLYGLOT_PIN,
                             "slugs": sorted(excluded)},
        "rule": {"practice_only": True, "implementation_files": 1, "third_party_dependencies": False,
                 "example_or_exemplar_required": True, "difficulty_min": lo, "difficulty_max": hi,
                 "difficulty_basis": "inclusive min/max of the 30 pg1 exercises; not a matched histogram",
                 "order": "ascending sha256(UTF-8(slug + salt)), slug tie-break", "salt": SALT, "take": 30,
                 "grading_failure": "reject only if stub passes or example/exemplar fails; advance in this order, record reason"},
        "limitations": ["Fresh means excluded from the 34 polyglot Python exercises, not unseen in model training.",
                         "Exercism ratings do not establish difficulty equivalence for current models."],
        "eligible_count": len(candidates), "eligible_ranked": [t["slug"] for t in candidates],
        "eligibility_rejections": rejected,
        "grading_rejections": [{"slug": slug, "reason": reason} for slug, reason in GRADING_REJECTIONS.items()],
        "tasks": selected,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--exercism-repo", type=Path, required=True)
    ap.add_argument("--polyglot-repo", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=Path(__file__).with_name("fresh_selection.json"))
    a = ap.parse_args(argv)
    selection = select(a.exercism_repo, a.polyglot_repo)
    with a.out.open("w", encoding="utf-8", newline="") as stream:
        json.dump(selection, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
    print(f"selected 30/{selection['eligible_count']} eligible exercises")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
