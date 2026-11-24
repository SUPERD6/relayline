"""Keep the tests out of the checkout's own .ccx/ (issue #506), loaded by tests/conftest.py.

The eval scripts keep their output folders as module-level paths under the repo (`r5.OUT = ROOT/.ccx/eval/r5`,
`batch.RESULTS`, ...). A test that calls into one of them (`r5.run_unit`) without moving that folder wrote into the
real checkout: `.ccx/eval/r5/streams/untagged/...` grew on every run, in every worktree, unseen by `git status`.

- `_repo_ccx_to_tmp` (autouse): before each test, every module-level `Path` under `<repo>/.ccx` in a loaded module of
  this repo points to the same relative place under the test's `tmp_path` instead. The defaults in the scripts stay
  as they are; a test that sets its own folder still does so on top. Not covered, so such a test passes `tmp_path`
  itself: a path bound as a function default (`def f(out=OUT)`), a path kept as a string (an argparse
  `default=str(...)`), a script run in a subprocess, and a module first imported inside the test body.
- `pytest_sessionstart` / `pytest_sessionfinish`: a file under `<repo>/.ccx/eval/` that appeared or changed (size or
  mtime: an append to an existing results.jsonl counts) during the session fails it and is named, so a leak is seen
  at once. Nothing is deleted: that is for the maintainer. `CCX_TEST_ALLOW_EVAL_WRITES=1` only warns, for a checkout
  where a real evaluation writes there while the tests run.
"""
import os
import sys
from pathlib import Path, PurePath

import pytest

ROOT = Path(__file__).resolve().parents[1]
REPO_CCX = ROOT / ".ccx"
EVAL_DIR = REPO_CCX / "eval"
ALLOW_ENV = "CCX_TEST_ALLOW_EVAL_WRITES"
_before: dict[str, tuple[int, int]] | None = None
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
        if isinstance(val, PurePath):
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


def _eval_files() -> dict[str, tuple[int, int]]:
    """Every file under .ccx/eval/ with its (size, mtime_ns)."""
    out = {}
    for dirpath, _dirs, files in os.walk(EVAL_DIR):
        for f in files:
            p = os.path.join(dirpath, f)
            try:
                st = os.stat(p)
            except OSError:
                continue
            out[p] = (st.st_size, st.st_mtime_ns)
    return out


def _touched(before: dict, after: dict) -> list[str]:
    """Files that are new or changed since `before`."""
    return sorted(p for p, sig in after.items() if before.get(p) != sig)


def _rel(p: str) -> str:
    try:
        return os.path.relpath(p, ROOT)
    except ValueError:      # another drive (Windows)
        return p


def pytest_sessionstart(session):
    global _before
    _before = _eval_files()


def pytest_sessionfinish(session, exitstatus):
    if _before is None:
        return
    touched = _touched(_before, _eval_files())
    if not touched:
        return
    allowed = os.environ.get(ALLOW_ENV) == "1"
    shown = "\n".join("  " + _rel(p) for p in touched[:20])
    more = f"\n  ... and {len(touched) - 20} more" if len(touched) > 20 else ""
    msg = (f"\n{len(touched)} file(s) under .ccx/eval/ of the checkout were written during the test session "
           f"(issue #506): a test wrote outside its tmp_path; point the folder it used to tmp_path (see "
           f"tests/_ccx_repo_outputs.py). If a real evaluation was writing there at the same time, this is not a "
           f"test's doing: set {ALLOW_ENV}=1 to only warn.\n{shown}{more}\n")
    tr = session.config.pluginmanager.get_plugin("terminalreporter")
    if tr is not None:
        tr.write_line(msg, red=not allowed, yellow=allowed)
    else:
        sys.stderr.write(msg)
    if not allowed and exitstatus == 0:
        session.exitstatus = 1
