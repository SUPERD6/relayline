"""Serial, budgeted execution of strength manifests using seven_func's isolated ccx mechanism."""
from __future__ import annotations

import dataclasses
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tempfile
import time
import uuid

from common import ROOT, append_jsonl, lead_env, make_repo, run_tree, score  # run_tree: issues #329, #332
from l5_memory import CASES, DISTRACTORS
from shared_context_ab import TASKS, lead_transcript
from seven_func import ccx_run, check_env, last_json
import preflight as PF
from ccx import ledger
from ccx.config import Paths

CCX_RUN_TIMEOUT_S = 300       # one `ccx run` per unit; past this the unit is TimeoutExpired, cost Unknown


def unit_cost(hub: Path) -> float | None:
    rows = [r for r in ledger.rows(Paths(hub)) if not r.get("type")]
    amounts = [r.get("ae_usd") for r in rows]
    if not amounts or any(isinstance(x, bool) or not isinstance(x, (int, float)) or
                          not math.isfinite(x) or x < 0 for x in amounts):
        return None
    return round(sum(amounts), 8)


CLAUDE_NO_WEB = {"permissions": {"deny": ["WebFetch", "WebSearch"]}}   # Claude units: no web tools (#345)
# A --tasks run's Codex units: [subagent] codex_lean_tools makes ccx pass `-c web_search="disabled"` (plus no image
# generation / goals) on a write run; Codex web search is not limited by the sandbox's network setting (#345).
CODEX_NO_WEB_CONFIG = "[subagent]\ncodex_lean_tools = true\n"
SYNTHETIC_LEAD_FOLDER = "ccx-strength-synthetic"


# ------------------------------------------------------------------ isolation (#454)
# What a unit's agents must not open, on top of preflight.forbidden's own list (the person's homes, hub, config,
# this checkout and its git worktrees): the task generators and hidden tests (scripts/eval, e.g. round2_a/), the
# frozen task files (docs/research/data, e.g. round2-tasks/), the --tasks file itself and every --hide path. Claude
# units get Read/Edit deny rules on them (Claude Code applies Read deny rules to Grep and Glob, best effort; Edit
# rules to every file-editing tool); every unit's tool calls are audited after the run (path_audit).
EVAL_ABS = Path(__file__).absolute().parent      # the spelling the script was started by (a junction kept)
DATA_DIRS = ("scripts/eval", "docs/research/data")
# Path-independent patterns: a relative read (`cd ../.. && cat scripts/eval/round2_a/x.py`), another folder name or an
# 8.3 short name (ROUND2~1) still names the task folder or module. Matched case-insensitively on preflight.canon text.
CONTENT_PATTERNS = (r"round2_a", r"round2_bc", r"round2-tasks", r"(?<![a-z0-9_])round2~\d",
                    r"(?<![a-z0-9_])(?:l5_memory|shared_context_ab)(?![a-z0-9_])")
# A recursive listing or search. Climbing (`..`) is judged by where it lands: the sub-agent works in the unit's repo or
# in a ccx worktree under <unit>/.ccx-worktrees/repo/<run id>, so `cd ../..` there is still inside the unit (#455).
_RECURSIVE = re.compile(r"(?<![\w.-])(?:rg|ag|tree|find|grep\s+(?:-\w*[rR]\w*|--recursive)|findstr\s+/s|"
                        r"dir\s+/s|ls\s+-\w*R\w*|(?:get-childitem|gci|ls|dir)\b[^|;&]*\s-r(?:ecurse)?\b)(?![\w-])",
                        re.I)
_END = r"(?=$|[\s\"'`;)|,&<>])"
_TOKEN_END = r"/?" + _END
# In order: a `cd`-like command with no target (bash: home), one with its target (cmd's `/d` and PowerShell's
# -switches skipped), or a relative path starting with `..` or `./..`. A cd counts only where a command starts: the
# beginning, after ; & | ( { ` or a newline, or right after the quote that opens a `-Command '...'`/`-c "..."`
# string; `echo cd` or `grep -w sl` mention the word without running it.
_CD = r"(?:^|(?<=[;&|(\n{`'\"]))\s*(?:cd|chdir|pushd|push-location|set-location|sl)(?![\w-])"
_NAV = re.compile(_CD + r"(?P<bare>(?=\s*(?:$|[;&|\n])))"
                  r"|" + _CD + r"\s+(?:(?:-\w+|/d|d:)\s+)*(?P<q>[\"']?)(?P<cd>[^\s\"';|&)]+)"   # canon: /d -> d:
                  r"|" + PF._B + r"(?P<up>(?:\./)?\.\.(?:/[^\s\"'`;)|,&<>]*)?)" + _END, re.I)
_ABS_DOTS = re.compile(PF._B + r"(?P<p>(?:[a-z]:)?/[^\s\"'`;)|,&<>]*/\.\.(?:/[^\s\"'`;)|,&<>]*)?)", re.I)
# Fields that say where a tool call goes (a Bash/Codex command, a path, a Grep/Glob pattern); never a written body
NAV_KEYS = {"command", "cmd", "file_path", "path", "paths", "pattern", "glob", "notebook_path", "cwd", "workdir",
            "arguments"}
# The run's own files next to the units in --out (#467): the frozen plan, every finished row, the final report
RUN_FILES = ("manifest.json", "results.jsonl", "report.json")
# A shared logged-in home's session records (#470): every unit's prompts and tool results, so an on or mem arm's answer.
# Codex (codex-cli 0.164.0, a home's entries): rollouts, history, memories, and the state/log/goal databases
# (CODEX_SQLITE_HOME is the same home). Claude (Claude Code 2.1.316): projects/<cwd slug>/ sessions and tool results,
# file backups, todos, shell snapshots... Entries a CLI reads to start (auth.json, config.toml, .credentials.json) are
# not records. A unit's own parts are not hits: its Claude project folders and its own Codex rollouts.
CODEX_RECORDS = ("sessions", "archived_sessions", "history.jsonl", "memories", "memories_v2", "log",
                 "shell_snapshots")
