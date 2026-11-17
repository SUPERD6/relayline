"""How much the project manager may do without asking (K4): L0 only proposes, L1 dispatches read-only work and
stops before a sub-agent edits files, L2 also dispatches write work and merges a small, checked, reviewed
worktree branch into a working branch the project allowed.

Where the level comes from (later wins): [autonomy] level in tiers.toml (or `ccx config set autonomy.level`) ->
the hub's per-project setting (`ccx autonomy set L2 --project X`, <hub>/ccx/autonomy.json) -> the project's own
`.ccx/autonomy.toml`, which may only lower it (a sub-agent can write into the project, so it can't raise it) ->
`ccx run --autonomy L?` for one run. Merging may only be switched on per project, in the hub.

Whatever the level, these always go to the person (ALWAYS_ASK): sending outside this machine, merging into a
protected branch (main and the like), spending over a cap, research approval. ccx already refuses or stops on the
caps and approval rules (daily_usd, --budget, `ccx way --yes`, `ccx run --project` + approval_rules); this module
does not repeat those, it only decides dispatching and the L2 merge."""
from __future__ import annotations

import fnmatch
import json
import os
import subprocess
import tempfile
import time
import tomllib
from pathlib import Path

from . import ledger, projects
from .config import Paths, load_config, paths

LEVELS = ("L0", "L1", "L2")
DEFAULTS = {"level": "L1", "max_lines": 80, "max_files": 5, "protected": ["main", "master", "trunk", "release/*"]}
MEANS = {
    "L0": "propose only: say what would be sent where, how, and what it would cost; dispatch nothing",
    "L1": "dispatch read-only work by itself; stop before a sub-agent may edit files and ask the person",
    "L2": "dispatch read and write work; merge a small worktree branch whose check passed and whose review found "
          "nothing into the working branch, only where the project allowed merging and never into a protected branch",
}
ALWAYS_ASK = (
    "sending anything outside this machine: email, chat, issues, PR comments to others, publishing",
    "merging into the main branch (or any protected branch)",
    "spending over a cap: a provider's daily_usd, --budget, `ccx way --risk critical`, `ccx discuss`",
    "research approval: a project's approval_rules",
)


def settings(cfg: dict) -> dict:
    return {**DEFAULTS, **(cfg.get("autonomy") or {})}


def _norm(level) -> str:
    v = str(level or "").strip().upper()
    if v in ("0", "1", "2"):
        v = "L" + v
    if v not in LEVELS:
        raise ValueError(f"autonomy level must be one of {', '.join(LEVELS)}, not {level!r}")
    return v


def store(p: Paths) -> Path:
    return p.state / "autonomy.json"


