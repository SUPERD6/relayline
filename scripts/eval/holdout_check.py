"""Check a task set the way r5.py scores it: for every task the hidden test fails at the commit's parent and passes
at the commit, the reference change is in the difficulty band, and (for the hold-out set) nothing leaks from r5.

For each task: `git archive` of the parent and of the commit into a scratch folder, today's tests/conftest.py, the
commit's own test files over whatever is there, then only those files run with r5.score (throwaway HOME / CCX_HUB /
CODEX_HOME / CLAUDE_CONFIG_DIR / CCX_CONFIG). No agent CLI is called.

  python scripts/eval/holdout_check.py                       # the hold-out set, 3 tasks at a time
  python scripts/eval/holdout_check.py --taskset r5 --tasks waiting-evals
  python scripts/eval/holdout_check.py --static              # band and leakage only, no pytest
  python scripts/eval/holdout_check.py --ext-python <venv python> [--ext-cache <folder with clones>]

Tasks of other repositories (scripts/eval/ext_repo.py) are checked the same way from a clone fetched once into the
scratch folder: the parent's tree (one fresh commit, plus the install-time stubs) with the commit's test files over
it must fail, the commit's tree must pass, both with PYTHONPATH=src and --ext-python (which needs their test
modules, e.g. freezegun). Running their tests runs that repository's code.
"""
from __future__ import annotations

import argparse
import io
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ext_repo  # noqa: E402
import r5  # noqa: E402
from common import ROOT  # noqa: E402

BAND_LINES = (5, 91)        # changed non-test lines of the reference change (r5: 5-91, median ~40)
BAND_FILES = (1, 5)
CODE = (".py", ".toml")     # what counts: code and config, not docs, CHANGELOG or changes/*.md


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", check=True).stdout


def ref_change(commit: str) -> dict:
    """The reference change's size: changed lines and files in code outside tests/."""
    lines, files = 0, []
    for row in _git("diff", "--numstat", f"{commit}^", commit).splitlines():
        add, rem, name = row.split("\t", 2)
        if name.startswith("tests/") or not name.endswith(CODE) or add == "-":
            continue
        lines += int(add) + int(rem)
        files.append(name)
    return {"size": lines, "files": files}


def _tree(rev: str, dest: Path) -> None:
    dest.mkdir(parents=True)
    data = subprocess.run(["git", "archive", rev], cwd=ROOT, capture_output=True, check=True).stdout
    tarfile.open(fileobj=io.BytesIO(data)).extractall(dest)


class Ctx:
    """Where other repositories are cloned for a check, and from where."""

    def __init__(self, work: Path, source: str | None = None, python: str | None = None):
        self.work, self.source, self.python = work, source or None, python or sys.executable

    def clone(self, task: dict) -> Path:
        return r5.ext_clone(task, self.work, self.source)


def change_of(task: dict, ctx: Ctx | None) -> dict:
    """ref_change for a task of this repository or of another one (from its clone)."""
    if r5.ext_spec(task):
        return ext_repo.ref_change(ctx.clone(task), task["commit"])
    return ref_change(task["commit"])


def static_ext(task: dict, ctx: Ctx) -> list[str]:
    """The checks of `static` that differ for another repository: full sha, one parent, test files at the commit."""
    out = []
    try:
        repo = ctx.clone(task)
    except Exception as e:  # noqa: BLE001
        return [f"cannot fetch or pin: {type(e).__name__}: {e}"[:300]]
    for t in task["tests"]:
        try:
            ext_repo.hidden_tests(repo, task["commit"], [t])
        except RuntimeError:
            out.append(f"{t} missing at {task['commit']}")
    return out


def static(task: dict, against: list[dict], ctx: Ctx | None = None) -> list[str]:
    """Problems found without running anything: band, recorded size, leakage from the other set's tasks."""
    if r5.ext_spec(task):
        out = static_ext(task, ctx)
        if out:
            return out
    else:
        out = []
    ch = change_of(task, ctx)
    if not BAND_LINES[0] <= ch["size"] <= BAND_LINES[1]:
        out.append(f"size {ch['size']} outside {BAND_LINES}")
    if not BAND_FILES[0] <= len(ch["files"]) <= BAND_FILES[1]:
        out.append(f"{len(ch['files'])} files outside {BAND_FILES}")
    if "size" in task and (task["size"], task["files"]) != (ch["size"], len(ch["files"])):
        out.append(f"recorded size/files {task['size']}/{task['files']} != {ch['size']}/{len(ch['files'])}")
    if r5.ext_spec(task):
        same = [o["id"] for o in against if o["commit"] == task["commit"]]
        return out + [f"same commit as {i}" for i in same]
    for t in task["tests"]:
        if not _git("ls-tree", "--name-only", task["commit"], t).strip():
            out.append(f"{t} missing at {task['commit']}")
    for node in task.get("deselect") or ():
        f, _, name = node.partition("::")
        if f not in task["tests"] or f"def {name.split('::')[-1]}(" not in _git("show", f"{task['commit']}:{f}"):
            out.append(f"deselect {node} is not a test of {task['tests']} at {task['commit']}")
    full = _git("rev-parse", task["commit"]).strip()
    for o in against:
        if not r5.ext_spec(o) and _git("rev-parse", o["commit"]).strip() == full:
            out.append(f"same commit as {o['id']}")
    return out


