"""The workspace around a write run: a worktree, the acceptance check ccx runs again, the snapshot taken
before the run and `ccx undo` (from delegate.py)."""
from __future__ import annotations

import difflib
import glob
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

from . import ledger
from .config import Paths, load_config, worktree_location
from .verdicts import _hard_verdict, verify

# `git worktree add` reads every worktree already registered; one another `worktree add` is creating at that moment
# has its .git/worktrees/<name>/ but no commondir yet, and git stops: "fatal: failed to read
# .git/worktrees/<name>/commondir" (CI, windows-latest, two writers of one `ccx q run`, 2026-10-30)
# matched on the path, not on the (translated) message; a path may hold spaces
_WT_RACE = re.compile(r"worktrees[\\/][^\\/\r\n]+[\\/](commondir|gitdir)")
_WT_LOCKS: dict[str, threading.Lock] = {}
_WT_LOCKS_GUARD = threading.Lock()
SIBLING_WORKTREE_DIR = ".ccx-worktrees"


def canonical(path: str | Path) -> Path:
    """Resolve aliases while keeping paths usable by Git (Windows can return an extended-length prefix)."""
    resolved = str(Path(path).resolve())
    if resolved.startswith("\\\\?\\UNC\\"):
        resolved = "\\\\" + resolved[8:]
    elif resolved.startswith("\\\\?\\"):
        resolved = resolved[4:]
    return Path(resolved)


def worktree_path(root: Path, run_id: str, location: str = "sibling") -> Path:
    """The configured layout for a new worktree, with one spelling for symlinks and Windows short names."""
    root = canonical(root)
    if location == "inside":
        return canonical(root / ".ccx" / "worktrees" / run_id)
    return canonical(root.parent / SIBLING_WORKTREE_DIR / root.name / run_id)


def worktree_repo(cwd: str | Path | None, *, root_only: bool = False) -> Path | None:
    """Repository owning a ccx worktree in either layout, regardless of today's location setting.
    Resolve aliases without requiring the worktree to exist: saved runs and the UI also need this after removal.
    root_only preserves check statistics' historic treatment of a worktree's subdirectories."""
    if not cwd:
        return None
    parts = canonical(str(cwd).replace("\\", "/")).parts
    compared = tuple(p.casefold() for p in parts) if os.name == "nt" else parts
    for i in range(len(parts) - 2, -1, -1):
        if root_only and i + 3 != len(parts):
            continue
        if compared[i] == SIBLING_WORKTREE_DIR and i + 2 < len(parts):
            return canonical(Path(*parts[:i]) / parts[i + 1])
        if compared[i:i + 2] == (".ccx", "worktrees") and i + 2 < len(parts):
            return canonical(Path(*parts[:i]))
    return None


def _worktree_lock(root: Path) -> threading.Lock:
    """One lock per repository: keyed by its common git folder, which every linked worktree of it shares."""
    rc, common = _git(root, "rev-parse", "--path-format=absolute", "--git-common-dir")
    key = os.path.normcase(str(canonical(common if rc == 0 and common else root)))
    with _WT_LOCKS_GUARD:
        return _WT_LOCKS.setdefault(key, threading.Lock())