CLAUDE_RECORDS = ("projects", "history.jsonl", "todos", "file-history", "sessions", "session-env", "shell-snapshots",
                  "plans", "backups", "debug")
_SQLITE = r"[\w.-]+\.sqlite(?:-wal|-shm|-journal)?"
SETTINGS_MAX_CHARS = 30000    # a Claude unit's --settings JSON; the Windows command line ends at 32767 (#467)
UNIT_NAME = re.compile(r"^unit-(\d+)$")       # execute() lays units out as <out>/unit-NNNN


def answer_files(kind: str, arm: str, agent: str) -> list[str]:
    """Where an arm's answer (the agreed decision, the convention) is written, as globs relative to the unit's folder
    (a leading <claude-home> is the logged-in Claude home), each followed by what writes it (#467). An arm that must
    not get the answer has none: the off arm gets no lead transcript (ccx never reads it with --context off) and
    nomem only the distractors. A unit reading another unit's folder is a path-audit hit whatever is in it."""
    runs = "hub/ccx/runs/*/* (ccx: the run's prompt, shared context and logs)"
    if kind == "context":
        if arm != "on":
            return []
        if agent == "claude":
            return [f"<claude-home>/projects/{SYNTHETIC_LEAD_FOLDER}/strength-*.jsonl (the lead transcript, read by "
                    "ccx; outside the unit, denied to every unit's agents, only this unit's own is not a hit)", runs]
        return ["claude-home/projects/lead/strength-synthetic-lead.jsonl (the lead transcript, read by ccx)", runs]
    if kind == "memory":
        if arm == "nomem":
            return []
        own = {"mem": "repo/.ccx/context.md (ccx ctx add)"}.get(arm, "hub/memory/* (ccx mem add)")
        return [own, runs]
    raise ValueError("unknown retest kind")


def sibling_globs(index: int, width: int = 4) -> list[str]:
    """Folder-name globs matching exactly unit-<0..index-1> (zero-padded to `width`): units run one after another, so
    these are the ones that exist while unit `index` runs. A few globs per digit (unit-00*, unit-010*, unit-0110), not
    one per unit: ccx passes Claude its settings on the command line. Past 10**width units: none (audit only)."""
    if index >= 10 ** width:
        return []
    out, i = [], 0
    while i < index:
        p = 0
        while p + 1 < width and i % 10 ** (p + 1) == 0 and i + 10 ** (p + 1) <= index:
            p += 1
        out.append("unit-" + str(i).zfill(width)[:width - p] + ("*" if p else ""))
        i += 10 ** p
    return out


def own_project_masks(u: PF.Unit, claude_home, home) -> list[tuple[re.Pattern, str]]:
    """The unit's own Claude project folders in `claude_home` (its repo; each ccx worktree, a name prefix), masked."""
    out = []
    for h in aliases(claude_home):
        proj = PF.canon((h / "projects").as_posix(), home) + "/"
        for spelled in {*(PF.slug(r) for r in aliases(u.repo)), *(PF.slug(w) + "-" for w in aliases(u.worktrees))}:
            tail = r"[^/\s\"'`;)|,&<>]*" if spelled.endswith("-") else ""
            out.append((re.compile(re.escape(proj + PF.canon(spelled, home)) + tail + r"(?=/|$|[\s\"'`;)|,&<>])"),
                        "<unit>"))
    return out


def record_patterns(homes, home) -> list[re.Pattern]:
    """Any part of a shared home's session records (#470), in each spelling of the home and as masked (<home>)."""
    names = "|".join(re.escape(n) for n in sorted({*CODEX_RECORDS, *CLAUDE_RECORDS}, key=len, reverse=True))
    roots = {re.escape(PF.canon(a.as_posix(), home)) for h in homes for a in aliases(h)} | {re.escape("<home>")}
    return [re.compile(r + r"/(?:" + names + "|" + _SQLITE + r")(?=/|$|[\s\"'`;)|,&<>])", re.I)
            for r in sorted(roots, key=len, reverse=True)] if homes else []


def own_sessions(hub: Path, codex_home) -> list[Path]:
    """The unit's own Codex rollouts in the shared `codex_home`: files under sessions/ (or archived_sessions/) whose
    name holds a session id from one of the unit's run records."""
    if codex_home is None:
        return []
    sids = set()
    for f in (Path(hub) / "ccx" / "runs").glob("*/run.json"):
        try:
            rec = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        sids |= {str(x) for x in [rec.get("session_id"), *(a.get("session_id") for a in rec.get("attempts") or []
                                                            if isinstance(a, dict))] if x}
    out = []
    for d in ("sessions", "archived_sessions"):
        root = Path(codex_home) / d
        if root.is_dir() and sids:
            out += [f for f in root.rglob("*.jsonl") if any(s in f.name for s in sids)]
    return sorted(out)


def record_deny(claude_home, dest: Path) -> list[str]:
    """A Claude unit's deny rules on the shared Claude home's records (#470), compact for the --settings command line:
    every session transcript (projects/*/*.jsonl, its own too: it never needs it), sub-agent folders and memory,
    every other record folder, and the project folders of the run's earlier units (their tool results; a few globs,
    as sibling_deny). Read rules only (writing there reveals nothing). Other runs' project folders are left to the
    audit."""
    rules = set()
    out = run_out(dest)
    m = UNIT_NAME.match(Path(dest).name)
    globs = sibling_globs(int(m.group(1)), len(m.group(1))) if m else []
    for h in aliases(claude_home):
        r = PF._rule_path(h)
        pats = ["projects/*/*.jsonl", "projects/*/memory/**", "projects/*/*/subagents/**",
                *(f"{n}/**" if "." not in n else n for n in CLAUDE_RECORDS if n != "projects")]
        if out is not None:
            # unit-0011 -> unit-0011-* (its repo, its worktrees); unit-001* already covers the rest of the name
            pats += [f"projects/{s}-{g if g.endswith('*') else g + '-*'}/**"
                     for s in {PF.slug(o) for o in aliases(out)} for g in globs]
        rules |= {f"Read({r}/{x})" for x in pats}     # Read only: editing them leaks nothing; keeps the line short
    return sorted(rules)


