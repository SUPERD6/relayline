"""Context/memory retest plans; execution requires explicit --run and --budget."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import HIDDEN, ROOT, lead_env
from l5_memory import CASES, DISTRACTORS
from shared_context_ab import TASKS, MODELS

AGENT_MODELS = {**MODELS, "claude": ("haiku", "low")}   # claude: the shipped T1 Claude rung (#345)
FRESH_MAX_UNIT_USD = 0.15     # per-invocation reservation ceiling with --tasks (issue #345)
FRESH_HARD_CAP_USD = 10.0     # total ceiling with --tasks, whatever the file's size
MAX_UNKNOWN_COST_UNITS = 3    # --on-invalid continue: the 4th unknown-cost unit stops the group
CLAUDE_HOME_REACH = ("CLAUDE.md", "agents", "skills", "commands")   # refused in a --claude-home
# What a --tasks run's sub-agents run without, printed in the plan (the dry-run is archived before any run)
SUBAGENT_TOOLS = {"claude": "CCX_CLAUDE_SETTINGS permissions.deny WebFetch, WebSearch",
                  "codex": "[subagent] codex_lean_tools = true in the unit hub: -c web_search=\"disabled\", "
                           "--disable image_generation, --disable goals",
                  "dsh": "unchanged"}


def _text(task: dict, key: str, where: str, optional: bool = False) -> None:
    value = task.get(key)
    if optional and value is None:
        return
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{where}: {key!r} must be a nonempty string")


def _distractors(value, where: str) -> list[tuple[str, str]]:
    if (not isinstance(value, list) or any(not isinstance(d, list) or len(d) != 2 or
                                           not all(isinstance(x, str) and x.strip() for x in d) for d in value)):
        raise ValueError(f"{where}: distractors must be a list of [topic, text] pairs")
    return [tuple(d) for d in value]


def load_tasks(path: Path, sha256: str | None, kind: str) -> list[dict]:
    """A frozen task file (JSON): {"kind": "context"|"memory", "tasks": [...], "distractors"?: [[topic, text]]}.
    Its SHA-256 must equal the value recorded in the preregistration (--tasks-sha256) or nothing is planned or run.
    Context task: id, files {path: text}, brief, settle (the agreement), reversed (null or the dropped option),
    hidden (pytest text), neutral (bool), source. Memory task: id, files, brief, memory (the convention), hidden,
    source, optional visible, kind (mem topic, default "convention"), neutral (default false), distractors
    (default: the file's, else l5_memory's)."""
    if not sha256:
        raise ValueError("--tasks needs --tasks-sha256 (the value recorded in the preregistration)")
    raw = Path(path).read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    if actual != sha256.strip().lower():
        raise ValueError(f"task file SHA-256 {actual} does not match --tasks-sha256 {sha256}; refusing a changed file")
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict) or data.get("kind") != kind:
        raise ValueError(f"task file kind must be {kind!r}")
    tasks = data.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("task file needs a nonempty list 'tasks'")
    shared = _distractors(data["distractors"], "task file") if "distractors" in data else list(DISTRACTORS)
    seen, out = set(), []
    for index, task in enumerate(tasks):
        where = f"task {index}"
        if not isinstance(task, dict):
            raise ValueError(f"{where} must be an object")
        for key in ("id", "brief", "hidden", "source"):
            _text(task, key, where)
        if task["id"] in seen:
            raise ValueError(f"duplicate task id {task['id']!r}")
        seen.add(task["id"])
        files = task.get("files")
        if (not isinstance(files, dict) or not files or
                any(not isinstance(k, str) or not k or not isinstance(v, str) for k, v in files.items())):
            raise ValueError(f"{where}: 'files' must map paths to text")
        for name in files:
            parts = Path(name).parts
            if Path(name).is_absolute() or ".." in parts or name.startswith(("/", "\\")) or \
                    Path(name).name in ("test_task.py", HIDDEN):
                raise ValueError(f"{where}: file path {name!r} must stay inside the repo and not be a test file "
                                 "the runner writes")
        item = dict(task)
        if kind == "context":
            _text(task, "settle", where)
            _text(task, "reversed", where, optional=True)
            if type(task.get("neutral")) is not bool:
                raise ValueError(f"{where}: 'neutral' must be true or false")
            item["reversed"] = task.get("reversed")
        else:
            _text(task, "memory", where)
            _text(task, "visible", where, optional=True)
            _text(task, "kind", where, optional=True)
            if type(task.get("neutral", False)) is not bool:
                raise ValueError(f"{where}: 'neutral' must be true or false")
            item["kind"] = task.get("kind") or "convention"
            item["neutral"] = task.get("neutral", False)
            item["distractors"] = _distractors(task["distractors"], where) if "distractors" in task else shared
        out.append(item)
    return out


def resolve_hide(values) -> list[Path]:
    """--hide paths (#454, the semantics of p4's --hide, #451): made absolute against the folder the eval starts in,
    de-duplicated; a missing one is refused (a typo would deny nothing). Both spellings are kept when a junction or
    symbolic link makes them differ. A git checkout brings its other git worktrees along (#455: each holds the same
    answers). A path holding the Python that runs the units is refused: their `python` is it."""
    out: list[Path] = []
    seen: set[str] = set()
    for v in values or ():
        given = Path(v).expanduser().absolute()
        real = given.resolve()
        if not real.exists():
            raise ValueError(f"--hide {v}: no such file or folder ({real}); no model called")
        more = []
        if real.is_dir() and (real / ".git").exists():
            import preflight as PF
            more = [w for w in PF.other_worktrees(real) if Path(w).exists()]
        for q in (given, real, *(Path(w).absolute() for w in more), *(Path(w).resolve() for w in more)):
            if any(_inside(Path(x), q) for x in (sys.executable, Path(sys.executable).resolve())):
                raise ValueError(f"--hide {v} holds the Python running the units ({sys.executable}) in {q}; hide "
                                 "the other checkout itself. No model called")
            key = str(q).lower() if sys.platform == "win32" else str(q)
            if key not in seen:
                seen.add(key)
                out.append(q)
    return out


def _inside(p: Path, root: Path) -> bool:
    try:
        Path(p).absolute().relative_to(Path(root).absolute())
        return True
    except ValueError:
        return False


def chosen_agents(kind: str, agents) -> list[str]:
    picked = list(agents) if agents else (list(MODELS) if kind == "context" else ["codex"])
    if not picked or len(set(picked)) != len(picked) or any(a not in AGENT_MODELS for a in picked):
        raise ValueError(f"unknown or repeated agent in {picked}; choose from {', '.join(AGENT_MODELS)}")
    return picked


def plan(kind: str, reps: int = 3, unit_usd: float | None = None, tasks: Path | None = None,
         tasks_sha256: str | None = None, agents=None, hide=None, out: Path | None = None) -> dict:
    """tasks/tasks_sha256/agents (issue #345) are off by default: without them the plan is the old one. With tasks or
    hide (#454) it also prints `isolation`: what every unit is denied (`out`: the run's --out, for the unit folder)."""
    if reps < 1 or (unit_usd is not None and (not math.isfinite(unit_usd) or unit_usd < 0)):
        raise ValueError("reps must be positive; unit estimate must be finite and non-negative")
    if tasks is None and tasks_sha256:
        raise ValueError("--tasks-sha256 is given without --tasks")
    fresh = load_tasks(tasks, tasks_sha256, kind) if tasks is not None else None
    picked = chosen_agents(kind, agents)
    hidden = resolve_hide(hide)
    if kind == "context":
        task_list = fresh if fresh is not None else TASKS
        units = [{"task": t["id"], "scenario": "neutral" if t["neutral"] else "favourable",
                  "agent": agent, "model": AGENT_MODELS[agent][0], "effort": AGENT_MODELS[agent][1],
                  "arm": arm, "rep": rep,
                  **({"neutral": t["neutral"], "source": t["source"]} if fresh is not None else {})}
                 for rep in range(1, reps + 1) for t in task_list
                 for agent in picked for arm in ("off", "on")]
        cap = 4.0
        # Historical total includes the single permitted rework. A proxy, never a new control arm.
        historical = ROOT / "docs/research/data/2026-10-25-shared-context-ab.json"
        old = json.loads(historical.read_text(encoding="utf-8"))
        groups = old["summary"]["by"]
        proxy = sum(groups[f"all:{s}"][a]["usd"] for s in ("settled", "neutral") for a in ("off", "on")) / 84
        source = historical.name
        arms = {"off": "--context off", "on": "--context on"}
    elif kind == "memory":
        # Original 3 project conventions + 3 previously used L5 cases. Not unseen holdout tasks.
        # A --tasks file replaces them with new tasks (previously_used false).
        task_list = fresh if fresh is not None else CASES
        units = [{"task": t["id"], "arm": arm, "rep": rep, "agent": agent,
                  "model": AGENT_MODELS[agent][0], "effort": AGENT_MODELS[agent][1],
                  "previously_used": fresh is None,
                  **({"neutral": t["neutral"], "source": t["source"]} if fresh is not None else {})}
                 for rep in range(1, reps + 1) for t in task_list
                 for agent in picked for arm in ("nomem", "mem", "hubmem", "hubstart")]
        cap = 3.0
        historical = ROOT / "docs/research/data/2026-10-25-l5-memory.json"
        old = json.loads(historical.read_text(encoding="utf-8"))
        proxy = old["summary"]["spend_usd"] / old["summary"]["units"]
        source = historical.name
        who = picked[0] if len(picked) == 1 else "<unit agent>"
        arms = {"nomem": "no convention", "mem": "ccx ctx add (project context)",
                "hubmem": "ccx mem add (delegation brief)",
                "hubstart": f"ccx mem add; ccx mem delta --as {who} --peek (startup payload)"}
    else:
        raise ValueError("unknown retest kind")
    if fresh is not None:
        # Scaled to the file's units, never above the hard ceiling (issue #345).
        cap = min(FRESH_HARD_CAP_USD, round(len(units) * FRESH_MAX_UNIT_USD, 2))
    estimate = len(units) * (proxy if unit_usd is None else unit_usd)
    # Trust only this script's repository for these invocations, never alter global Git configuration.
    git = ["git", "-c", f"safe.directory={ROOT.as_posix()}"]
    pin = subprocess.run([*git, "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True,
                         encoding="utf-8", errors="replace", check=True).stdout.strip()
    dirty = bool(subprocess.run([*git, "status", "--porcelain"], cwd=ROOT, capture_output=True,
                                text=True, encoding="utf-8", errors="replace", check=True).stdout.strip())
    data = {"evidence": "not run", "dry_run": True, "kind": kind, "code_pin": pin, "dirty": dirty,
            "reps": reps, "tasks": len(task_list), "arms": arms,
            "units": units, "n": len(units), "cap_usd": cap, "estimated_usd": round(estimate, 6),
            "within_estimated_cap": estimate <= cap,
            "estimate_basis": "caller unit estimate" if unit_usd is not None else f"historical proxy: {source}",
            "execution": "opt-in: execute KIND --run --budget USD --out FRESH_DIRECTORY",
            "interruption": "retain every failure/interruption and cost; missing outcomes remain Unknown",
            "metrics": ["hidden-test successes / all attempts", "all workflow cost / successes", "rework rate"],
            "limitations": ["Historical costs are not current controls or a guaranteed spend bound.",
                            "Pin a clean independent clone and preregister before real evaluation.",
                            "hubstart payload probe does not prove a native client executes SessionStart.",
                            "Pass thresholds and final-set selection must be preregistered by the lead."]}
    if fresh is not None:
        data.update(tasks_file=str(Path(tasks).resolve()), tasks_sha256=tasks_sha256.strip().lower(),
                    task_ids=[t["id"] for t in fresh], neutral_tasks=[t["id"] for t in fresh if t["neutral"]],
                    agents=picked, cap_basis=f"min({FRESH_HARD_CAP_USD}, units x {FRESH_MAX_UNIT_USD})",
                    subagent_tools={a: SUBAGENT_TOOLS[a] for a in picked})
        if unit_usd is None:
            data["estimate_basis"] += " (old tasks; new, harder tasks may cost more)"
    if fresh is not None or hidden:
        # Units are isolated either way (#454); the list is printed when it can matter, so old plans stay as they were
        from strength_runner import isolation_plan
        data["isolation"] = isolation_plan(Path(tasks).resolve() if tasks is not None else None, hidden, out,
                                           kind, picked)
    return data


def probe_hook(hub: Path, cwd: Path, agent: str) -> dict:
    """Run the exact memory startup command against an explicitly supplied synthetic hub."""
    env = lead_env()
    env.update(CCX_HUB=str(hub.resolve()), CCX_NO_QUOTA_PROBE="1")
    # Isolate optional user configuration and do not inherit another client's home/state.
    env["CCX_CONFIG"] = str(hub.resolve() / "probe-config.toml")
    command = [sys.executable, str(ROOT / "ccx.py"), "mem", "delta", "--as", agent, "--peek"]
    result = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=30)
    return {"evidence": "engineering check", "exit_code": result.returncode,
            "payload": result.stdout, "native_hook_execution": "Unknown"}


def _content_name(what: str, home: Path) -> None:
    """A logged-in home named like one of the audit's content patterns is refused (#455): the units' tool calls name
    it, and each would look like a read of the task folder."""
    from strength_runner import content_hit
    rx = content_hit(home)
    if rx:
        raise ValueError(f"{what} refused: {home} matches the audit's content pattern {rx!r}; rename it")


def checked_codex_home(arg: str) -> Path:
    """The --codex-home of a run with Codex units, prepared as p4_long_session.py's is (preflight's
    check_codex_home: an absolute folder apart from your own homes, a login present, nothing that reaches every
    run). A read-only check first; only a home that passes it is then prepared for the start as p4 does
    (write=True: a missing config.toml is written with the keys ccx carries over, on Windows the unelevated
    sandbox, and a synced plugins/ folder is removed). No credential file is opened: the login is checked by
    existence only."""
    import preflight as PF
    if not arg:
        raise ValueError("units run Codex: pass --codex-home <a Codex home you logged in to yourself>; "
                         "an empty home has no login (issue #320)")
    home, real = Path(PF.codex_home_arg(arg)), PF.real_paths()
    _content_name("--codex-home", home)
    for write in (False, True):
        problems, _ = PF.check_codex_home(home, True, real, write=write)
        if problems:
            raise ValueError("--codex-home refused: " + "; ".join(problems))
    return home


def checked_claude_home(arg: str) -> Path:
    """The --claude-home of a run with Claude units (issue #345): an absolute, existing folder you logged in to
    yourself (`CLAUDE_CONFIG_DIR=<dir> claude` then /login), apart from your own Claude home, because the units write
    their sessions and a synthetic lead transcript there. The login is checked by the existence of
    .credentials.json only; no credential file is opened. Without it every unit got an empty CLAUDE_CONFIG_DIR and
    would have run logged out (the Claude side of issue #320)."""
    import preflight as PF
    if not arg:
        raise ValueError("units run Claude: pass --claude-home <a Claude home you logged in to yourself>; "
                         "an empty CLAUDE_CONFIG_DIR has no login (issue #320)")
    home = Path(arg).expanduser()
    if not home.is_absolute():
        raise ValueError(f"--claude-home must be an absolute path: {arg}")
    if not home.is_dir():
        raise ValueError(f"--claude-home refused: {home} is not a folder")
    _content_name("--claude-home", home)
    real = PF.real_paths()
    # As preflight.check_codex_home: no overlap either way with your own homes, hub or this checkout
    for name in ("claude_home", "home_claude", "codex_home", "home_codex", "ccx_home", "hub", "dsh_home",
                 "agents_home", "root"):
        p = real[name]
        if PF._inside(home, p) or PF._inside(p, home):
            how = "inside" if PF._inside(home, p) else "contains"
            raise ValueError(f"--claude-home refused: {home} overlaps your own {name.replace('_', ' ')} ({how} it); "
                             "use a separate dedicated evaluation home")
    # What would reach every unit's Claude: user memory and user-level agents/skills/commands
    reach = [n for n in CLAUDE_HOME_REACH if (home / n).exists()]
    if reach:
        raise ValueError(f"--claude-home refused: {', '.join(reach)} in {home} would reach every unit; "
                         "use a home with only the login")
    if not (home / ".credentials.json").exists():
        raise ValueError(f"--claude-home refused: no login in {home} (.credentials.json missing; checked by "
                         "existence only; a macOS Keychain login has no such file and is not supported here)")
    return home.resolve()


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    dry = sub.add_parser("plan")
    dry.add_argument("kind", choices=("context", "memory"))
    dry.add_argument("--dry-run", action="store_true", help="explicit spelling; plans are always offline")
    dry.add_argument("--reps", type=int, default=3)
    dry.add_argument("--unit-usd", type=float)
    dry.add_argument("--out", type=Path)
    run = sub.add_parser("execute", help="serial runner; defaults to an offline estimate")
    run.add_argument("kind", choices=("context", "memory"))
    mode = run.add_mutually_exclusive_group()
    mode.add_argument("--run", action="store_true", help="explicitly allow model calls")
    mode.add_argument("--dry-run", action="store_true")
    run.add_argument("--budget", type=float, help="required with --run; context <=4, memory <=3")
    run.add_argument("--unit-budget", type=float, default=0.05, help="maximum reserved USD per invocation")
    run.add_argument("--reps", type=int, default=3)
    run.add_argument("--out", type=Path, help="fresh output directory required with --run")
    run.add_argument("--codex-home", default="", help="a dedicated Codex home you logged in to yourself "
                     "(`CODEX_HOME=<dir> codex login`); required with --run when units run Codex. Only its path is "
                     "passed on: Codex units use it as CODEX_HOME and write their sessions there")
    run.add_argument("--claude-home", default="", help="a dedicated Claude home you logged in to yourself "
                     "(`CLAUDE_CONFIG_DIR=<dir> claude`, then /login); required with --run when units run Claude "
                     "(--agents claude). Checked by existence only; Claude units use it as CLAUDE_CONFIG_DIR")
    run.add_argument("--on-invalid", choices=("stop", "continue"),
                     help="an errored, receipt-error or unknown-cost unit: stop the group (default without --tasks) "
                          "or record it as invalid and go on (default with --tasks; the group still stops on the "
                          f"budget, a unit over its reservation, Ctrl-C, or the {MAX_UNKNOWN_COST_UNITS + 1}th "
                          "unknown-cost unit)")
    for parser in (dry, run):
        parser.add_argument("--tasks", type=Path, help="a frozen new-task file (JSON) instead of the built-in "
                            "tasks; needs --tasks-sha256 (issue #345)")
        parser.add_argument("--tasks-sha256", help="the task file's SHA-256 as recorded in the preregistration; "
                            "a different file is refused")
        parser.add_argument("--agents", type=lambda v: [x.strip() for x in v.split(",") if x.strip()],
                            help=f"comma-separated sub-agents from {', '.join(AGENT_MODELS)} "
                                 "(default: context codex,dsh; memory codex)")
        parser.add_argument("--hide", action="append", default=[], metavar="PATH",
                            help="repeatable (#454): another folder or file every unit's agents must not open, e.g. "
                                 "your everyday relayline checkout when the run uses an independent clone; made "
                                 "absolute against the folder you start in, a missing path is refused. This checkout "
                                 "and its task data are always denied; the plan's isolation field lists every path")
    hook = sub.add_parser("probe-hook")
    hook.add_argument("--hub", required=True, type=Path, help="synthetic hub only")
    hook.add_argument("--cwd", required=True, type=Path)
    hook.add_argument("--as", dest="agent", choices=("codex", "claude"), default="codex")
    a = p.parse_args(argv)
    try:
        if a.cmd == "execute":
            data = plan(a.kind, a.reps, tasks=a.tasks, tasks_sha256=a.tasks_sha256, agents=a.agents, hide=a.hide,
                        out=a.out)
            if a.budget is not None and (not math.isfinite(a.budget) or not 0 < a.budget <= data["cap_usd"]):
                raise ValueError("budget must be positive, finite and within the kind's cap")
            if not math.isfinite(a.unit_budget) or a.unit_budget <= 0:
                raise ValueError("unit budget must be positive and finite")
            if a.tasks is not None and a.unit_budget > FRESH_MAX_UNIT_USD:
                raise ValueError(f"unit budget must be at most {FRESH_MAX_UNIT_USD} with --tasks")
            data.update(budget_usd=a.budget if a.budget is not None else data["cap_usd"],
                        unit_budget_usd=a.unit_budget)
            data["within_budget"] = data["estimated_usd"] <= data["budget_usd"]
            if a.tasks is not None or a.on_invalid:      # absent by default: the old output stays as it was
                data["on_invalid"] = a.on_invalid or ("continue" if a.tasks is not None else "stop")
            if a.run:
                if a.budget is None or a.out is None:
                    raise ValueError("execution requires --run --budget USD --out FRESH_DIRECTORY")
                from strength_runner import execute, needs_codex_home, needs_claude_home
                codex_home = checked_codex_home(a.codex_home) if needs_codex_home(data["units"]) else None
                claude_home = checked_claude_home(a.claude_home) if needs_claude_home(data["units"]) else None
                data = execute(data, a.out, a.budget, a.unit_budget, codex_home, claude_home)
        elif a.cmd == "plan":
            data = plan(a.kind, a.reps, a.unit_usd, tasks=a.tasks, tasks_sha256=a.tasks_sha256, agents=a.agents,
                        hide=a.hide)
        else:
            data = probe_hook(a.hub, a.cwd, a.agent)
    except (ValueError, OSError) as e:
        p.error(str(e))
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    if a.cmd == "plan" and a.out:
        a.out.write_text(text, encoding="utf-8", newline="")
    else:
        print(text, end="")
    if a.cmd == "execute":
        return 2 if data.get("budget_stopped") or (data.get("dry_run") and not data["within_budget"]) else 0
    return (0 if data["within_estimated_cap"] else 2) if a.cmd == "plan" else data["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