def _hub(p: Paths) -> dict:
    try:
        return json.loads(store(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _entry(p: Paths, project) -> dict | None:
    if isinstance(project, dict) or not project:
        return project or None
    cat = projects.load(p)
    return projects.find(cat, project) if cat else None


def _project_file(path: str | None) -> dict:
    if not path:
        return {}
    f = Path(path) / ".ccx" / "autonomy.toml"
    try:
        return tomllib.loads(f.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def level_for(project=None, p: Paths | None = None, cfg: dict | None = None, flag: str | None = None) -> dict:
    """The level that applies to `project` (a catalog name or entry; None = no project) and where it came from.
    -> {level, source, auto_merge, project, means}. Also what `ccx ui` shows."""
    p = p or paths()
    cfg = cfg if cfg is not None else load_config(p)
    st = settings(cfg)
    level, source = _norm(st["level"]), "config"
    e = _entry(p, project)
    name = e["name"] if e else (project if isinstance(project, str) else None)
    own = (_hub(p).get("projects") or {}).get(name or "") or {}
    if own.get("level"):
        level, source = _norm(own["level"]), "hub project"
    pf = _project_file(e.get("path") if e else None)
    if pf.get("level"):
        try:
            lower = _norm(pf["level"])
        except ValueError:
            lower = "L0"                       # unreadable means the strictest, not the default
        if LEVELS.index(lower) < LEVELS.index(level):
            level, source = lower, "project .ccx/autonomy.toml"
    if flag:
        level, source = _norm(flag), "--autonomy"
    return {"level": level, "source": source, "auto_merge": bool(own.get("auto_merge")) and level == "L2",
            "project": name, "means": MEANS[level]}


def set_level(p: Paths, level: str | None, project: str | None = None, auto_merge: bool | None = None) -> dict:
    """`ccx autonomy set`: the default (in the hub's settings) or one project's level and merge permission."""
    if not project:
        if auto_merge is not None:
            raise ValueError("--auto-merge is per project: add --project NAME")
        from .config import set_setting
        return set_setting(p, "autonomy.level", _norm(level))
    e = _entry(p, project)
    if not e:
        raise ValueError(f"no single project named {project!r} in the catalog; `ccx projects` lists them")
    data = _hub(p)
    row = data.setdefault("projects", {}).setdefault(e["name"], {})
    if level:
        row["level"] = _norm(level)
    if auto_merge is not None:
        row["auto_merge"] = auto_merge
    store(p).parent.mkdir(parents=True, exist_ok=True)
    store(p).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"project": e["name"], **row}


def overview(p: Paths, cfg: dict, project=None) -> dict:
    return {**level_for(project, p, cfg), "default": _norm(settings(cfg)["level"]),
            "projects": (_hub(p).get("projects") or {}), "always_ask": list(ALWAYS_ASK),
            "levels": MEANS}


def gate(info: dict, mode: str, approved: bool, plan: dict) -> dict | None:
    """Before a manager's dispatch: None = go on; else what to tell the lead instead of running."""
    lv = info["level"]
    if approved or lv == "L2" or (lv == "L1" and mode == "read"):
        return None
    why = ("L0: the manager only proposes" if lv == "L0"
           else "L1: this run may edit files, and edits wait for the person")
    return {"delegated": False, "autonomy": {k: info[k] for k in ("level", "source", "project")}, "why": why,
            "plan": plan,
            "next": "tell the person in a line what would run and its estimate; if they say yes, run the same "
                    "command again with --approved"}


# ---------------------------------------------------------------- the L2 merge
def _git(cwd, *args, env=None) -> tuple[int, str]:
    r = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, encoding="utf-8",
                       errors="replace", stdin=subprocess.DEVNULL, env=env)
    return r.returncode, (r.stdout if r.returncode == 0 else r.stdout + r.stderr).strip()


def _repo_of(wt: Path) -> Path | None:
    from .workspace import canonical
    rc, common = _git(wt, "rev-parse", "--path-format=absolute", "--git-common-dir")
    return canonical(common).parent if rc == 0 and common else None


def protected(repo: Path, branch: str, patterns: list[str]) -> bool:
    rc, head = _git(repo, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    names = list(patterns) + ([head.split("/", 1)[1]] if rc == 0 and "/" in head else [])
    return any(fnmatch.fnmatchcase(branch, x) for x in names)


def _numstat(wt: Path, base: str) -> tuple[int, list[str]]:
    """Changed lines and files of the worktree (committed, edited and new files) against base, without touching
    its index: a throwaway index file."""
    with tempfile.TemporaryDirectory() as d:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(d) / "index")}
        _git(wt, "read-tree", "HEAD", env=env)
        _git(wt, "add", "-A", env=env)
        rc, out = _git(wt, "diff", "--cached", "--numstat", base, env=env)
    if rc != 0:
        return 0, []
    lines, files = 0, []
    for row in out.splitlines():
        a, b, f = (row.split("\t", 2) + ["", ""])[:3]
        lines += (int(a) if a.isdigit() else 1) + (int(b) if b.isdigit() else 0)
        files.append(f)
    return lines, files