def make_worktree(cwd: Path, run_id: str, tries: int = 3) -> Path:
    """A new worktree on branch ccx/<run_id> in the configured location (beside the repo by default).
    Threads of this process (the writers of one `ccx q run`
    or `ccx batch`) add theirs one at a time, so they never meet git's race above. Another process (a second ccx, a
    `ccx run --bg --worktree` beside it) still can: then this one tries again, up to `tries` times, on the branch git
    already made for it (deleting it first would read the worktrees again and meet the same race)."""
    cwd = canonical(cwd)
    top = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=cwd,
                         capture_output=True, text=True, encoding="utf-8", errors="replace")
    if top.returncode != 0:
        raise RuntimeError("--worktree needs a git repository")
    root = canonical(top.stdout.strip())
    location = worktree_location(load_config())
    wt = worktree_path(root, run_id, location)
    if location == "inside":
        if _git(root, "check-ignore", "-q", ".ccx/")[0] != 0:
            print("ccx: warning: worktree.location = inside, but git does not ignore .ccx/ in "
                  f"{root}. Add .ccx/ to {root / '.gitignore'} to keep worktrees out of git status; "
                  "ccx will not edit .gitignore.", file=sys.stderr)
    wt.parent.mkdir(parents=True, exist_ok=True)
    branch = f"ccx/{run_id}"
    with _worktree_lock(root):
        args = ["-b", branch, str(wt)]
        for n in range(tries):
            r = subprocess.run(["git", "worktree", "add", *args], cwd=root,
                               capture_output=True, text=True, encoding="utf-8", errors="replace")
            if r.returncode == 0:
                return wt
            if n + 1 == tries or not _WT_RACE.search(r.stderr or ""):
                break
            if _git(root, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}")[0] == 0:
                args = [str(wt), branch]      # git made this run's branch before the step that failed: use it
            try:
                wt.rmdir()                    # an empty folder git may have left (never one with files)
            except OSError:
                pass
            time.sleep(0.2 * (n + 1))         # the other process is mid-add: give it a moment to finish
    raise RuntimeError("git worktree add failed: " + r.stderr.strip())


# pytest's own exit codes for "this command did not test anything": 4 = usage error (e.g. a file that does not
# exist), 5 = no tests collected. Neither says the work is wrong; the check itself is broken.
PYTEST_BROKEN = {4: "pytest usage error (exit 4): a named file or option does not exist",
                 5: "pytest collected no tests (exit 5): the paths or -k filter match nothing"}
_TOKEN = re.compile(r"\"[^\"]*\"|'[^']*'|\S+")


def _expand_globs(cmd: str, cwd: Path) -> str:
    """For cmd.exe, which knows neither globs nor single quotes, in one pass over the tokens: expand unquoted * / ?
    tokens relative to cwd the way a POSIX shell would (a token with no match stays as it is), and turn a
    single-quoted token with no double quote inside into a double-quoted one: `-k 'a or b'` reached pytest as three
    words there (exit 4, r5e-h: 5/80 checks broken). Only those tokens change; everything else, `&&`, `|` and
    redirects included, is kept character for character (never re-joined with shlex / list2cmdline)."""
    def one(tok: str) -> str:
        if len(tok) >= 2 and tok[0] == tok[-1] == "'" and "'" not in tok[1:-1] and '"' not in tok:
            return '"' + tok[1:-1] + '"'
        if any(c in tok for c in "\"'") or not any(c in tok for c in "*?") or tok.startswith("-"):
            return tok
        hits = sorted(glob.glob(tok, root_dir=str(cwd)))
        return " ".join(h.replace("\\", "/") for h in hits) if hits else tok
    return "".join(t if t.isspace() else one(t) for t in _shell_words(cmd))


_BOOL_WORDS = ("or", "and", "not")
_CMD_SEP = ("&&", "||", "|", ";", "&")


