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
    rc, common = _git(wt, "rev-parse", "--path-format=absolute", "--git-common-dir")
    return Path(common).resolve().parent if rc == 0 and common else None


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
    """L2: merge run `run_id`'s worktree branch (ccx/<run_id>) into the branch the project is on, if every
    condition holds. Dry run unless apply. Any condition that fails is listed and nothing is merged."""
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
    out.update(repo=str(repo), into=target)
    if not target:
        no.append("the project is not on a branch")
    elif protected(repo, target, st["protected"]):
        no.append(f"{target} is protected: merging into it always goes to the person")
    _, dirty = _git(repo, "status", "--porcelain", "--untracked-files=no")
    if dirty:
        no.append("the project has uncommitted changes")
    rc, base = _git(repo, "merge-base", target or "HEAD", branch)
    lines, files = _numstat(wt, base) if rc == 0 else (0, [])
    out.update(lines=lines, files=files)
    if not files:
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