def merge(p: Paths, run_id: str, info: dict, cfg: dict | None = None, rules: list | None = None,
          apply: bool = False) -> dict:
    """L2: merge run `run_id`'s worktree branch (ccx/<run_id>; ccx/<first run_id> for a resume, #374) into the
    branch the project is on, if every condition holds. Dry run unless apply. Any condition that fails is listed and nothing is merged."""
    from .workspace import worktree_repo
    cfg = cfg if cfg is not None else load_config(p)
    st = settings(cfg)
    rec = ledger.load_run(p, run_id)
    wt = Path(rec.get("cwd") or "")
    branch = f"ccx/{run_id}"
    no = []
    if info["level"] != "L2":
        no.append(f"autonomy is {info['level']}, merging needs L2")
    if not info.get("auto_merge"):
        no.append("this project does not allow merging: `ccx autonomy set L2 --project NAME --auto-merge on`")
    if rules:
        no.append("the project has approval rules: the person merges")
    if not rec.get("ok") or (rec.get("kind") not in (None, "ok")):
        no.append(f"the run did not end ok ({rec.get('kind') or rec.get('state')})")
    c = rec.get("check") or {}
    if not c:
        no.append("no --check ran")
    elif not c.get("passed"):
        no.append("the check failed")
    elif c.get("weak"):
        no.append(f"the check is weak here ({c['weak']})")
    rv = (rec.get("review") or {}).get("verdict")
    if rv == "pass" and (rec.get("review") or {}).get("downgraded"):
        no.append("the review's [must] items were only downgraded for lack of a repro (must_needs_repro)")
    elif rv != "pass":
        no.append(f"the independent review did not pass ({rv or 'none ran'}): use --review on")
    if rec.get("risk") in ("visible", "critical"):
        no.append(f"risk is {rec['risk']}")
    out = {"run_id": run_id, "branch": branch, "merged": False}
    repo = _repo_of(wt) if worktree_repo(wt) is not None and wt.exists() else None
    if not repo:
        no.append("not a --worktree run (nothing separate to merge)")
        return {**out, "can_merge": False, "why_not": no}
    rc, target = _git(repo, "symbolic-ref", "--short", "HEAD")
    target = target if rc == 0 else ""
    found, why = run_branch(p, rec, wt, run_id)   # #374: a resumed run's branch is the first run's
    if found:
        branch = out["branch"] = found
    else:
        no.append(why)
    out.update(repo=str(repo), into=target)
    if not target:
        no.append("the project is not on a branch")
    elif protected(repo, target, st["protected"]):
        no.append(f"{target} is protected: merging into it always goes to the person")
    _, dirty = _git(repo, "status", "--porcelain", "--untracked-files=no")
    if dirty:
        no.append("the project has uncommitted changes")
    start = upstream_start(p, rec)
    if start and start.get("unknown"):   # #349: never fall back to the merge-base, which counts the upstream too
        rc, base = 1, ""
        no.append(unknown_start(start))
    elif start:    # #349: a --base upstream run is measured from where its worktree started, not the merge-base
        rc, base = 0, start["sha"]
        why = behind_start(repo, target or "HEAD", start)
        if why:
            no.append(why)
    else:
        rc, base = _git(repo, "merge-base", target or "HEAD", branch)
    lines, files = _numstat(wt, base) if rc == 0 else (0, [])
    out.update(lines=lines, files=files)
    if not files and found and not (start and start.get("unknown")):   # an unknown branch says why already
        no.append("nothing changed")
    if lines > int(st["max_lines"]) or len(files) > int(st["max_files"]):
        no.append(f"too big for a merge without the person: {lines} lines in {len(files)} files "
                  f"(limit {st['max_lines']} lines, {st['max_files']} files)")
    out["can_merge"] = not no
    if no:
        return {**out, "why_not": no}
    if not apply:
        return {**out, "next": f"ccx autonomy merge {run_id} --apply"}
    err = commit_worktree(wt, f"ccx run {run_id}: {rec.get('label') or 'sub-agent changes'}")
    if err:
        return {**out, "can_merge": False, "why_not": [f"could not commit the worktree: {err}"]}
    m = merge_branch(repo, branch, f"Merge {branch} (ccx autonomy L2)")
    if not m["merged"]:
        return {**out, "can_merge": False, "why_not": [f"merge failed, aborted: {m['error']}"]}
    prev, head = m["prev"], m["head"]
    row = {"type": "auto_merge", "run_id": run_id, "repo": str(repo), "into": target, "from": prev, "head": head,
           "lines": lines, "files": len(files), "ts": time.time()}
    ledger.append_event(p, row)
    (p.runs / run_id / "merge.json").write_text(json.dumps(row), encoding="utf-8")
    return {**out, "merged": True, "head": head,
            "undo": f"git -C \"{repo}\" reset --keep {prev}",
            "note": "merged locally only: pushing and any PR into main still follow the project's rules"}