def quote_k_expr(cmd: str) -> str:
    """A pytest `-k` / `-m` expression written without quotes (`-k undo or verify or verdict`) reached pytest as
    `-k undo` plus the paths `or`, `verify`, ... (exit 4: two units of the P1-10 audit judged "not ok" for that).
    Such an expression is put in double quotes, which both cmd.exe and a POSIX shell read as one argument; anything
    already quoted, and every other character of the command, is kept as it is."""
    if "pytest" not in cmd or not any(f" {w} " in f" {cmd} " for w in _BOOL_WORDS):
        return cmd
    words = _shell_words(cmd)
    idx = [i for i, t in enumerate(words) if not t.isspace()]
    out = list(words)
    k = 0
    while k < len(idx):
        if words[idx[k]] in ("-k", "-m") and k + 1 < len(idx):
            j = k + 1
            expr = []
            want_operand = True
            while j < len(idx):
                t = words[idx[j]]
                if t in _CMD_SEP or t.startswith(("-", '"', "'")) or any(c in t for c in "<>"):
                    break
                if want_operand:
                    expr.append(t)
                    want_operand = t == "not"            # `not x`: still an operand to come
                elif t in _BOOL_WORDS:
                    expr.append(t)
                    want_operand = True
                else:
                    break
                j += 1
            if len(expr) > 1 and not want_operand:
                first, last = idx[k + 1], idx[k + len(expr)]
                out[first:last + 1] = ['"' + " ".join(expr) + '"'] + [""] * (last - first)
            k = k + len(expr) + 1
            continue
        k += 1
    return "".join(out)


def _shell_words(cmd: str) -> list[str]:
    """cmd split into words and the whitespace runs between them (joined back, it is cmd again), tracking quote
    state the way the MSVC argv rules do: a `"` toggles it unless an odd number of backslashes comes right before
    it, and a `'` groups only outside double quotes. So a `'...'` inside a double-quoted argument
    (`"print('a b')"`, `--opt="a 'b c' d"`, one after a `\\"`) stays part of that word and is never rewritten on
    its own. An unclosed quote makes the rest of the line one word, which is then left as it is."""
    out: list[str] = []
    cur: list[str] = []
    dq = sq = False
    bs = 0
    for ch in cmd:
        if ch.isspace() and not dq and not sq:
            if cur:
                out.append("".join(cur))
                cur = []
            if out and out[-1].isspace():
                out[-1] += ch
            else:
                out.append(ch)
            bs = 0
            continue
        if ch == '"' and not sq and bs % 2 == 0:
            dq = not dq
        elif ch == "'" and not dq:
            sq = not sq
        bs = bs + 1 if ch == "\\" else 0
        cur.append(ch)
    if cur:
        out.append("".join(cur))
    return out


def _typo_of(want: str, have: str) -> bool:
    """`have` is `want` with a typo (same folder, file name a letter or two off), not a different file that merely
    looks alike, so swapping it into the check is safe."""
    (wd, _, wn), (hd, _, hn) = want.rpartition("/"), have.rpartition("/")
    wn, hn = wn.removeprefix("test_"), hn.removeprefix("test_")
    return wd == hd and abs(len(wn) - len(hn)) <= 2 and difflib.SequenceMatcher(None, wn, hn).ratio() >= 0.85


def missing_test_paths(cmd: str, cwd: Path) -> list[dict]:
    """`tests/....py` paths the check names that do not exist under cwd, each with close matches, so a check that
    could never pass (a guessed file name) stops before a sub-agent is paid to satisfy it."""
    known = None
    out = []
    for tok in _TOKEN.findall(cmd or ""):
        path = tok.strip("\"'").split("::")[0]
        if not re.match(r"^(\./)?tests[/\\].*\.py$", path) or any(c in path for c in "*?"):
            continue
        if (cwd / path).exists():
            continue
        if known is None:
            tests = cwd / "tests"
            known = sorted(q.relative_to(cwd).as_posix() for q in tests.rglob("*.py")) if tests.is_dir() else []
        want = path.replace("\\", "/")
        stem = want.removesuffix(".py") + "_"
        prefix = [] if "::" in tok else [k for k in known if k.startswith(stem) and "/" not in k[len(stem):]]
        out.append({"path": path, "close": difflib.get_close_matches(want, known, n=3, cutoff=0.5),
                    "sure": [k for k in known if _typo_of(want, k)], "prefix": prefix})
    return out