def run_out(dest: Path) -> Path | None:
    """The run's --out for a unit folder execute() made (<out>/unit-NNNN), else None (no sibling rules)."""
    return Path(dest).parent if UNIT_NAME.match(Path(dest).name) else None


def sibling_deny(dest: Path) -> list[str]:
    """Claude Read/Edit deny rules on the run's own files and the units before this one, for each spelling of --out."""
    out = run_out(dest)
    if out is None:
        return []
    digits = UNIT_NAME.match(Path(dest).name).group(1)
    globs = sibling_globs(int(digits), len(digits))
    rules = set()
    for o in aliases(out):
        r = PF._rule_path(o)
        for t in ("Read", "Edit"):
            rules |= {f"{t}({r}/{f})" for f in RUN_FILES} | {f"{t}({r}/{g}/**)" for g in globs}
    return sorted(rules)


def short_path(p) -> Path | None:
    """Windows: the 8.3 short spelling of an existing path (None elsewhere, or when it cannot be read). A volume with
    8.3 names turned off gives back the long name."""
    if os.name != "nt":
        return None
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(32768)
        n = ctypes.windll.kernel32.GetShortPathNameW(str(Path(p).resolve()), buf, len(buf))
        return Path(buf.value) if 0 < n < len(buf) else None
    except (OSError, AttributeError, ValueError):
        return None


def aliases(p) -> list[Path]:
    """Every spelling of `p` the deny rules and the audit know: as given (absolute, a junction or symbolic link kept),
    resolved, and on Windows their 8.3 short names. A path mixing short and long parts is not one of them."""
    p = Path(p).expanduser()
    out: list[Path] = []
    for q in (p.absolute(), p.resolve()):
        for r in (q, short_path(q) if q.exists() else None):
            if r is not None and os.path.normcase(str(r)) not in {os.path.normcase(str(x)) for x in out}:
                out.append(r)
    return out


def isolation_paths(tasks_file=None, hide=()) -> list[Path]:
    """The run's own checkout (both spellings), its task generators and data, the --tasks file and the --hide paths,
    each with its aliases."""
    roots = [ROOT, EVAL_ABS.parents[1]]
    base = [*roots, *(r / d for r in roots for d in DATA_DIRS), *([Path(tasks_file)] if tasks_file else []),
            *(Path(h) for h in hide or ())]
    out: list[Path] = []
    for p in base:
        for q in aliases(p):
            if os.path.normcase(str(q)) not in {os.path.normcase(str(x)) for x in out}:
                out.append(q)
    return out


def isolation_unit(dest: Path, hub: Path, hidden) -> PF.Unit:
    """preflight.Unit for a strength unit: its own folder `dest` (repo, hub, homes) stays readable and writable. A
    hidden file (the --tasks file) gets its own deny rules: forbidden()'s rules cover a folder's contents (/**)."""
    files = [p for p in hidden if Path(p).is_file()]
    return PF.Unit(f"strength-{Path(dest).name}", Path(dest), Path(dest) / "repo", Path(hub), claude="config-dir",
                   hidden=tuple(hidden), deny=tuple(f"{t}({PF._rule_path(f)})" for f in files for t in ("Read", "Edit")),
                   flags=CONTENT_PATTERNS)


def python_paths() -> list[Path]:
    """The interpreter the units' `python` is (common.lead_env puts its folder first on PATH) and its prefix (a venv)."""
    return [Path(sys.prefix), Path(sys.executable).parent]


def _ancestor_paths(paths, home) -> list[str]:
    """Each forbidden path's parent folders, canonical (not a drive or the file-system root)."""
    out: list[str] = []
    for p in paths:
        for a in PurePosixPath(PF.canon(Path(p).as_posix(), home)).parents:
            s = str(a).rstrip("/")
            if len([x for x in s.split("/") if x]) >= 2 and s not in out:
                out.append(s)
    return out


def _ancestors(paths, home) -> list[re.Pattern]:
    """The same as whole path tokens: a recursive search or a Grep/Glob tool call there reads the forbidden folder."""
    return [re.compile(PF._B + re.escape(s) + _TOKEN_END) for s in _ancestor_paths(paths, home)]


def content_hit(p) -> str | None:
    """The content pattern a path's own spelling matches (an --out, --claude-home or --codex-home named so would make
    every tool call on the unit's own files look like a read of the task folder), or None."""
    for q in aliases(p) if Path(p).exists() else [Path(p).expanduser().absolute()]:
        t = PF.canon(q.as_posix(), Path.home())
        for rx in CONTENT_PATTERNS:
            if re.search(rx, t, re.I):
                return rx
    return None


def _nav_values(obj, keyed: bool = True) -> list[str]:
    if isinstance(obj, str):
        return [obj] if keyed else []
    if isinstance(obj, list):
        return [x for o in obj for x in _nav_values(o, keyed)]
    if isinstance(obj, dict):
        return [x for k, v in obj.items() for x in _nav_values(v, k in NAV_KEYS) if isinstance(v, (str, list, dict))]
    return []


def nav_view(s: str) -> tuple[str, bool]:
    """A tool call's navigation fields as text, and whether it is a Grep/Glob-style search (a "pattern" or "glob").
    A Write/Edit body (content, old_string, new_string, edits) is left out: writing code that says `tree` or `../..`
    reads nothing. Text that is not a JSON object (a Codex command string) is all navigation."""
    try:
        obj = json.loads(s)
    except (ValueError, TypeError):
        return s, False
    if isinstance(obj, dict):
        return "\n".join(_nav_values(obj)), "pattern" in obj or "glob" in obj
    return "\n".join(_nav_values(obj)), False