# ---------------------------------------------------------------- merge steps shared with `ccx q accept`
def upstream_start(p: Paths, rec: dict, hops: int = 20) -> dict | None:
    """Where a `--base upstream` run's worktree started (#341): {sha, ref} from its record, or from the run it
    resumed (a resume works in the same worktree but records no base of its own). None = a head-based run (its own
    record, or the first one up the resume chain, says head or nothing), whose merge-base with the project's branch
    is its start point as before. {unknown: why} = the chain breaks before saying (a record missing or unreadable, a
    loop, more than `hops` resumes, an upstream run without base_sha): the caller refuses instead of guessing head."""
    seen: set = set()
    while True:
        rid = rec.get("run_id")
        if rec.get("worktree_base") == "upstream":
            if rec.get("base_sha"):
                return {"sha": rec["base_sha"], "ref": rec.get("base_ref") or "the upstream"}
            return {"unknown": f"run {rid} started from the upstream but records no base_sha"}
        if rec.get("worktree_base") or not rec.get("resumed_from"):
            return None
        seen.add(rid)
        parent = rec["resumed_from"]
        if parent in seen:
            return {"unknown": f"the resume chain loops back to run {parent}"}
        if len(seen) > hops:
            return {"unknown": f"the resume chain is too long (over {hops} runs)"}
        try:
            rec = ledger.load_run(p, parent)
        except FileNotFoundError:
            return {"unknown": f"the record of run {parent}, which it resumed, is missing"}
        except (OSError, ValueError) as e:
            return {"unknown": f"the record of run {parent}, which it resumed, cannot be read ({type(e).__name__})"}
        if not isinstance(rec, dict):
            return {"unknown": f"the record of run {parent}, which it resumed, cannot be read (not an object)"}


def run_branch(p: Paths, rec: dict, wt: Path, run_id: str | None = None,
               hops: int = 20) -> tuple[str | None, str | None]:
    """#374: the branch run `rec` worked on -> (branch, None), or (None, why not). A resume works in the worktree of
    the run it resumed, so a resumed run's branch is ccx/<first run_id>, not ccx/<its own>. The worktree's checked-out
    branch is what its changes get committed to; it must be ccx/<id> of this run or of a run up its resume chain,
    else (detached, moved to another branch) nothing is merged. A chain that breaks before reaching that branch (a
    record missing or unreadable, a loop, more than `hops` resumes) is refused with the reason, never guessed."""
    rc, cur = _git(wt, "symbolic-ref", "--short", "-q", "HEAD")
    if rc != 0 or not cur:
        return None, "the worktree is not on a branch (detached HEAD): the person merges it"
    rid = run_id or rec.get("run_id")
    ids, broken = [rid], None
    while rec.get("resumed_from") and f"ccx/{ids[-1]}" != cur:
        parent = rec["resumed_from"]
        if parent in ids:
            broken = f"the resume chain loops back to run {parent}"
            break
        if len(ids) > hops:
            broken = f"the resume chain is too long (over {hops} runs)"
            break
        ids.append(parent)
        try:
            rec = ledger.load_run(p, parent)
        except FileNotFoundError:
            broken = f"the record of run {parent}, which it resumed, is missing"
            break
        except (OSError, ValueError) as e:
            broken = f"the record of run {parent}, which it resumed, cannot be read ({type(e).__name__})"
            break
        if not isinstance(rec, dict):
            broken = f"the record of run {parent}, which it resumed, cannot be read (not an object)"
            break
    if cur in {f"ccx/{i}" for i in ids if i}:
        return cur, None
    if broken:
        return None, f"cannot tell which branch this run worked on ({broken}): the person merges it"
    mine = ", ".join(f"ccx/{i}" for i in ids if i)
    return None, (f"the worktree is on {cur}, not a branch of this run or of the runs it resumed ({mine}): "
                  "the person merges it")


