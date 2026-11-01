"""What a passed check actually covered: the test files its pytest / unittest command names, and which of them the run
itself changed, added tests to or wrote. Display only (the receipt, `ccx show`, the ledger); the verdict rules do not
use it.

P1-10 (verdict audit, 2026-10-31, docs/research/2026-10-31-verdict-audit.md): of the receipts after #158 that said ok
but whose hidden tests failed, all 8 had a passed check and a passed review, and the check did not reach the broken
behaviour: 1 never ran the test the hidden one corresponds to (`-k` picked others), 7 ran the sub-agent's version of
the same-named test file. A receipt that says "check passed" should say what it passed on."""
from __future__ import annotations

import fnmatch
import os
import posixpath
import re
import shlex
import subprocess
from pathlib import Path

from .review import edited_tests, is_test_file

SHOWN = 20                                # file names kept in the record; n_files has the full count
WALK_CAP = 5000                           # files looked at when a folder is not in git (then the count is a floor)
_SEP = ("&&", "||", ";", "|")
# options that take a value as the next token (so that value is not a path)
_PYTEST_VAL = {"-k", "-m", "-p", "-c", "-o", "-W", "-n", "--rootdir", "--deselect", "--ignore", "--ignore-glob",
               "--maxfail", "--tb", "--junitxml", "--junit-xml", "--basetemp", "--confcutdir", "--override-ini",
               "--timeout", "--log-level", "--cov", "--cov-report", "--cov-config", "--durations", "--import-mode",
               "--capture", "--log-cli-level", "--dist", "--reruns", "--reruns-delay", "--html", "--randomly-seed",
               "--log-file", "--log-format", "--color", "--count", "--workers", "--tests-per-worker"}
_PYTEST_SHORT_VAL = set("kmpcoWn")        # -xk EXPR: a cluster ending in one of these takes the next token
_UNITTEST_VAL = {"-k", "-s", "-p", "-t", "--start-directory", "--pattern", "--top-level-directory"}
_FILTERS = {"-k", "-m", "--deselect"}     # options that run only part of what the paths name
_DOTTED = re.compile(r"[A-Za-z_]\w*(\.[A-Za-z_]\w*)*")
_SKIP_DIRS = {".git", ".ccx", "node_modules", ".venv", "venv", "env", "__pycache__", ".tox", "build",
              "dist", "site-packages", ".mypy_cache", ".pytest_cache", "vendor", "target"}


def _parts(cmd: str) -> list[list[str]]:
    """The command split into simple commands at && || ; | outside quotes, each as shlex tokens (posix; Windows
    backslashes read as slashes first, since shlex would take them as escapes)."""
    try:
        lex = shlex.shlex((cmd or "").replace("\\", "/"), posix=True, punctuation_chars="&|;<>")
        lex.whitespace_split = True
        toks = list(lex)
    except ValueError:
        toks = (cmd or "").replace("\\", "/").split()
    out, cur = [], []
    for t in toks:
        if t in _SEP:
            out.append(cur)
            cur = []
        else:
            cur.append(t)
    out.append(cur)
    return [p for p in out if p]


def _runner(toks: list[str]) -> tuple[str, list[str]] | None:
    """('pytest' | 'unittest', the arguments after it) for a simple command that runs one, else None."""
    for i, t in enumerate(toks):
        name = t.rsplit("/", 1)[-1].lower().removesuffix(".exe")
        if name in ("pytest", "py.test"):
            return "pytest", toks[i + 1:]
        if t == "-m" and i + 1 < len(toks) and toks[i + 1] in ("pytest", "unittest"):
            return toks[i + 1], toks[i + 2:]
    return None


# commands that only show or pass on a test run's output (`pytest ... | tail -5`): no evidence of their own
_SHOW_ONLY = {"tail", "head", "tee", "cat", "echo", "true", "set", "export"}


def only_tests(cmd: str) -> bool:
    """Every simple command in `cmd` is a pytest / unittest run, a `cd`, or only shows output: nothing else (a
    script, a build, another checker) adds evidence of its own."""
    for toks in _parts(cmd):
        if not toks or _runner(toks) is not None or (toks[0] == "cd" and len(toks) == 2):
            continue
        if toks[0].rsplit("/", 1)[-1].lower().removesuffix(".exe") in _SHOW_ONLY:
            continue
        return False
    return True


def _drop_redirects(args: list[str]) -> list[str]:
    """Without shell redirections: _parts() splits `2>&1` into '2', '>&', '1' and `> out.txt` into '>', 'out.txt'."""
    out, skip = [], False
    for t in args:
        if skip:
            skip = False
            continue
        if t and set(t) <= set("<>&"):
            if out and out[-1].isdigit():
                out.pop()                       # the file descriptor before it (`2>`)
            skip = True                         # what it redirects to
            continue
        out.append(t)
    return out