def climbs_out(text: str, cwd: str, work: str, parents=frozenset()) -> bool:
    """Does this (canonical) navigation text leave the unit's folder `work`, starting from `cwd`? Paths are resolved
    in the order they appear; a `cd` moves the starting point. A hit: any relative path starting with `..` or `./..`
    (whatever the command) that lands outside `work`; a `cd` with no target or to `~` (home, outside the unit); a `cd`
    to a folder outside `work` that holds a forbidden path (`parents`: their canonical parent folders), from which a
    relative read would reach it; a `cd` target that cannot be resolved (a variable, a subshell) and contains `..`."""
    import posixpath
    here = cwd
    for m in _NAV.finditer(text):
        if m.group("bare") is not None:
            return True
        target = m.group("cd")
        if target is not None:
            if target == "-":
                continue
            if target == "~":
                return True
            if re.search(r"[$%`(]", target):
                segment = re.split(r"[;&|\n]", text[m.start():], maxsplit=1)[0]     # this cd's whole argument
                if ".." in segment:
                    return True
                continue
            new = posixpath.normpath(target if re.match(r"^(?:[a-z]:)?/", target, re.I) else here + "/" + target)
            if not PF._under(new, [work]) and (".." in target.split("/") or new.rstrip("/") in parents):
                return True
            here = new
            continue
        if not PF._under(posixpath.normpath(here + "/" + m.group("up")), [work]):
            return True
    return False


def _with_resolved(t: str) -> str:
    """`t` plus each absolute path in it that has a `..` part, resolved (`/eval/u/../../relayline` names relayline)."""
    import posixpath
    extra = [posixpath.normpath(m.group("p")) for m in _ABS_DOTS.finditer(t)]
    return t + ("\n" + "\n".join(extra) if extra else "")


def _masks(paths, home, label: str) -> list[tuple[re.Pattern, str]]:
    out = []
    for p in paths:
        for q in aliases(p):
            out.append((re.compile(re.escape(PF.canon(q.as_posix(), home)) + r"(?=/|$|[\s\"'`;)|,&<>])"), label))
    return sorted(out, key=lambda x: -len(x[0].pattern))       # longest first: a home inside the unit, say


def audit_hits(inputs: list[str], u: PF.Unit, homes=(), cwd=None, out=None, own=()) -> list[str]:
    """Tool calls a unit must not make:
    - preflight.path_hits on the whole call: a forbidden path in any spelling PF.canon() knows (also once an absolute
      path's `..` parts are resolved);
    - a content pattern (CONTENT_PATTERNS) anywhere, a Write/Edit body included (a script written to read the task
      folder, then run);
    - in its navigation fields only (nav_view: never a Write/Edit body), a relative `..` path or a `cd` that leaves
      the unit's folder from `cwd` (the run's working folder, default the unit's repo; see climbs_out);
    - there too, a recursive search, or a Grep/Glob call, on a parent folder of a forbidden path;
    - the run's --out (`out`) in any spelling once the unit's own folder is masked (#467): another unit's folder (an
      on arm's shared-context.md, a mem arm's notes), manifest.json, results.jsonl; `out` and its parents also count
      as parents of a forbidden path.
    The unit's own folder, its `own` files elsewhere (a Claude on unit's lead transcript in the logged-in home) and its
    logged-in `homes` (--claude-home, --codex-home) are masked before any pattern is matched, so their names never
    make a hit (#455); so are the interpreter's folders (running Python is never a hit). A home holding a forbidden
    folder is not masked. preflight already lets this checkout's ccx.py through."""
    home = u.real["home"]
    forbidden = PF.forbidden(u)
    work = PF.canon(Path(u.work).absolute().as_posix(), home)
    here = PF.canon(Path(cwd or u.repo).absolute().as_posix(), home)
    py = [p for p in python_paths() if not any(PF._inside(f, p) for f in forbidden)]   # never hide a forbidden one
    shared = [h for h in homes if h]
    homes = [h for h in shared if not any(PF._inside(f, h) for f in forbidden)]   # likewise
    own_proj = [m for h in shared for m in own_project_masks(u, h, home)]
    masks = (own_proj + _masks([u.work, *own], home, "<unit>") + _masks(homes, home, "<home>")
             + _masks(py, home, "<python>"))
    records = record_patterns(shared, home)
    others = _masks([out], home, "<out>") if out is not None else []
    # unit-x: out itself is a parent; every spelling of out (a junction given and its target)
    near = [*forbidden, *([a / "unit-x" for a in aliases(out)] if out is not None else []),
            *(a / "projects" for h in shared for a in aliases(h))]     # a shared home and above: parents (#470)
    parents = _ancestors(near, home) + ([re.compile(PF._B + re.escape("<home>") + _TOKEN_END)] if shared else [])
    parent_paths = frozenset(_ancestor_paths(near, home))
    no_flags = dataclasses.replace(u, flags=())
    hits = []
    for s in inputs:
        nav, search_tool = nav_view(s)
        nav_c = PF.canon(nav, home)
        bad = climbs_out(nav_c, here, work, parent_paths)
        full, nav_m = _with_resolved(PF.canon(s, home)), _with_resolved(nav_c)
        for rx, label in masks:
            full, nav_m = rx.sub(label, full), rx.sub(label, nav_m)
        bad = bad or bool(PF.path_hits([full], no_flags)) or any(rx.search(full) for rx, _ in others)
        bad = bad or any(rx.search(full) for rx in records)
        bad = bad or any(re.search(rx, full, re.I) for rx in CONTENT_PATTERNS)
        if not bad and (search_tool or _RECURSIVE.search(nav_m)) and any(a.search(nav_m) for a in parents):
            bad = True
        if bad:
            hits.append(s[:200])
    return hits


def _run_cwd(run_dir: Path, u: PF.Unit) -> Path:
    """The run's working folder (run.json's cwd: the repo or its ccx worktree), if it lies in the unit's folder."""
    try:
        cwd = Path(json.loads((run_dir / "run.json").read_text(encoding="utf-8")).get("cwd") or "")
    except (OSError, ValueError, TypeError):
        return u.repo
    return cwd if str(cwd) not in ("", ".") and PF._inside(cwd, u.work) else u.repo