def unknown_start(start: dict) -> str:
    return f"cannot tell where this run started ({start['unknown']}): the person merges it"


def behind_start(repo: Path, target: str, start: dict) -> str | None:
    """#349: merging an upstream-based branch into a branch that lacks the commit it started from would bring the
    commits up to that one in too: a pull nobody asked for. -> why not, or None when `target` has the start point.
    N counts the commits of the run's start point (base_sha) that `target` lacks, not the upstream as it is now."""
    sha = start["sha"]
    rc, n = _git(repo, "rev-list", "--count", f"{target}..{sha}")
    if rc != 0:
        return f"cannot tell whether {target} has {sha[:12]} ({start['ref']}), where this run started"
    if not n.isdigit() or int(n) == 0:
        return None
    head = (f"{target} is missing {n} commit(s) that this run started from ({start['ref']} at {sha[:12]}): merging "
            "would bring them in too; ")
    rc, mine = _git(repo, "rev-list", "--count", f"{sha}..{target}")
    if rc == 0 and mine.isdigit() and int(mine) > 0:
        return head + (f"{target} and {start['ref']} have diverged ({mine} local commit(s) not in it): bring "
                       f"{start['ref']} into {target} yourself (`git pull --rebase` or `git pull`), then merge")
    return head + "pull first (`git pull`), then merge"


def _ident(repo: Path) -> list[str]:
    """`-c user.name/-c user.email` for a merge commit only where git has no identity (a fresh CI machine);
    otherwise the person's own identity signs it."""
    rc, email = _git(repo, "config", "user.email")
    return [] if rc == 0 and email else ["-c", "user.name=ccx", "-c", "user.email=ccx@localhost"]


def commit_worktree(wt: Path, message: str, ident: bool = False) -> str | None:
    """Commit whatever the worktree still has uncommitted (a piece's work is normally committed already).
    -> None, or why it could not."""
    _, wdirty = _git(wt, "status", "--porcelain")
    if not wdirty:
        return None
    _git(wt, "add", "-A")
    rc, msg = _git(wt, *(_ident(wt) if ident else []), "commit", "-qm", message)
    return None if rc == 0 else msg[-300:]


def merge_branch(repo: Path, branch: str, message: str, ident: bool = False) -> dict:
    """`git merge --no-ff branch` into what repo has checked out; on failure the merge is aborted, so the
    project is as it was. -> {merged, prev, head, conflicts: [files], error}"""
    _, prev = _git(repo, "rev-parse", "HEAD")
    rc, msg = _git(repo, *(_ident(repo) if ident else []), "merge", "--no-ff", "-m", message, branch)
    if rc != 0:
        _, unmerged = _git(repo, "diff", "--name-only", "--diff-filter=U")
        _git(repo, "merge", "--abort")
        return {"merged": False, "prev": prev, "head": prev, "error": msg[-300:],
                "conflicts": [x for x in unmerged.splitlines() if x.strip()]}
    _, head = _git(repo, "rev-parse", "HEAD")
    return {"merged": True, "prev": prev, "head": head, "error": None, "conflicts": []}


def rollback(repo: Path, prev: str) -> str | None:
    """Undo a merge just made (`git reset --keep prev`: never drops an uncommitted edit). -> None, or why not."""
    rc, msg = _git(repo, "reset", "--keep", prev)
    return None if rc == 0 else msg[-300:]
