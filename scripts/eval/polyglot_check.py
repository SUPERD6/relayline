"""Check that each polyglot exercise's hidden tests can grade it (the polyglot counterpart of holdout_check.py):
scored exactly as a unit is (r5.score_exercise), the untouched stub must fail and the exercise's own example solution
must pass, with the selection's test count. Run once before a tagged run; no agent is involved.

The example solution is read here, by the checker, out of a clone in a temporary folder that is then removed; it
never reaches a unit (units get only the stub, ext_repo.exercise_material) and nothing of it is printed or kept.

  python scripts/eval/polyglot_check.py                       # every task, clone from the benchmark's URL
  python scripts/eval/polyglot_check.py --tasks pg-zipper --ext-cache DIR      # a local copy (DIR/polyglot.git)
  python scripts/eval/polyglot_check.py --taskset fresh --ext-cache DIR       # DIR/exercism-python.git
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ext_repo  # noqa: E402
import r5  # noqa: E402
import tasks_polyglot  # noqa: E402


def example_files(cache_repo: Path, task: dict) -> dict[str, bytes]:
    """The exercise's example solution, under the solution files' names (its config pairs them in order)."""
    cfg = json.loads(ext_repo._git(cache_repo, "show", f"{task['commit']}:{task['dir']}/.meta/config.json"))["files"]
    ex = cfg.get("example") or cfg.get("exemplar") or []
    if len(ex) != len(task["solution"]):
        raise ValueError(f"{task['id']}: {len(ex)} example file(s) for {len(task['solution'])} solution file(s)")
    return {sol: ext_repo._git(cache_repo, "show", f"{task['commit']}:{task['dir']}/{e}", data=True)
            for sol, e in zip(task["solution"], ex)}


def check(task: dict, work: Path, cache: Path, source: str | None) -> dict:
    """Stub and example scored as a unit is; returns {"id", "stub", "example", "ok", "problems"}."""
    r5.ext_material(task, work, source, cache=cache)
    t = r5.by_id(task["id"]) if task["id"] in tasks_polyglot.IDS else task
    repo = work / f"check-{task['id']}"
    r5.make_repo(t, repo, work, source)
    stub = r5.score(repo, t, work, source=source)
    clone = ext_repo.cache_path(cache, task["repo"])
    for f, body in example_files(clone, task).items():
        (repo / f).write_bytes(body)
    ex = r5.score(repo, t, work, source=source)
    r5.r2._rmtree(repo)
    probs = ([] if not stub["ok"] else ["the stub passes the hidden tests"]) + \
            ([] if ex["ok"] else [f"the example solution fails: {ex['pytest']}"])
    return {"id": task["id"], "stub": stub["pytest"], "example": ex["pytest"], "ok": not probs, "problems": probs}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tasks", default="", help="comma-separated ids (default: all 30)")
    ap.add_argument("--taskset", choices=("polyglot", "fresh"), default="polyglot")
    ap.add_argument("--ext-cache", default="", help="a folder with polyglot[.git] or, for fresh, exercism-python[.git]")
    a = ap.parse_args(argv)
    taskset = r5.TASKSETS[a.taskset]
    ids = a.tasks.split(",") if a.tasks else taskset.IDS
    tmp = Path(tempfile.mkdtemp(prefix="pgcheck-"))
    bad = 0
    try:
        for tid in ids:
            res = check(taskset.by_id(tid), tmp, tmp / "cache", a.ext_cache or None)
            bad += not res["ok"]
            print(f"{'ok ' if res['ok'] else 'BAD'} {tid:30} stub: {res['stub'][:40]:40} example: {res['example'][:40]}"
                  + (f"  <- {'; '.join(res['problems'])}" if res["problems"] else ""), flush=True)
    finally:
        ext_repo._rmtree(tmp)
    print(f"{len(ids) - bad}/{len(ids)} exercises grade right")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