def path_audit(u: PF.Unit, homes=(), out=None, own=()) -> dict:
    """The unit's sub-agent tool calls (every runs/*/events* log ccx kept in its hub, read by preflight.tool_inputs:
    Claude stream-json and Codex --json) checked by audit_hits from that run's working folder (`out`, `own`: as
    there). clean: False on any hit, None when no log was found."""
    runs = u.hub / "ccx" / "runs"
    files = sorted(runs.glob("*/events*")) if runs.is_dir() else []
    n, hits = 0, []
    for f in files:
        inputs = PF.tool_inputs(f.read_text(encoding="utf-8", errors="replace"))
        n += len(inputs)
        hits += audit_hits(inputs, u, homes, _run_cwd(f.parent, u), out, own)
    return {"logs": len(files), "tool_calls": n, "path_hits": hits[:20], "n_path_hits": len(hits),
            "clean": False if hits else (True if files else None)}


def dirty(row: dict) -> bool:
    return (row.get("path_audit") or {}).get("clean") is False


def isolation_plan(tasks_file=None, hide=(), out=None, kind=None, agents=()) -> dict:
    """What a dry run prints about isolation (#454): the --hide paths and every path the first unit is denied. Other
    units differ only in their own folder. With `kind` (#467): each arm's answer-level files (answer_files), per
    agent when they differ, and what each unit is kept from in --out."""
    hidden = isolation_paths(tasks_file, hide)
    dest = (Path(out).resolve() if out else Path(tempfile.gettempdir()) / "strength-<out>") / "unit-0000"
    u = isolation_unit(dest, dest / "hub", hidden)
    extra = {}
    if kind is not None:
        arms = ("off", "on") if kind == "context" else ("nomem", "mem", "hubmem", "hubstart")
        per = {a: {arm: answer_files(kind, arm, a) for arm in arms} for a in agents or ("codex",)}
        first = next(iter(per.values()))
        extra["answer_files"] = first if all(v == first for v in per.values()) else per
        extra["siblings"] = {
            "run_files": list(RUN_FILES),
            "note": "Every unit is kept from the other unit-* folders in --out and from the run files there: a "
                    "tool call naming --out in any spelling, once the unit's own folder is masked, is a path-audit "
                    "hit; Claude units also get Read/Edit deny rules on the run files and on the units before "
                    "theirs (a few unit-NN* globs). Claude units: <claude-home>/projects/"
                    f"{SYNTHETIC_LEAD_FOLDER} is denied and audited for every unit; an on unit's own transcript "
                    "there is not a hit. Not listed in answer_files: the shared logged-in homes' own session "
                    "records (Claude <claude-home>/projects/<slug>/, file-history/ ...; Codex <codex-home>/sessions/, "
                    "archived_sessions/, history.jsonl, *.sqlite ...) also hold the prompt and tool results: the "
                    "parts that are not the unit's own are audited for every unit and denied to Claude units "
                    "(Read rules, #470)"}
    return {"hide": [str(p) for p in hide or ()], "unit": "unit-0000",
            "forbidden_paths": [str(p) for p in PF.forbidden(u)],
            "claude_deny_rules": len(PF.claude_settings(u)["permissions"]["deny"]),
            "content_patterns": list(CONTENT_PATTERNS), **extra,
            "note": "Claude units: Read/Edit deny rules on each path (Read rules also cover Grep/Glob, best effort). "
                    "Codex units: workspace-write confines writes only and codex exec has no read deny, so reads are "
                    "audited, not blocked. Every unit's tool calls are audited after the run (forbidden paths in "
                    "any spelling, the content patterns, a cd or recursive search landing outside the unit's "
                    "folder, a search of a forbidden path's parent); a hit makes the row invalid. DSH logs are "
                    "audited only as far as their format is parsed"}


def check_out(out: Path, hidden, homes=()) -> None:
    """--out must not lie inside a folder the units are denied: preflight.forbidden drops a folder that holds a unit's
    own folder, so that folder would stay readable (this checkout, its worktrees, every hidden path, and the person's
    own homes, hub and config), nor inside a logged-in home (#467). Neither --out nor a logged-in home may be named
    like a content pattern (#455)."""
    for what, p in (("--out", out), *(("a logged-in home", h) for h in homes if h)):
        rx = content_hit(p)
        if rx:
            raise ValueError(f"{what} {p} matches the audit's content pattern {rx!r}: every tool call on the unit's "
                             "own files would look like a read of the task folder; rename it")
    real = PF.real_paths()
    own = [real[k] for k in ("home_codex", "codex_home", "ccx_home", "hub", "dsh_home", "agents_home",
                             "home_claude", "claude_home")]
    for p in [*hidden, PF.ROOT, *PF.other_worktrees(PF.ROOT), *own]:
        if PF._inside(out, p):
            raise ValueError(f"--out {out} is inside {p}, which the units must not read; put it outside")
    for h in homes:
        if h and any(PF._inside(o, a) for o in aliases(out) for a in aliases(h)):
            raise ValueError(f"--out {out} is inside the logged-in home {h}: the audit masks that home as the "
                             "unit's own, so the other units there would stay readable; put it outside")


def needs_codex_home(units) -> bool:
    return any(u.get("agent") == "codex" for u in units)


def needs_claude_home(units) -> bool:
    return any(u.get("agent") == "claude" for u in units)