def run_check(cmd: str, cwd: Path, timeout: int = 900, tail_chars: int = 800) -> dict:
    """The lead's acceptance command, run by ccx after the sub-agent says it is done (not trusting its report).
    `broken` (status check_broken) = the command could not test anything, which is not a verdict on the work.
    `tail_chars`: how much of the end of its output is kept (a focused retry hands the sub-agent ~2000)."""
    t0 = time.time()
    ran = quote_k_expr(cmd)
    ran = _expand_globs(ran, cwd) if os.name == "nt" else ran
    try:
        r = subprocess.run(ran, shell=True, cwd=cwd, capture_output=True, text=True, timeout=timeout,
                           stdin=subprocess.DEVNULL, encoding="utf-8", errors="replace")
        code, tail = r.returncode, (r.stdout + r.stderr)[-tail_chars:]
    except subprocess.TimeoutExpired:
        code, tail = -1, f"timed out after {timeout}s"
    out = {"cmd": cmd, "exit": code, "passed": code == 0, "seconds": round(time.time() - t0, 1), "tail": tail}
    if ran != cmd:
        out["ran"] = ran
    if code in PYTEST_BROKEN and "pytest" in cmd:
        out.update(status="check_broken", broken=PYTEST_BROKEN[code] + "; fix the check (ccx resume <run_id> "
                   "--check \"...\"), not the code")
    if out["passed"]:
        out.update(_check_doubt(cmd, cwd))
    return out


def _check_doubt(cmd: str, cwd: Path) -> dict:
    """J7: when this command (here) passed work later judged wrong too often, say so with the result."""
    try:
        from .config import hub_dir
        p = Paths(hub_dir())
        g = ledger.check_trust(ledger.rows(p), p).get(ledger.check_key(cmd, str(cwd))[0])
    except Exception:  # noqa: BLE001 — a note, never a reason for the run to fail
        return {}
    if not g or not g["weak"]:
        return {}
    return {"weak": f"{g['wrong']}/{g['judged']} passed but judged wrong", "note": ledger.WEAK_CHECK_NOTE}


def _git(cwd: Path, *args: str) -> tuple[int, str]:
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       stdin=subprocess.DEVNULL)
    return r.returncode, r.stdout.strip()


def undo_snapshot(cwd: Path) -> dict | None:
    """Before a write run: remember the exact working tree (incl. uncommitted edits) without touching it."""
    rc, top = _git(cwd, "rev-parse", "--show-toplevel")
    if rc != 0:
        return None
    _, stash = _git(cwd, "stash", "create")          # a commit object of the dirty tree; "" if clean
    _, head = _git(cwd, "rev-parse", "HEAD")
    base = stash or head
    if not base:
        return None
    _, untracked = _git(Path(top), "ls-files", "--others", "--exclude-standard")
    return {"repo": top, "base": base, "head": head, "untracked": untracked.splitlines()}


def tree_state(cwd: Path) -> dict | None:
    """HEAD, the content of the working tree (tracked files, incl. uncommitted edits) and the untracked files."""
    snap = undo_snapshot(cwd)
    if not snap:
        return None
    rc, tree = _git(cwd, "rev-parse", snap["base"] + "^{tree}")
    return {"head": snap.get("head"), "tree": tree if rc == 0 else None, "untracked": sorted(snap["untracked"])}


def mark_run_end(run_dir: Path, cwd: Path) -> None:
    """Add to a write run's undo.json how it left the tree, so a resume can tell whether anything changed since."""
    f = run_dir / "undo.json"
    try:
        if f.exists():
            snap = json.loads(f.read_text(encoding="utf-8"))
            snap["after"] = tree_state(cwd)
            f.write_text(json.dumps(snap), encoding="utf-8")
    except (OSError, ValueError, TypeError):    # best effort: without it a resume just checks HEAD
        pass


