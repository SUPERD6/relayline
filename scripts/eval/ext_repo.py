"""External repositories for the hold-out set (backlog C1/7: tasks from another code base).

A task of another repository names it (`repo`) and pins the commit by its full sha. Before the first unit of a run,
each repository is cloned once (`git clone --bare` from its URL, or from a local copy given with --ext-cache) into a
temporary folder outside the work dir, and everything the units need is read out of it into memory (`material`):
the parent's tree as a tar, the commit's own test files, the files the commit changed and its date. The clone is
then removed, so while units run no copy of the fix sits on disk next to them. Every unit gets the repository at the
commit's parent with no future history visible: a fresh `git init` and one commit of the parent's tree, so the
unit's git has no remote, tag, reflog, packed ref or later object. Files the package needs at import time but that
its build backend writes at install time (hatch-vcs's `_version.py`) are written as a stub and committed with `-f`
(they are git-ignored upstream; ccx worktrees must have them too). The hidden acceptance test is the commit's own
version of the test files, and the tests run with `PYTHONPATH=src` (relative: the repository root or a ccx worktree
of it), since nothing is installed. Before scoring, the parent's test folder and test configuration (pyproject.toml,
setup.cfg, tox.ini, pytest.ini and every conftest.py) are put back, so nothing an agent changed there applies to the
hidden test.

Only git reads the cached repositories here; nothing in them is executed except, at scoring time, their tests.
"""
from __future__ import annotations

import io
import json
import os
import re
import shutil
import stat
import subprocess
import tarfile
from pathlib import Path

CODE = (".py", ".toml")
VERSION_STUB = '__version__ = version = "0.0"\n__version_tuple__ = version_tuple = (0, 0)\n'
# files at the repository root that configure pytest (put back from the parent before scoring)
TEST_CONFIG = ("pyproject.toml", "setup.cfg", "tox.ini", "pytest.ini", ".pytest.ini", "conftest.py")


def _git(cwd: Path | None, *args: str, data: bool = False):
    r = subprocess.run(["git", "-c", "user.name=eval", "-c", "user.email=eval@example.invalid",
                        "-c", "core.autocrlf=false", *args], cwd=cwd, capture_output=True)
    if r.returncode:
        raise RuntimeError(f"git {' '.join(args[:3])} failed: {r.stderr.decode('utf-8', 'replace').strip()[:300]}")
    return r.stdout if data else r.stdout.decode("utf-8", "replace")


def _rmtree(p: Path) -> None:
    def onerror(fn, path, _exc):
        os.chmod(path, stat.S_IWRITE)
        fn(path)
    if Path(p).exists():
        shutil.rmtree(p, onerror=onerror)


def cache_key(repo: str) -> str:
    """The cache folder stem of a repository (#400). `owner/name` becomes `<owner>__<name>`, case-folded, with every
    character outside `[a-z0-9._-]` (Windows rejects `:*?"<>|`) and a trailing dot or space replaced by `_`, so
    `a/utils` and `b/utils` never share a clone. A plain name (a frozen task's `repo`, e.g. `polyglot`) is unchanged.
    The old bare-name folder of an owner/name repository is never looked at: that is how two owners would share it."""
    parts = [p for p in str(repo).strip().split("/") if p]
    if len(parts) < 2:
        return str(repo).strip()
    safe = []
    for p in parts[-2:]:
        p = re.sub(r"[^a-z0-9._-]", "_", p.casefold())
        safe.append(p[:-1] + "_" if p.endswith(".") else p)
    return "__".join(safe)


def cache_path(cache: Path, name: str) -> Path:
    return Path(cache) / f"{cache_key(name)}.git"


def fetch(name: str, spec: dict, cache: Path, source: Path | None = None) -> Path:
    """The bare clone of one repository in `cache`, made once: from `source/<name>` (or `source/<name>.git`) when a
    local copy is given, otherwise from the spec's URL. An existing clone is reused as it is."""
    dest = cache_path(cache, name)
    if (dest / "HEAD").exists():
        return dest
    origin = spec["url"]
    if source is not None:
        key = cache_key(name)
        cands = [Path(source) / key, Path(source) / f"{key}.git"]
        local = next((c for c in cands if c.exists()), None)
        if local is None:
            raise FileNotFoundError(f"--ext-cache has no copy of {name} (looked for {', '.join(map(str, cands))})")
        origin = str(local)
    Path(cache).mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    _rmtree(tmp)
    _git(None, "clone", "--bare", "--quiet", origin, str(tmp))
    tmp.rename(dest)
    return dest


