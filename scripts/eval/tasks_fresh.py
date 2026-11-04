"""Pinned, deterministic fresh Exercism tasks for the Stage 3 candidate comparison."""
from __future__ import annotations

import json
from pathlib import Path

from tasks_polyglot import REPOS as POLYGLOT_REPOS

SELECTION_FILE = Path(__file__).with_name("fresh_selection.json")
SELECTION = json.loads(SELECTION_FILE.read_text(encoding="utf-8"))
COMMIT = SELECTION["source"]["commit"]
REPOS = {"exercism-python": {**POLYGLOT_REPOS["polyglot"],
                            "url": SELECTION["source"]["repo"] + ".git"}}
ARMS = ("self", "ccx2cand")
T = [{"id": it["id"], "repo": "exercism-python", "commit": COMMIT, "kind": "exercise",
      "dir": f"exercises/practice/{it['slug']}", "language": "python", "solution": it["solution"],
      "tests": it["test"], "area": f"fresh: {it['slug']}", "difficulty": it["exercism_difficulty"],
      "n_tests": it["tests"], "brief": f"(instructions for {it['slug']}, loaded before the run)"}
     for it in SELECTION["tasks"]]
IDS = [t["id"] for t in T]


def by_id(task_id: str) -> dict:
    return dict(next(t for t in T if t["id"] == task_id))