def full_tree(cwd: Path) -> str | None:
    """A git tree object of the working tree as it is now, new untracked files included (.gitignore'd files and
    .ccx/ left out), built in a throwaway index: the real index, the files and HEAD stay as they are. Used by
    [review] fix_rereview = "focus" (end.json); undo.json is never touched by it."""
    import shutil
    import tempfile
    rc, top = _git(cwd, "rev-parse", "--show-toplevel")
    if rc != 0 or not top:
        return None
    rc, real = _git(Path(top), "rev-parse", "--git-path", "index")
    d = tempfile.mkdtemp(prefix="ccx-tree-")
    try:
        idx = Path(d) / "index"
        if rc == 0 and real:
            src = Path(real) if Path(real).is_absolute() else Path(top) / real
            if src.is_file():
                shutil.copyfile(src, idx)          # its stat cache: only changed files are hashed again
        env = {**os.environ, "GIT_INDEX_FILE": str(idx)}

        def g(*args: str) -> tuple[int, str]:
            r = subprocess.run(["git", *args], cwd=top, capture_output=True, text=True, encoding="utf-8",
                               errors="replace", stdin=subprocess.DEVNULL, env=env)
            return r.returncode, r.stdout.strip()
        if g("add", "-A", "--", ".", ":(exclude).ccx", ":(exclude,glob)**/.ccx/**")[0] != 0:
            return None
        rc, tree = g("write-tree")
        return tree if rc == 0 and tree else None
    except OSError:
        return None
    finally:
        shutil.rmtree(d, ignore_errors=True)


def write_end_tree(run_dir: Path, cwd: Path) -> None:
    """end.json: the tree as this run left it (full_tree), so the review of the fix round that follows can show the
    fix alone. A file of its own: undo.json and `ccx undo` are unchanged."""
    try:
        tree = full_tree(cwd)
        if tree:
            (run_dir / "end.json").write_text(json.dumps({"tree": tree, "ts": time.time()}), encoding="utf-8")
    except (OSError, ValueError):                 # best effort: without it the fix round gets the full review
        pass