def pin(cache_repo: Path, sha: str) -> str:
    """The task's commit must be in the clone under exactly this full sha (a short or moved one is refused)."""
    if len(sha) != 40:
        raise ValueError(f"external tasks pin the full 40-character sha, got {sha!r}")
    got = _git(cache_repo, "rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}").strip()
    if got != sha:
        raise LookupError(f"commit {sha} is not in {cache_repo}")
    parents = _git(cache_repo, "rev-list", "--parents", "-n", "1", sha).split()
    if len(parents) != 2:
        raise ValueError(f"{sha} must have exactly one parent (has {len(parents) - 1})")
    return parents[1]


def write_stubs(dest: Path, spec: dict) -> list[str]:
    """Files the build backend would write at install time; written only when missing."""
    out = []
    for rel in spec.get("stubs") or ():
        f = Path(dest) / rel
        if not f.exists():
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(VERSION_STUB, encoding="utf-8")
            out.append(rel)
    return out


def archive(cache_repo: Path, rev: str) -> bytes:
    return _git(cache_repo, "archive", "--format=tar", rev, data=True)


def extract(data: bytes, dest: Path, names: list[str] | None = None) -> None:
    """The tar's files (or only `names`) into `dest`."""
    with tarfile.open(fileobj=io.BytesIO(data)) as tf:
        members = None if names is None else [m for m in tf.getmembers() if m.name in set(names)]
        if hasattr(tarfile, "data_filter"):
            tf.extractall(dest, members=members, filter="data")
        else:                                      # Python before 3.11.4: git archive writes no links outside
            tf.extractall(dest, members=members)


def tar_names(data: bytes) -> list[str]:
    with tarfile.open(fileobj=io.BytesIO(data)) as tf:
        return [m.name for m in tf.getmembers() if m.isfile()]


def export_tree(cache_repo: Path, rev: str, spec: dict, dest: Path) -> list[str]:
    """The files of `rev` (no .git) in a new folder `dest`, plus the stubs; returns the stubs written."""
    Path(dest).mkdir(parents=True)
    extract(archive(cache_repo, rev), dest)
    return write_stubs(dest, spec)


def repo_from_tar(data: bytes, spec: dict, dest: Path) -> list[str]:
    """`dest` as a new repository holding only this tree in a single commit (plus the stubs); returns the stubs."""
    Path(dest).mkdir(parents=True)
    extract(data, dest)
    stubs = write_stubs(dest, spec)
    _git(dest, "init", "-q")
    _git(dest, "add", "-A")
    if stubs:
        _git(dest, "add", "-f", "--", *stubs)
    _git(dest, "commit", "-q", "--no-verify", "-m", "start")
    return stubs


def make_parent_repo(cache_repo: Path, sha: str, spec: dict, dest: Path) -> dict:
    """`dest` as a new repository holding only the parent's tree in a single commit (plus the stubs)."""
    parent = pin(cache_repo, sha)
    return {"parent": parent, "stubs": repo_from_tar(archive(cache_repo, parent), spec, dest)}


def hidden_tests(cache_repo: Path, sha: str, tests: list[str]) -> dict[str, bytes]:
    """The commit's own versions of the test files."""
    return {t: _git(cache_repo, "show", f"{sha}:{t}", data=True) for t in tests}


def material(cache_repo: Path, sha: str, tests: list[str]) -> dict:
    """Everything a run needs of one task, read out of the clone (which can then be removed): the parent's tree as a
    tar, the hidden test files, the files the commit changed, the commit's date."""
    parent = pin(cache_repo, sha)
    return {"parent": parent, "tar": archive(cache_repo, parent), "tests": hidden_tests(cache_repo, sha, tests),
            "changed": _git(cache_repo, "diff", "--name-only", parent, sha).split(),
            "date": _git(cache_repo, "log", "-1", "--format=%cs", sha).strip()}