def parse(cmd: str) -> tuple[list[str], list[str]] | None:
    """(paths the command's pytest / unittest runs name, relative to where the check runs ('.' when it names none: the
    whole folder); the filters that run only part of them, e.g. "-k foo"). None when no part of the command is pytest
    or unittest: then ccx cannot tell what it ran. A `cd DIR` before it makes its paths DIR/..."""
    out: list[str] = []
    filters: list[str] = []
    seen = False
    base = ""
    pattern = None
    for toks in _parts(cmd):
        if toks[0] == "cd" and len(toks) == 2:
            d = toks[1] if toks[1].startswith("/") or ":" in toks[1][:3] else base + toks[1]
            d = posixpath.normpath(d)
            base = "" if d == "." else d + "/"
            continue
        r = _runner(toks)
        if r is None:
            continue
        seen = True
        kind, args = r
        args = _drop_redirects(args)
        vals = _PYTEST_VAL if kind == "pytest" else _UNITTEST_VAL
        paths: list[str] = []
        start = None
        k = 0
        while k < len(args):
            t = args[k]
            nxt = args[k + 1] if k + 1 < len(args) else ""
            if t.startswith("-"):
                opt = t.split("=", 1)[0]
                eaten = False                       # the value is the next token
                if opt in vals:
                    flag = opt
                    val = t.split("=", 1)[1] if "=" in t else nxt
                    eaten = "=" not in t
                elif not t.startswith("--") and len(t) > 2 and "=" not in t:
                    # a short cluster: -ktest_io (value attached), -xk EXPR (no-value flags, then one taking it)
                    short = _PYTEST_SHORT_VAL if kind == "pytest" else {x[1] for x in vals if len(x) == 2}
                    at = next((i for i in range(1, len(t)) if t[i] in short), None)
                    if at is None:
                        flag, val = opt, None
                    else:
                        flag = "-" + t[at]
                        val = t[at + 1:] or nxt
                        eaten = not t[at + 1:]
                else:
                    flag, val = opt, None
                if flag in _FILTERS and val:
                    filters.append(f"{flag} {val}")
                if kind == "unittest" and flag in ("-s", "--start-directory") and val:
                    start = val
                if kind == "unittest" and flag in ("-p", "--pattern") and val:
                    pattern = val
                k += 2 if eaten else 1
                continue
            k += 1
            if kind == "unittest":
                if t == "discover":
                    continue
                if "/" not in t and not t.endswith(".py"):
                    if not _DOTTED.fullmatch(t):
                        continue                    # not a module name: '.', '..' and the like name nothing here
                    t = t.replace(".", "/")         # tests.test_x(.Case.test): resolved to a file in covered()
            if "::" in t:
                filters.append(t)                   # a node id runs one test of that file
            paths.append(t.split("::", 1)[0])
        if kind == "unittest" and not paths:
            paths = [start or "."]
            pattern = pattern or "test*.py"
        out.extend(posixpath.normpath(base + p) if base and not p.startswith("/") and ":" not in p[:3] else p for p in (paths or ["."]))
    if pattern:
        filters.append(f"pattern {pattern}")
    return (list(dict.fromkeys(out)), list(dict.fromkeys(filters))) if seen else None


def targets(cmd: str) -> list[str] | None:
    """parse()'s paths alone."""
    r = parse(cmd)
    return None if r is None else r[0]


def _rel(p: Path, repo: Path) -> str | None:
    try:
        r = os.path.relpath(os.path.abspath(p), os.path.abspath(repo)).replace("\\", "/")
        if r.startswith(".."):                # a junction / symlink / short name on one side: compare real paths
            r = os.path.relpath(p.resolve(), repo.resolve()).replace("\\", "/")
        return r
    except ValueError:                        # another drive
        return None


def _resolve(t: str, cwd: Path) -> Path | None:
    """A target as an existing path under cwd (a unittest dotted name: the longest prefix that is a .py file)."""
    p = cwd / t
    if p.exists():
        return p
    parts = t.split("/")
    for k in range(len(parts), 0, -1):
        f = cwd.joinpath(*parts[:k]).with_suffix(".py")
        if f.is_file():
            return f
    return None


def _pytest_name(n: str) -> bool:
    """pytest's default python_files: test_*.py or *_test.py."""
    return n.endswith(".py") and (n.startswith("test_") or n.endswith("_test.py"))


def _wanted(n: str, pattern: str | None) -> bool:
    return fnmatch.fnmatch(n, pattern) if pattern else _pytest_name(n)


