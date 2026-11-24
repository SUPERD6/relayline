"""Keep the tests out of the checkout's own .ccx/ (issue #506), loaded by tests/conftest.py.

The eval scripts keep their output folders as module-level paths under the repo (`r5.OUT = ROOT/.ccx/eval/r5`,
`batch.RESULTS`, ...). A test that calls into one of them (`r5.run_unit`) without moving that folder wrote into the
real checkout: `.ccx/eval/r5/streams/untagged/...` grew on every run, in every worktree, unseen by `git status`.

- `_repo_ccx_to_tmp` (autouse): before each test, every module-level `Path` under `<repo>/.ccx` in a loaded module of
  this repo points to the same relative place under the test's `tmp_path` instead. The defaults in the scripts stay
  as they are; a test that sets its own folder still does so on top.
- `pytest_sessionstart` / `pytest_sessionfinish`: a file that appeared under `<repo>/.ccx/eval/` during the session
  fails it and is named, so a new leak is seen at once (it is not deleted: that is for the maintainer).
"""
import os
import sys
from pathlib import Path, PurePath

import pytest

ROOT = Path(__file__).resolve().parents[1]
REPO_CCX = ROOT / ".ccx"
EVAL_DIR = REPO_CCX / "eval"
_before: set[str] | None = None
_in_repo: dict[str, bool] = {}     # module file -> under ROOT; resolved once, not once per test


def _repo_modules():
    for name, mod in list(sys.modules.items()):
        f = getattr(mod, "__file__", None)
        if not isinstance(f, str) or name == __name__:
            continue
        if f not in _in_repo:
            try:
                _in_repo[f] = Path(f).resolve().is_relative_to(ROOT)
            except (OSError, ValueError):
                _in_repo[f] = False
        if _in_repo[f]:
            yield mod


def _ccx_paths(mod):
    for attr, val in list(vars(mod).items()):
        if isinstance(val, PurePath) and not attr.startswith("__"):
            try:
                if Path(val).is_relative_to(REPO_CCX):
                    yield attr, Path(val)
            except (TypeError, ValueError):
                continue


@pytest.fixture(autouse=True)
def _repo_ccx_to_tmp(tmp_path, monkeypatch):
    moved = tmp_path / "repo-ccx"
    for mod in _repo_modules():
        for attr, val in _ccx_paths(mod):
            monkeypatch.setattr(mod, attr, moved / val.relative_to(REPO_CCX))
    yield


def _eval_files() -> set[str]:
    out = set()
    for dirpath, _dirs, files in os.walk(EVAL_DIR):
        out.update(os.path.join(dirpath, f) for f in files)
    return out


def pytest_sessionstart(session):
    global _before
    _before = _eval_files()


def pytest_sessionfinish(session, exitstatus):
    if _before is None:
        return
    new = sorted(_eval_files() - _before)
    if not new:
        return
    shown = "\n".join("  " + os.path.relpath(p, ROOT) for p in new[:20])
    more = f"\n  ... and {len(new) - 20} more" if len(new) > 20 else ""
    msg = (f"\n{len(new)} new file(s) under .ccx/eval/ of the checkout during the test session (issue #506): a test "
           f"wrote outside its tmp_path. Point the folder it used to tmp_path (see tests/repo_outputs.py).\n"
           f"{shown}{more}\n")
    tr = session.config.pluginmanager.get_plugin("terminalreporter")
    if tr is not None:
        tr.write_line(msg, red=True)
    else:
        sys.stderr.write(msg)
    if session.exitstatus == 0:
        session.exitstatus = 1