def restore_test_setup(dest: Path, data: bytes, spec: dict, keep: list[str] = ()) -> None:
    """Put back the parent's test folders, its root test configuration and its conftest.py files (an agent's own
    conftest.py or pytest settings must not apply to the hidden test). Files the reference change itself touched
    (`keep`) are left as the agent left them."""
    dest, names, keep = Path(dest), tar_names(data), set(keep)
    dirs = tuple(d.rstrip("/") + "/" for d in spec.get("test_dirs") or ("tests",))
    for d in dirs:
        _rmtree(dest / d)
    for f in list(dest.rglob("conftest.py")):
        rel = f.relative_to(dest).as_posix()
        if not rel.startswith(".git/") and rel not in keep:
            f.unlink()
    for n in TEST_CONFIG:
        if n not in keep and n not in names and (dest / n).is_file():
            (dest / n).unlink()
    back = [n for n in names if n not in keep and
            (n.startswith(dirs) or n in TEST_CONFIG or n.rsplit("/", 1)[-1] == "conftest.py")]
    extract(data, dest, back)


def ref_change(cache_repo: Path, sha: str, test_dirs: tuple[str, ...] = ("tests/",)) -> dict:
    """The reference change's size, counted as for this repository: changed lines in code and config files outside
    the test folders (docs and changelogs not counted)."""
    lines, files = 0, []
    for row in _git(cache_repo, "diff", "--numstat", f"{sha}^", sha).splitlines():
        add, rem, name = row.split("\t", 2)
        if name.startswith(test_dirs) or not name.endswith(CODE) or add == "-":
            continue
        lines += int(add) + int(rem)
        files.append(name)
    return {"size": lines, "files": files}


def run_env(spec: dict) -> dict:
    """Environment additions for running the repository's tests uninstalled (relative, so a worktree uses its own).
    pip gets no package index: an agent cannot fetch the released library (which has the fix) or change the shared
    Python that scores every unit."""
    return {"PYTHONPATH": spec.get("pythonpath", "src"), "PIP_NO_INDEX": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1"}


# ------------------------------------------------------------------ exercises (the polyglot task set)

DOCS = ("introduction.md", "instructions.md", "instructions.append.md")


def _tar_of(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for name, body in sorted(files.items()):
            info = tarfile.TarInfo(name)
            info.size, info.mode = len(body), 0o644
            tf.addfile(info, io.BytesIO(body))
    return buf.getvalue()


def exercise_material(cache_repo: Path, sha: str, folder: str, solution: list[str], tests: list[str]) -> dict:
    """One exercise at the pinned commit, read out of the clone: the starting tree (the solution stubs and nothing
    else: no .meta/ with its example solution, no .approaches/, .docs/ or tests) as a tar, the test files (hidden),
    the instruction texts and the commit's date. The test and solution file names come from the task (its
    .meta/config.json, recorded in the selection), and are checked against the exercise's config here."""
    if len(sha) != 40:
        raise ValueError(f"external tasks pin the full 40-character sha, got {sha!r}")
    got = _git(cache_repo, "rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}").strip()
    if got != sha:
        raise LookupError(f"commit {sha} is not in {cache_repo}")
    cfg = json.loads(_git(cache_repo, "show", f"{sha}:{folder}/.meta/config.json"))["files"]
    if sorted(cfg.get("solution") or []) != sorted(solution) or sorted(cfg.get("test") or []) != sorted(tests):
        raise ValueError(f"{folder}: its .meta/config.json names other files than the task "
                         f"(solution {cfg.get('solution')}, test {cfg.get('test')})")
    listed = _git(cache_repo, "ls-tree", "--name-only", f"{sha}:{folder}/.docs").split()
    docs = {n: _git(cache_repo, "show", f"{sha}:{folder}/.docs/{n}") for n in DOCS if n in listed}
    return {"parent": sha, "tar": _tar_of({f: _git(cache_repo, "show", f"{sha}:{folder}/{f}", data=True)
                                           for f in solution}),
            "tests": {t: _git(cache_repo, "show", f"{sha}:{folder}/{t}", data=True) for t in tests},
            "docs": docs, "changed": list(solution),
            "date": _git(cache_repo, "log", "-1", "--format=%cs", sha).strip()}
