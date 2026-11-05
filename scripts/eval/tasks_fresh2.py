"""Frozen second split; the lead must preregister a pin before paid evaluation."""
from __future__ import annotations

import json
from pathlib import Path

from tasks_fresh import REPOS

SELECTION = json.loads(Path(__file__).with_name("fresh2_selection.json").read_text(encoding="utf-8"))
ARMS = ("self", "ccx3cand")
T = [{"id": it["id"], "repo": "exercism-python", "commit": SELECTION["source"]["commit"], "kind": "exercise",
      "dir": f"exercises/practice/{it['slug']}", "language": "python", "solution": it["solution"],
      "tests": it["test"], "area": f"fresh2: {it['slug']}", "difficulty": it["exercism_difficulty"],
      "n_tests": it["tests"], "brief": f"(instructions for {it['slug']}, loaded before the run)"}
     for it in SELECTION["tasks"]]
IDS = [t["id"] for t in T]


def by_id(task_id):
    return dict(next(t for t in T if t["id"] == task_id))