def fix_delta(p: Paths, prev_id: str | None, cwd: Path) -> str | None:
    """`git diff` from the tree run prev_id left (its end.json) to the working tree now, new files included; None
    when there is no end.json or git can't answer."""
    if not prev_id:
        return None
    try:
        end = json.loads((p.runs / prev_id / "end.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    now = full_tree(cwd)
    if not now or not end.get("tree"):
        return None
    rc, top = _git(cwd, "rev-parse", "--show-toplevel")
    try:
        r = subprocess.run(["git", "-c", "core.quotepath=off", "diff", end["tree"], now],
                           cwd=top if rc == 0 and top else cwd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", stdin=subprocess.DEVNULL)
    except OSError:
        return None
    return r.stdout if r.returncode == 0 else None


def chain_snapshot(p: Paths, record: dict, cwd: Path, prev_id: str | None) -> dict | None:
    """A resume / review fix round's undo snapshot: the chain's first one when the tree is still exactly as the
    previous link left it (same HEAD, same files; HEAD only when that link never finished), so its review and
    `ccx undo` cover the whole chain. When the lead committed or edited in between, a fresh snapshot instead:
    undoing then must not revert the lead's own work."""
    inherited = run_snapshot(p, record)
    if not inherited:
        return undo_snapshot(cwd)
    after = inherited.get("after")
    if after:
        same = after == tree_state(cwd)
    else:
        now = undo_snapshot(cwd)
        same = bool(inherited.get("head")) and bool(now) and inherited.get("head") == now.get("head")
    if not same:
        snap = undo_snapshot(cwd)
        if snap:
            snap["chain_broken"] = (f"the tree changed after run {prev_id} ended (a commit or an edit): this run's "
                                    "review and undo count from its own start")
        return snap
    snap = {k: v for k, v in inherited.items() if k != "after"}
    snap["chain_from"] = inherited.get("chain_from") or prev_id
    return snap


def run_snapshot(p: Paths, record: dict, depth: int = 5) -> dict | None:
    """The undo snapshot a run's changes count from: its own, or (a resume, a review fix round) the one of the
    run it continued, followed back a few links."""
    rec = record
    for _ in range(depth):
        f = p.runs / str(rec.get("run_id")) / "undo.json"
        try:
            if f.exists():
                return json.loads(f.read_text(encoding="utf-8"))
            if not rec.get("resumed_from"):
                return None
            rec = ledger.read_record(p.runs / rec["resumed_from"] / "run.json")
        except (OSError, ValueError):
            return None
    return None


def diffstat(snap: dict | None) -> str | None:
    """One line of what a write run changed since its snapshot: `git diff --shortstat` plus files that are new
    since then (untracked). None when there is no snapshot or git can't answer: the lead then just has no line."""
    if not snap:
        return None
    try:
        repo = Path(snap["repo"])
        rc, stat = _git(repo, "diff", "--shortstat", snap["base"], "--", ".", ":(exclude).ccx")
        if rc != 0:
            return None
        rc, others = _git(repo, "ls-files", "--others", "--exclude-standard")
    except (OSError, KeyError, TypeError, ValueError):       # git missing, odd snapshot
        return None
    before = set(snap.get("untracked") or [])
    new = [n for n in (others.splitlines() if rc == 0 else []) if n and n not in before and not n.startswith(".ccx/")]
    parts = [stat.strip()] if stat.strip() else []
    if new:
        parts.append(f"{len(new)} new untracked file{'s' if len(new) > 1 else ''}")
    return "; ".join(parts) or "no changes"


def _unquote(name: str) -> str:
    """A path as `git ls-files` prints it (C-quoted when core.quotepath is on and the name is not ASCII) -> the real
    name. Unquoted names come back as they are."""
    if len(name) >= 2 and name[0] == name[-1] == '"':
        import codecs
        return codecs.escape_decode(name[1:-1].encode("ascii", "backslashreplace"))[0].decode("utf-8")
    return name


def unchanged(snap: dict | None, since: float | None = None) -> bool | None:
    """Did a write run leave the tree exactly as its undo snapshot found it? True only when HEAD is the same (a
    commit of the builder's own is a change), no tracked file differs from the snapshot's base, no untracked file is
    new or gone, and no untracked file that was already there was written after `since` (the run's start; git keeps
    no content of those). Not seen: files .gitignore'd or outside the repo (a run that writes only those looks
    unchanged; the hint says so). None when there is no snapshot or git can't answer: then nothing is claimed."""
    if not snap or not snap.get("base"):
        return None
    try:
        repo = Path(snap["repo"])
        rc, head = _git(repo, "rev-parse", "HEAD")
        if rc != 0:
            return None
        if snap.get("head") and head != snap["head"]:
            return False
        r = subprocess.run(["git", "diff", "--quiet", snap["base"], "--", ".", ":(exclude).ccx"], cwd=repo,
                           capture_output=True, stdin=subprocess.DEVNULL)
        if r.returncode == 1:
            return False
        if r.returncode != 0:
            return None
        rc, others = _git(repo, "ls-files", "--others", "--exclude-standard")
        if rc != 0:
            return None
        before = set(snap.get("untracked") or [])
        now = [n for n in others.splitlines() if n and not n.startswith(".ccx/")]
        if any(n not in before for n in now):
            return False                        # a new untracked file
        if {n for n in before if n and not n.startswith(".ccx/")} - set(now):
            return False                        # an untracked file that was there is gone (deleted, moved, added)
        for n in now:
            # git C-quotes non-ASCII names in this list (the snapshot's too, so the comparisons above agree);
            # the file on disk has the real name
            if since is not None and (repo / _unquote(n)).stat().st_mtime > since:
                return False
    except (OSError, KeyError, TypeError, ValueError):
        return None
    return True


def undo(p: Paths, run_id: str, apply: bool = False, wrong: bool = False, piece: str | None = None) -> dict:
    """Put back the files a write run changed. Dry run unless apply. New files are moved aside, not deleted.
    Undoing is not a verdict by itself (people undo to try again, or to split the work); `wrong` says it was.
    piece: a merged run (`ccx batch --merge`): only the files that piece declared; never a verdict (a verdict is
    per run), and the run is not marked undone (its other pieces stand)."""
    declared = None
    if piece is not None:
        if wrong:
            raise ValueError("--wrong records a verdict on the whole run; with --piece only files are put back")
        from .merge import piece_files
        declared = piece_files(ledger.load_run(p, run_id), piece)
    f = p.runs / run_id / "undo.json"
    if not f.exists():
        raise FileNotFoundError(f"run {run_id} has no undo snapshot (read-only run, worktree run, or not a git repo)")
    snap = json.loads(f.read_text(encoding="utf-8"))
    repo, base = Path(snap["repo"]), snap["base"]
    rc_d, changed = _git(repo, "diff", "--name-only", base)
    rc_u, untracked = _git(repo, "ls-files", "--others", "--exclude-standard")
    git_failed = rc_d != 0 or rc_u != 0
    new_files = sorted(set(untracked.splitlines()) - set(snap["untracked"]))
    restore = [x for x in changed.splitlines() if x]
    if declared is not None:
        from .merge import restrict
        restore, new_files = restrict(restore, declared), restrict(new_files, declared)
    out = {"run_id": run_id, "restore": restore, "move_aside": new_files, "applied": False,
           "warning": "also reverts any edits you made to these files after the run"}
    if piece is not None:
        out["piece"] = piece
    if snap.get("chain_from"):
        out["chain_from"] = snap["chain_from"]
        out["warning"] = (f"this run went on from run {snap['chain_from']}: undo puts back what the whole chain "
                          "changed since that run started (the earlier runs' work too), and any edits you made to "
                          "these files after the run")
        if wrong:
            out["wrong_scope"] = f"only {run_id} is recorded as wrong; `ccx verify` the earlier runs yourself"
    if git_failed:
        # git could not list them (base commit gone after a gc or rebase, repo moved): say so, never "nothing to undo"
        out["git_error"] = (f"git could not list the run's files (diff exit {rc_d}, ls-files exit {rc_u}; base "
                            f"{base[:12]}): the lists above may be incomplete")
    elif not restore and not new_files:
        # nothing to put back: one line instead of a warning about files that are not there (walkthrough 2026-10-29)
        del out["warning"]
        out["nothing_to_undo"] = "this run left no changed or new files: there is nothing to undo"
    if apply:
        if restore:
            rc, msg = _git(repo, "checkout", base, "--", *restore)
            if rc != 0:
                raise RuntimeError("git checkout failed: " + msg)
        trash = repo / ".ccx" / "undo" / run_id
        for rel in new_files:
            src = repo / rel
            dst = trash / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            os.replace(src, dst)
        out.update(applied=True, moved_to=str(trash) if new_files else None)
        if piece is not None:            # one piece of a merged run: the run itself stands, no verdict
            ledger.append_event(p, {"type": "undo", "run_id": run_id, "piece": piece, "reason": "undone",
                                    "wrong": False, "ts": time.time()})
            return out
        (p.runs / run_id / "undone.json").write_text(json.dumps({"ts": time.time(), "wrong": wrong}),
                                                     encoding="utf-8")
        ledger.append_event(p, {"type": "undo", "run_id": run_id, "reason": "undone", "wrong": wrong,
                                "ts": time.time()})
        if wrong and not _hard_verdict(ledger.load_run(p, run_id)):
            verify(p, run_id, False, note="undone with ccx undo --wrong", reason="wrong")
            out["verdict"] = "recorded as wrong (undo --wrong)"
        elif not wrong:
            out["verdict"] = "none: waits for yours (`ccx verify` or `ccx undo --wrong`)"
    return out