def dynamic(task: dict, work: Path, ctx: Ctx | None = None) -> dict:
    """The hidden test at the parent (must fail) and at the commit (must pass). Another repository: the parent as a
    unit gets it (r5.make_repo), the commit's tree with the same stubs."""
    res = {}
    ext = r5.ext_spec(task)
    for side, rev in (("parent", f"{task['commit']}^"), ("commit", task["commit"])):
        d = Path(tempfile.mkdtemp(prefix=f"{task['id']}-{side}-", dir=work))
        try:
            if not ext:
                _tree(rev, d / "repo")
                res[side] = r5.score(d / "repo", task, d)
                continue
            if side == "parent":
                r5.make_repo(task, d / "repo", ctx.work, ctx.source)
            else:
                ext_repo.export_tree(ctx.clone(task), rev, ext, d / "repo")
            res[side] = r5.score(d / "repo", task, ctx.work, python=ctx.python, source=ctx.source)
        finally:
            shutil.rmtree(d, ignore_errors=True)
    return res


def check(task: dict, against: list[dict], work: Path, run_tests: bool, ctx: Ctx | None = None) -> dict:
    ctx = ctx or Ctx(work)
    probs = static(task, against, ctx)
    try:
        ch = change_of(task, ctx)
    except Exception as e:  # noqa: BLE001 — the fetch problem is already in probs
        ch = {"size": None, "files": [], "error": str(e)[:200]}
    row = {"id": task["id"], "repo": task.get("repo", "this"), "commit": task["commit"], "area": task.get("area"),
           "size": ch["size"], "files": ch["files"], "tests": task["tests"], "problems": probs}
    if probs and ch["size"] is None:
        row["ok"] = False
        return row
    # `boltons` (an older task) and `mahmoud/boltons` (round 2, #400) are one repository
    same_repo = [o for o in against if ext_repo.repo_name(o.get("repo")) == ext_repo.repo_name(task.get("repo"))]
    shared = sorted(set(ch["files"]) & {f for o in same_repo for f in change_of(o, ctx)["files"]})
    if shared:
        row["files_shared_with_other_set"] = shared        # allowed, but worth seeing (a different function)
    if run_tests:
        dyn = dynamic(task, work, ctx)
        row.update(parent=dyn["parent"]["pytest"], commit_result=dyn["commit"]["pytest"])
        if dyn["parent"]["ok"]:
            row["problems"].append("hidden test passes at the parent")
        if not dyn["commit"]["ok"]:
            row["problems"].append("hidden test fails at the commit")
    row["ok"] = not row["problems"]
    return row


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--taskset", choices=sorted(r5.TASKSETS), default="holdout")
    ap.add_argument("--tasks", default="", help="comma-separated ids (default: the whole set)")
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--static", action="store_true", help="band and leakage only, no pytest")
    ap.add_argument("--workdir", default="", help="scratch folder (default: a new temp folder, removed after)")
    ap.add_argument("--ext-cache", default="", help="local clones of the other repositories, named after them")
    ap.add_argument("--ext-python", default="", help="the Python for the other repositories' tests (default: this)")
    a = ap.parse_args(argv)
    mod = r5.TASKSETS[a.taskset]
    ids = a.tasks.split(",") if a.tasks else mod.IDS
    against = [t for name, m in r5.TASKSETS.items() if name != a.taskset for t in m.T]
    work = Path(a.workdir) if a.workdir else Path(tempfile.mkdtemp(prefix="holdout-check-"))
    work.mkdir(parents=True, exist_ok=True)
    try:
        with ThreadPoolExecutor(max_workers=max(1, a.jobs)) as ex:
            ctx = Ctx(work, a.ext_cache, a.ext_python)
            rows = list(ex.map(lambda i: check(mod.by_id(i), against, work, not a.static, ctx), ids))
    finally:
        if not a.workdir:
            shutil.rmtree(work, ignore_errors=True)
    for row in rows:
        print(json.dumps(row, ensure_ascii=False), flush=True)
    bad = [r["id"] for r in rows if not r["ok"]]
    print(f"{len(rows) - len(bad)}/{len(rows)} ok" + (f"; failing: {', '.join(bad)}" if bad else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