def _folder_tests(d: Path, pattern: str | None = None) -> tuple[list[Path], bool]:
    """Test files in a folder: from git (fast, .gitignore respected), else a capped walk. (files, complete)."""
    from .workspace import SIBLING_WORKTREE_DIR
    skip_dirs = _SKIP_DIRS | {SIBLING_WORKTREE_DIR}
    try:
        r = subprocess.run(["git", "-C", str(d), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                           capture_output=True, timeout=20)
        if r.returncode == 0:
            names = [n for n in r.stdout.decode("utf-8", "replace").split("\0") if n]
            return [d / n for n in sorted(names) if _wanted(n.rsplit("/", 1)[-1], pattern)
                    and not set(n.split("/")[:-1]) & skip_dirs], True
    except (OSError, subprocess.SubprocessError):
        pass
    found, seen = [], 0
    for root, sub, files in os.walk(d):
        sub[:] = sorted(x for x in sub if x not in skip_dirs and not x.startswith("."))
        for n in sorted(files):
            seen += 1
            if seen > WALK_CAP:
                return found, False
            if _wanted(n, pattern):
                found.append(Path(root) / n)
    return found, True


def covered(tgts: list[str], cwd: Path, repo: Path, pattern: str | None = None) -> tuple[list[str], list[str], bool]:
    """(test files the targets run, as repo paths; the targets that are folders, as repo paths; complete). Targets
    that do not exist are left out (an option value read as a path); when none exists, the folder itself counts."""
    files: list[str] = []
    dirs: list[str] = []
    complete = True
    found = [p for p in (_resolve(t, cwd) for t in tgts) if p is not None] or [cwd]
    for p in found:
        if p.is_dir():
            r = _rel(p, repo)
            if r is not None:
                dirs.append("." if r == "." else r.rstrip("/") + "/")
            got, done = _folder_tests(p, pattern)
            complete = complete and done
            for f in got:
                rf = _rel(f, repo)
                if rf is not None and rf not in files:
                    files.append(rf)
        else:
            r = _rel(p, repo)
            if r is not None and r not in files:
                files.append(r)
    return files, dirs, complete


def new_tests(diff: str) -> list[str]:
    """Test files the run created (a diff part from /dev/null)."""
    out: list[str] = []
    new = False
    for ln in diff.splitlines():
        if ln.startswith("--- "):
            new = ln[4:].strip() == "/dev/null"
        elif ln.startswith("+++ ") and new:
            f = ln[4:].strip()
            f = f[2:] if f.startswith("b/") else f
            if is_test_file(f) and f not in out:
                out.append(f)
            new = False
    return out


def added_to_tests(diff: str) -> list[str]:
    """Test files that existed before the run and only gained lines (edited_tests leaves those out by design)."""
    out: list[str] = []
    old = None
    for ln in diff.splitlines():
        if ln.startswith("--- "):
            old = ln[4:].strip()
            old = None if old == "/dev/null" else old[2:] if old.startswith("a/") else old
        elif ln.startswith("+++ "):
            continue
        elif old and ln.startswith("+") and is_test_file(old) and old not in out:
            out.append(old)
    edited = set(edited_tests(diff))
    return [f for f in out if f not in edited]


_REWRITE = re.compile(r"\bassert|\bdef test|\.assert[A-Z]|pytest\.raises|self\.fail|\bexpected\b")


def rewritten_tests(diff: str) -> list[str]:
    """Test files that existed before the run and lost or changed a line that tests something: an assertion, a test
    function's head, an expected value. Edits only to imports or set-up (a new name imported for a test added below)
    leave the earlier tests in force, so such a file is no sign the check's basis is the sub-agent's own (P0-8)."""
    out: list[str] = []
    old = None
    for ln in diff.splitlines():
        if ln.startswith("--- "):
            old = ln[4:].strip()
            old = None if old == "/dev/null" else old[2:] if old.startswith("a/") else old
        elif ln.startswith("+++ "):
            continue
        elif old and ln.startswith("-") and is_test_file(old) and old not in out and _REWRITE.search(ln):
            out.append(old)
    return out


def _key(f: str) -> str:
    return f.replace("\\", "/").lstrip("./").lower()


def summarize(cmd: str, cwd: Path, repo: Path, edited: list[str], written: list[str],
              added: list[str] | None = None, rewritten: list[str] | None = None) -> dict:
    """The record's check["covers"]: {"files" (at most SHOWN), "n_files", "dirs"?, "partial"?, "filtered"?,
    "edited"?, "basis_changed"?, "added_to"?, "written"?, "own_tests_only"?, "self_authored"?}, or {"unknown": why} when
    the command is not pytest / unittest. `rewritten` (rewritten_tests; default: all of `edited`): the edited files
    that count as the sub-agent's own yardstick for self_authored."""
    r = parse(cmd)
    if r is None:
        return {"unknown": "not a pytest / unittest command: which tests it ran is not known"}
    tgts, filters = r
    pattern = next((x[8:] for x in filters if x.startswith("pattern ")), None)
    filters = [x for x in filters if not x.startswith("pattern ")]
    files, dirs, complete = covered(tgts, cwd, repo, pattern)
    keys = {_key(f) for f in files}
    under = [""] if "." in dirs else [_key(d) for d in dirs]

    def inside(f: str) -> bool:
        k = _key(f)
        if k.rsplit("/", 1)[-1] == "conftest.py":       # fixtures of every test below its folder
            d = k[: -len("conftest.py")]
            return any(x.startswith(d) for x in keys) or any(u.startswith(d) or d.startswith(u) for u in under)
        return k.endswith(".py") and (k in keys or any(k.startswith(d) for d in under))
    ed = [f for f in edited if inside(f)]
    ad = [f for f in (added or []) if inside(f) and f not in ed]
    wr = [f for f in written if inside(f) and f not in ed]
    out: dict = {"files": files[:SHOWN], "n_files": len(files)}
    if dirs:
        out["dirs"] = dirs
    if not complete:
        out["partial"] = True              # a big folder outside git: the walk stopped, n_files is a floor
    if filters:
        out["filtered"] = filters[:3]      # -k / -m / --deselect / a node id: only part of those files ran
    if ed:
        out["edited"] = ed
        out["basis_changed"] = True        # the check passed on tests the sub-agent changed: its own yardstick
    if ad:
        out["added_to"] = ad
    if wr:
        out["written"] = wr
    if files and {_key(f) for f in written} >= keys and not ed:
        out["own_tests_only"] = True       # every test the check runs is one the sub-agent wrote
    own = [f for f in ed if rewritten is None or _key(f) in {_key(x) for x in rewritten}]
    if files and complete and {_key(f) for f in [*written, *own]} >= keys and only_tests(cmd):
        # P0-8: every test file the check ran is one this run wrote or changed: its pass is the sub-agent's own
        # yardstick (pg1: 18/18 hidden-test failures passed a test_own.py). added_to is left out: the tests those
        # files had before the run still ran; so is a command that also runs something else (only_tests)
        out["self_authored"] = True
    return out


def self_checked(cov: dict | None) -> bool:
    """The check's basis is the sub-agent's own (coverage.summarize's self_authored)."""
    return bool((cov or {}).get("self_authored"))


SELF_CHECKED = "ok_self_checked"     # the run's kind: passed, but only on its own tests
ON_SELF_CHECKED = ("off", "review", "rung")
SELF_CHECKED_NOTE = ("check basis self-authored: every test the check ran was written or changed by the sub-agent "
                     "in this run, not independently verified")


def reviewed_ok(record: dict) -> bool:
    """An ok_self_checked run whose review was told to hold it against the task text, and passed (not downgraded)."""
    rv = record.get("review") or {}
    return bool(rv.get("self_checked") and rv.get("verdict") == "pass" and not rv.get("downgraded"))


def on_self_checked(cfg: dict) -> str:
    """[escalate] on_self_checked: "review" (default; an unknown value too), "off" or "rung"."""
    v = str((cfg.get("escalate") or {}).get("on_self_checked", "review")).strip().lower()
    return v if v in ON_SELF_CHECKED else "review"


def text(cov: dict | None, limit: int = 3) -> str:
    """'covers: a.py, b.py +2 more | basis changed: a.py edited by the sub-agent' for receipts and recaps (no ";":
    the recap line uses it as its own separator)."""
    if not cov:
        return ""
    if cov.get("unknown"):
        return "covers: not known (not pytest / unittest)"
    files = cov.get("files") or []
    n = cov.get("n_files", len(files))
    more = "+" if cov.get("partial") else ""
    if cov.get("dirs") and n > limit:
        what = ", ".join(cov["dirs"][:limit]) + f" ({n}{more} test files)"
    elif files:
        what = ", ".join(files[:limit]) + (f" +{n - limit}{more} more" if n > limit else "")
    else:
        what = "no test file found"
    out = f"covers: {what}"
    if cov.get("filtered"):
        out += f" (only {', '.join(cov['filtered'][:2])})"
    if cov.get("basis_changed"):
        out += f" | basis changed: {', '.join(cov['edited'][:limit])} edited by the sub-agent"
    if cov.get("added_to"):
        out += f" | tests added by the sub-agent in {', '.join(cov['added_to'][:limit])}"
    if cov.get("own_tests_only"):
        out += " | only tests the sub-agent wrote"
    elif cov.get("written"):
        out += f" | written by the sub-agent: {', '.join(cov['written'][:limit])}"
    return out