def unit_env(unit: dict, dest: Path, codex_home: Path | None, claude_home: Path | None = None,
             fresh: bool = False, extra_deny=()) -> dict:
    """The unit's environment and its own folders. Everything stays in `dest` except the logged-in homes a unit's own
    CLI needs: a Codex unit uses `codex_home`, a Claude unit `claude_home` (issue #320 / #345: an empty home has no
    login). Claude units never get web tools; a `fresh` (--tasks) run's Codex units neither. `extra_deny`: more
    Claude deny rules (the isolation rules run_unit passes, #454)."""
    agent = unit.get("agent")
    if agent == "codex" and codex_home is None:
        raise ValueError("a Codex unit needs a logged-in Codex home (--codex-home)")
    if agent == "claude" and claude_home is None:
        raise ValueError("a Claude unit needs a logged-in Claude home (--claude-home)")
    isolated = lead_env()
    codex_dir = str(codex_home) if agent == "codex" else str(dest / "codex-home")
    claude_dir = str(claude_home) if agent == "claude" else str(dest / "claude-home")
    isolated.update(CCX_CONFIG=str(dest / "config.toml"), CODEX_HOME=codex_dir, CODEX_SQLITE_HOME=codex_dir,
                    CLAUDE_CONFIG_DIR=claude_dir, CCX_CODEX_ISOLATE="1",
                    DSH_HOME=str(dest / "dsh-home"), CCX_NO_AUTO_ARCHIVE="1",
                    CCX_CLAUDE_NO_SKILLS="1", CCX_CLAUDE_SETTING_SOURCES="project,local")
    if agent == "claude":
        # Merged into settings the caller's environment may already give (e.g. deny rules), never replacing them
        raw = isolated.get("CCX_CLAUDE_SETTINGS", "").strip()
        given = json.loads(raw if raw.startswith("{") else Path(raw).read_text(encoding="utf-8")) if raw else {}
        perms = dict(given.get("permissions") or {})
        perms["deny"] = sorted(set(perms.get("deny") or []) | set(CLAUDE_NO_WEB["permissions"]["deny"])
                               | set(extra_deny))
        isolated["CCX_CLAUDE_SETTINGS"] = json.dumps({**given, "permissions": perms})
    env = check_env(dest, isolated)
    for name in ("codex-home", "claude-home", "dsh-home"):
        (dest / name).mkdir(parents=True, exist_ok=True)
    (dest / "config.toml").write_text("", encoding="utf-8", newline="")
    if fresh and agent == "codex":
        # A run's [subagent] switches come from the hub's tiers.toml (ccx.config.load_config), not CCX_CONFIG
        tiers = Paths(Path(env["CCX_HUB"])).user_tiers
        tiers.parent.mkdir(parents=True, exist_ok=True)
        tiers.write_text(CODEX_NO_WEB_CONFIG, encoding="utf-8", newline="")
    return env


def write_lead_transcript(task: dict, home: Path, sid: str, folder: str = "lead") -> tuple[str, Path]:
    """The synthetic lead conversation in `home`/projects/`folder`/`sid`.jsonl, found by ccx by its session id."""
    transcript = home / "projects" / folder / f"{sid}.jsonl"
    transcript.parent.mkdir(parents=True, exist_ok=True)
    transcript.write_text("".join(json.dumps(e) + "\n" for e in lead_transcript(task, time.time())),
                          encoding="utf-8", newline="")
    return sid, transcript


def run_unit(unit: dict, kind: str, dest: Path, budget: float, codex_home: Path | None = None,
             claude_home: Path | None = None, tasks: list[dict] | None = None, fresh: bool = False,
             hidden=None) -> dict:
    """All writes and client state stay in this unit, except a Codex unit's own Codex files: those go to the
    caller's logged-in `codex_home` (shared by the run's Codex units, as in p4_long_session.py), because a fresh
    empty CODEX_HOME has no login (issue #320: every Codex unit got 401). A Claude unit likewise uses the caller's
    logged-in `claude_home`; its synthetic lead transcript gets a unique session id there (#345). A Codex unit's
    TMP/TEMP/TMPDIR is its own tmp/ folder, and each workspace-write `codex exec` gets a private temp folder inside
    its working directory, as in p4 (issue #327: under the unelevated sandbox the system %TEMP% is not writable and
    PowerShell hangs). `tasks`: a frozen --tasks file's tasks instead of the built-in ones. Hidden tests arrive after
    the CLI exits. `hidden`: the paths its agents must not open (isolation_paths(); default: this checkout and its
    task data, #454): deny rules for a Claude unit, and every unit's tool calls are audited (row["path_audit"])."""
    pool = tasks if tasks is not None else (TASKS if kind == "context" else CASES)
    task = next(t for t in pool if t["id"] == unit["task"])
    hidden = isolation_paths() if hidden is None else tuple(hidden)
    if claude_home is not None:
        # Claude units' lead transcripts share the logged-in home (#467): denied to every unit, masked as no unit's
        synth = Path(claude_home) / "projects" / SYNTHETIC_LEAD_FOLDER
        synth.mkdir(parents=True, exist_ok=True)
        seen = {os.path.normcase(str(p)) for p in hidden}
        hidden = (*hidden, *(a for a in aliases(synth) if os.path.normcase(str(a)) not in seen))
    out = run_out(dest)
    iso = isolation_unit(dest, dest / "hub", hidden)
    deny = ([*PF.claude_settings(iso)["permissions"]["deny"], *sibling_deny(dest), *record_deny(claude_home, dest)]
            if unit.get("agent") == "claude" else ())
    env = unit_env(unit, dest, codex_home, claude_home, fresh, extra_deny=deny)
    size = len(env.get("CCX_CLAUDE_SETTINGS", "")) if unit.get("agent") == "claude" else 0
    if size > SETTINGS_MAX_CHARS:
        # ccx passes them on the command line (--settings <json>); Windows stops at 32767 characters
        raise ValueError(f"Claude settings are {size} characters (> {SETTINGS_MAX_CHARS}): the command line would "
                         "overflow; fewer --hide paths or a shorter --out")
    repo = make_repo(task, dest / "repo")
    if unit.get("agent") == "codex":
        tmp = dest / "tmp"
        tmp.mkdir(parents=True, exist_ok=True)
        env.update({k: str(tmp) for k in ("TMP", "TEMP", "TMPDIR")})
        env.update(PF.codex_workspace_tmp_env(repo, dest))
    hub = Path(env["CCX_HUB"])
    iso = dataclasses.replace(iso, hub=hub)
    # No app/session archiving: these synthetic homes are retained as evidence.
    def command(args):
        return run_tree([sys.executable, str(ROOT / "ccx.py"), *args], cwd=repo, env=env, timeout=180)

    def setup(args):
        result = command(args)
        if result.returncode:
            raise RuntimeError("synthetic context/memory setup failed")
        return result.stdout

    brief, payload, own = task["brief"], "", ()
    row = {**unit, "ok": None, "usd": 0.0, "rc": None, "native_hook_execution": "Unknown"}
    if unit.get("agent") == "codex":
        row["tmp_policy"] = "codex-workspace-private"
    started = False
    t0 = time.monotonic()
    try:
        if kind == "context":
            # Only the on arm gets the lead transcript (#467: it is the agreed answer). With --context off ccx never
            # reads it, so the off arm keeps the same session id and environment, without the file.
            on = unit["arm"] == "on"
            if unit.get("agent") == "claude":
                # The shared logged-in home holds every Claude unit's transcript: a unique id per unit
                sid = f"strength-{uuid.uuid4().hex}"
                if on:
                    _, transcript = write_lead_transcript(task, claude_home, sid, SYNTHETIC_LEAD_FOLDER)
                    row["lead_transcript"] = str(transcript)
                    own = (transcript,)
            else:
                sid = "strength-synthetic-lead"
                if on:
                    write_lead_transcript(task, dest / "claude-home", sid)
            env.update(CCX_LEAD_SESSION=sid, CCX_LEAD_VIEW="full")
        else:
            # Same distractors in every arm; only the relevant note's delivery changes.
            for topic, text in task.get("distractors", DISTRACTORS):
                setup(["mem", "add", "--by", "claude", "--topic", topic, text])
            if unit["arm"] == "mem":
                setup(["ctx", "--cwd", str(repo), "init"])
                setup(["ctx", "--cwd", str(repo), "add", task["memory"]])
            elif unit["arm"] in ("hubmem", "hubstart"):
                setup(["mem", "add", "--by", "claude", "--topic", task["kind"], task["memory"]])
            if unit["arm"] == "hubstart":
                payload = setup(["mem", "delta", "--as", unit["agent"], "--peek"])
                # This arm tests delivery of the actual startup payload, not installation of a native hook.
                brief = "[Synthetic startup memory payload]\n" + payload + "\n[Task]\n" + brief
        extra = ["--from", "claude", "--to", unit["agent"], "--model", unit["model"],
                 "--effort", unit["effort"], "--budget", str(budget), "--minutes", "3",
                 "--no-escalate", "--no-fallback", "--no-subagents", "--review", "off",
                 "--context", unit["arm"] if kind == "context" else "off"]
        started = True
        result = run_tree(ccx_run(repo, "strength-retest", brief, extra), cwd=repo, env=env,
                          timeout=CCX_RUN_TIMEOUT_S)
        receipt = last_json(result.stdout)
        row.update(rc=result.returncode, run_id=receipt.get("run_id"), status=receipt.get("status"),
                   kind=receipt.get("kind"), **score(repo, task))
        prompt = hub / "ccx" / "runs" / str(receipt.get("run_id")) / "prompt.md"
        content = prompt.read_text(encoding="utf-8") if prompt.exists() else ""
        row["note_in_prompt"] = task.get("memory", task.get("settle", "")) in content
        context_file = repo / ".ccx" / "context.md"
        row["project_context_referenced"] = (str(context_file) in content and context_file.exists()
            and task.get("memory", "") in context_file.read_text(encoding="utf-8"))
        row["startup_payload_delivered"] = bool(payload) and payload in content
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, KeyboardInterrupt) as exc:
        row["error"] = type(exc).__name__
    finally:
        row["usd"] = unit_cost(hub) if started else 0.0
        if started:
            try:
                own = (*own, *own_sessions(hub, codex_home))      # its own Codex rollouts are not hits (#470)
                row["path_audit"] = path_audit(iso, (claude_home, codex_home), out, own)
            except OSError as exc:
                row["path_audit"] = {"clean": None, "error": type(exc).__name__}
        row["wall_s"] = round(time.monotonic() - t0, 4)
    return row


def execute(manifest: dict, out: Path, budget: float, unit_budget: float, codex_home: Path | None = None,
            claude_home: Path | None = None) -> dict:
    if (not math.isfinite(budget) or not 0 < budget <= manifest["cap_usd"] or
            not math.isfinite(unit_budget) or unit_budget <= 0):
        raise ValueError("invalid budget or unit budget")
    # Refuse before anything starts, never fall back to an empty home (issue #320).
    if needs_codex_home(manifest["units"]) and codex_home is None:
        raise ValueError("units run Codex: pass a logged-in Codex home (--codex-home)")
    if needs_claude_home(manifest["units"]) and claude_home is None:
        raise ValueError("units run Claude: pass a logged-in Claude home (--claude-home)")
    tasks, fresh = None, manifest.get("tasks_file") is not None
    if fresh:
        # Checked again right before the run: the file must still be the preregistered one (issue #345).
        from strength_retest import load_tasks
        tasks = load_tasks(Path(manifest["tasks_file"]), manifest.get("tasks_sha256"), manifest["kind"])
    on_invalid = manifest.get("on_invalid", "stop")
    if on_invalid not in ("stop", "continue"):
        raise ValueError("on_invalid must be stop or continue")
    # What every unit must not open (#454): this checkout, its task data, the task file, the plan's --hide paths
    hidden = isolation_paths(manifest.get("tasks_file"), (manifest.get("isolation") or {}).get("hide") or ())
    check_out(out, hidden, (codex_home, claude_home))
    # A fresh directory prevents accidental cost resets, repeated units and overwriting evidence.
    out.mkdir(parents=True, exist_ok=False)
    frozen_plan = {**manifest, "runtime_budget_usd": budget, "unit_budget_usd": unit_budget,
                   "codex_home": str(codex_home) if codex_home is not None else None}
    if claude_home is not None:
        frozen_plan["claude_home"] = str(claude_home)
    (out / "manifest.json").write_text(json.dumps(frozen_plan, indent=2) + "\n", encoding="utf-8", newline="")
    if on_invalid == "continue":
        rows, spent, charged, stopped, reason = _run_continuing(manifest, out, budget, unit_budget, codex_home,
                                                                claude_home, tasks, fresh, hidden)
        invalid = sum(r.get("invalid") is True for r in rows)
        extra = {"on_invalid": "continue", "invalid": invalid,
                 "unknown_cost_units": sum(r.get("usd") is None for r in rows)}
    else:
        rows, spent, charged, stopped, reason = _run_stopping(manifest, out, budget, unit_budget, codex_home,
                                                              claude_home, tasks, fresh, hidden)
        extra = {}
    report = {"kind": manifest["kind"], "dry_run": False, "evidence": "engineering check",
              "attempted": len(rows), "planned": manifest["n"], "rows": rows,
              "successes": sum(r.get("ok") is True for r in rows), "budget_usd": budget,
              "known_spent_usd": round(spent, 8), "spent_usd": round(spent, 8) if charged == spent else None,
              "charged_usd": round(charged, 8), "budget_stopped": stopped, "stop_reason": reason,
              "gate": "Unknown", "native_hook_execution": "Unknown",
              "path_audit_unclean": sum(dirty(r) for r in rows), **extra}
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="")
    return report


def _one(manifest, index, unit, out, reservation, codex_home, claude_home, tasks, fresh, hidden=None) -> dict:
    try:
        row = run_unit(unit, manifest["kind"], out / f"unit-{index:04d}", reservation, codex_home,
                       claude_home=claude_home, tasks=tasks, fresh=fresh, hidden=hidden)
    except (Exception, KeyboardInterrupt) as exc:  # retain a failed unit even when setup could not start
        row = {**unit, "ok": None, "usd": None, "error": type(exc).__name__}
    row.update(code_pin=manifest["code_pin"], reservation_usd=reservation)
    return row


ENVIRONMENT_KINDS = ("auth", "quota")   # a receipt saying the CLI could not work at all: no task outcome follows
ARM_LIMIT_KINDS = ("timeout", "over_budget", "max_usd")   # the sub-agent's own time/cost cap (ccx/delegate.py)


def _run_continuing(manifest, out, budget, unit_budget, codex_home, claude_home, tasks, fresh, hidden=None):
    """--on-invalid continue (the round-2 preregistration): an environment error, a receipt status "error" or an
    unknown cost makes the row invalid (recorded, "invalid": true) and the group goes on. An arm's own timeout or
    cap hit with a known cost is a valid row with ok false. The group stops only on: the budget, a unit that spent
    more than its reservation, Ctrl-C, more than MAX_UNKNOWN_COST_UNITS unknown-cost units (each charged at its
    reservation), or the environment check: a receipt of kind auth/quota (issue #321: 42 units ran on with 401).
    A tool call on a forbidden path (path_audit, #454) makes the row invalid too."""
    from strength_retest import MAX_UNKNOWN_COST_UNITS
    rows, spent, charged, unknown = [], 0.0, 0.0, 0
    for index, unit in enumerate(manifest["units"]):
        if charged >= budget - 1e-9:
            return rows, spent, charged, True, "budget exhausted"
        reservation = min(unit_budget, round(budget - charged, 8))
        row = _one(manifest, index, unit, out, reservation, codex_home, claude_home, tasks, fresh, hidden)
        amount = row["usd"]
        if (row.get("status") == "error" and row.get("kind") in ARM_LIMIT_KINDS and amount is not None
                and not row.get("error")):
            # The sub-agent's own timeout or cap: ccx has no structured result, so the receipt says status "error",
            # but the preregistration counts it as a valid row with ok = False (hidden test kept as hidden_ok)
            row.update(arm_limit=row["kind"], hidden_ok=row.get("ok"), ok=False)
        receipt_error = row.get("status") == "error" and "arm_limit" not in row
        reasons = [r for r, bad in (("error", bool(row.get("error"))), ("receipt status error", receipt_error),
                                    ("unknown cost", amount is None), ("no outcome", row.get("ok") is None),
                                    ("forbidden path in a tool call", dirty(row))) if bad]
        row.update(invalid=bool(reasons), invalid_reason=", ".join(reasons) or None)
        rows.append(row)
        append_jsonl(out / "results.jsonl", row)
        if amount is None:
            charged += reservation
            unknown += 1
        else:
            spent += amount
            charged += amount
        if row.get("error") == "KeyboardInterrupt":
            return rows, spent, charged, True, "interrupted"
        if amount is None and unknown > MAX_UNKNOWN_COST_UNITS:
            return rows, spent, charged, True, (f"Unknown cost in {unknown} units (> {MAX_UNKNOWN_COST_UNITS}); "
                                                "retained reservations and stopped")
        if amount is not None and amount > reservation + 1e-9:
            return rows, spent, charged, True, "unit exceeded reservation"
        if row.get("status") == "error" and row.get("kind") in ENVIRONMENT_KINDS:
            return rows, spent, charged, True, f"environment: ccx receipt kind={row.get('kind')}"
    return rows, spent, charged, False, ""


def _run_stopping(manifest, out, budget, unit_budget, codex_home, claude_home, tasks, fresh, hidden=None):
    """The default: the group stops on the first errored, receipt-error or unknown-cost unit (round 1), or on the
    first unit whose tool calls touched a forbidden path (#454: that row alone is marked invalid)."""
    rows, spent, charged, stopped, reason = [], 0.0, 0.0, False, ""
    for index, unit in enumerate(manifest["units"]):
        if charged >= budget - 1e-9:
            stopped, reason = True, "budget exhausted"
            break
        reservation = min(unit_budget, round(budget - charged, 8))
        row = _one(manifest, index, unit, out, reservation, codex_home, claude_home, tasks, fresh, hidden)
        if dirty(row):
            row.update(invalid=True, invalid_reason="forbidden path in a tool call")
        rows.append(row)
        append_jsonl(out / "results.jsonl", row)
        amount = row["usd"]
        if amount is None:
            charged += reservation
            stopped, reason = True, "Unknown cost; retained reservation and stopped"
            break
        spent += amount
        charged += amount
        if amount > reservation + 1e-9 or row.get("kind") == "over_budget" or row.get("error"):
            stopped, reason = True, "unit exceeded reservation or interrupted"
            break
        if dirty(row):
            stopped, reason = True, "forbidden path in a tool call (path audit)"
            break
        if row.get("status") == "error":
            # The ccx receipt says the run itself failed (e.g. kind=auth): the preregistration stops the group on
            # an errored row, not only on a Python exception here (issue #321: 42 units ran on with 401).
            stopped, reason = True, f"ccx receipt status error (kind={row.get('kind')})"
            break
    return rows, spent, charged, stopped, reason
