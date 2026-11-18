"""Experimental P4 long sessions. No model call without --run; defaults stay unchanged.

Each episode has four tasks in one persistent Claude conversation per arm. Tasks
are interleaved between arms; the repository is rebuilt at each reference parent.
Hidden scoring happens in a separate directory and is never sent to the lead.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import json
import math
import os
import re
from pathlib import Path
import shutil
import statistics
import sys
import tempfile
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
import r5
import preflight as PF
import ext_repo as E
import evidence_streams as ES
import long_check as LC
import tasks_long as TASKS
import p5_costs as P5
import p5_arms as P5A
import dispatch_eval as DE
import long_environment as LE
from common import ROOT, append_jsonl, read_jsonl

ARMS = ("self", "ccxlong")
N = 4
# Round 2 (#346): frozen task files of any size; invalid rows continue (up to a limit) instead of stopping.
ROUND2 = ("r2b", "r2c")
TASK_FIELDS = ("repo", "commit", "brief", "tests", "code")
WEB_TOOLS = ("WebFetch", "WebSearch")
LIMITATION = "Delegation and one-line acceptance change together; their effects are not separated."
USAGE_COUNTERS = {"input_tokens": "inputTokens", "output_tokens": "outputTokens",
                  "cache_read_input_tokens": "cacheReadInputTokens",
                  "cache_creation_input_tokens": "cacheCreationInputTokens"}
COST_BASIS = "CLI session cumulative total_cost_usd minus previous validated cumulative; modelUsage counters checked against summed per-invocation result.usage"


def finite_cost(value):
    return (float(value) if isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and value >= 0 else None)


@dataclass
class LeadCost:
    """Fail closed for the rest of a session after a missing/inconsistent receipt."""
    cumulative: float = 0.0
    usage: dict = field(default_factory=lambda: dict.fromkeys(USAGE_COUNTERS, 0))
    failed: bool = False

    def observe(self, result: dict, session_match: bool = True) -> dict:
        cumulative = finite_cost(result.get("total_cost_usd"))
        invocation = result.get("usage")
        models = result.get("modelUsage")
        totals = None
        if (isinstance(invocation, dict) and isinstance(models, dict) and models
                and all(isinstance(m, dict) for m in models.values())):
            values = [invocation.get(k) for k in USAGE_COUNTERS]
            values += [m.get(k) for m in models.values() for k in USAGE_COUNTERS.values()]
            if all(type(v) is int and v >= 0 for v in values):
                totals = {k: sum(m[v] for m in models.values()) for k, v in USAGE_COUNTERS.items()}
        expected = ({k: self.usage[k] + invocation[k] for k in USAGE_COUNTERS}
                    if totals is not None else None)
        check = not self.failed and totals is not None and totals == expected
        errors = []
        if self.failed:
            errors.append("previous receipt untrusted; session accounting stopped")
        if cumulative is None:
            errors.append("missing or invalid cumulative cost")
        elif cumulative < self.cumulative:
            errors.append("cumulative cost decreased")
        if not check:
            errors.append("modelUsage counters missing/invalid or differ from summed result.usage")
        if not session_match:
            errors.append("session_id mismatch")
        row = {"lead_cumulative_usd": cumulative, "lead_previous_cumulative_usd": self.cumulative,
               "lead_reported_usd": result.get("total_cost_usd"), "cost_basis": COST_BASIS,
               "lead_result_usage": invocation, "lead_model_usage": totals,
               "cost_cumulative_check": check, "cost_errors": errors,
               "lead_usd": None if errors else cumulative - self.cumulative}
        if errors:
            self.failed = True
        else:
            self.cumulative, self.usage = cumulative, expected
        return row


def pin_matches(requested: str, actual: str) -> bool:
    """Git may report a full SHA or an abbreviation; refuse ambiguous tiny pins."""
    requested, actual = requested.lower(), actual.lower()
    return bool(re.fullmatch(r"[0-9a-f]{7,40}", requested)
                and re.fullmatch(r"[0-9a-f]{7,40}", actual)
                and (requested.startswith(actual) or actual.startswith(requested)))


def pin_refused(requested: str, actual: str) -> bool:
    if not requested or pin_matches(requested, actual):
        return False
    why = "at least 7 hexadecimal characters required" if len(requested) < 7 else "SHA prefixes do not match"
    print(f"P4 --pin-commit refused: requested={requested} actual={actual}; {why}", file=sys.stderr)
    return True


def schedule(tasks: list[dict], rounds: int = 1, arms=ARMS, episode_size: int = N) -> list[dict]:
    """episode_size 1 (#346): each task in its own new lead session, so tasks stay independent."""
    if set(DE.ARMS) & set(arms):
        return DE.schedule(tasks, rounds, arms)
    if episode_size < 1 or len(tasks) % episode_size:
        raise ValueError("episodes must contain exactly four tasks" if episode_size == N
                         else f"task count must be a multiple of the episode size {episode_size}")
    result = []
    for rd in range(1, rounds + 1):
        for ep, start in enumerate(range(0, len(tasks), episode_size), 1):
            group = tasks[start:start + episode_size]
            if len({t["repo"] for t in group}) != 1:
                raise ValueError("an episode must use one repository")
            for turn, task in enumerate(group, 1):
                # Same task order in both arms; alternate who runs first.
                order = (arms if (rd + ep + turn) % 2 else arms[::-1]) if len(arms) == 2 else (
                    arms[(rd+ep+turn) % len(arms):] + arms[:(rd+ep+turn) % len(arms)])
                for arm in order:
                    result.append({"round": rd, "episode": ep, "turn": turn,
                                   "task": task["id"], "arm": arm})
    return result


def estimate(units: list[dict], arms=ARMS, tasks: list[dict] | None = None) -> dict:
    # Historical r5 tasks were about 40 changed code lines. Scale by the
    # frozen task's actual implementation size, not documentation/type stubs.
    details = []
    known = {t["id"]: t for t in tasks or []}
    for u in units:
        task = known.get(u["task"]) or TASKS.by_id(u["task"])
        lines, files = task.get("code_lines", 40), len(task["code"])
        scale = max(1, lines / 40, files / 2)
        base = r5.UNIT_USD["self" if u["arm"] == "self" else "ccx2"]
        base, note = P5A.estimate_base(u["arm"], base)
        details.append({"task": u["task"], "arm": u["arm"], "code_lines": lines, "code_files": files,
                        "size_multiplier": scale, "usd": round(base * scale * 1.5, 6), "basis": note})
    by_arm = {a: round(sum(x["usd"] for x in details if x["arm"] == a), 4)
              for a in dict.fromkeys([*arms, *(u["arm"] for u in units)])}
    return {"usd": round(sum(by_arm.values()), 4), "by_arm": by_arm,
            "tasks": details,
            "method": "r5 means self=$0.20, ccx2=$0.12 x max(1, code_lines/40, code_files/2) x1.5 context; API-equivalent USD",
            "uncertainty": "Unknown: larger external changes and resumed context have not been measured",
            "historical_source": "scripts/eval/r5.py UNIT_USD (r5 tags; ccx2 r5c-r5h)"}


def task_caps(a, arm: str) -> tuple[float, float]:
    legacy = getattr(a, "task_cap", None)
    if legacy is not None:
        return (legacy, 0.0) if arm == "self" else (legacy / 2, legacy / 2)
    if arm == "self" and getattr(a, "self_lead_budget", None) is not None:
        # #346: self's lead cap can equal a ccx arm's lead + delegation caps (equal per-task allowances).
        return float(a.self_lead_budget), 0.0
    return float(getattr(a, "lead_budget", 1.5)), (float(getattr(a, "child_budget", 1.5)) if arm != "self" else 0.0)


def budget_envelope(a) -> dict:
    lead, child = task_caps(a, "ccxlong")
    reserve = max(lead + child, sum(task_caps(a, "self")))
    out = {"budget_usd": a.budget, "lead_allowance_usd": lead, "child_allowance_usd": child,
           "max_task_reservation_usd": reserve, "overrun_allowance_usd": reserve,
           "operational_upper_usd": a.budget + reserve, "absolute_hard_cap": False,
           "basis": "reserve lead+child before each task; allow one final overrun allowance per role; CLI caps are step-boundary checks, not a provider billing guarantee"}
    if getattr(a, "self_lead_budget", None) is not None and getattr(a, "task_cap", None) is None:
        out["self_lead_allowance_usd"] = float(a.self_lead_budget)
    return out


@dataclass
class Budget:
    cap: float
    spent: float = 0.0
    unknown: bool = False

    def reserve(self, amount: float) -> bool:
        return not self.unknown and amount > 0 and self.spent + amount <= self.cap + 1e-9

    def charge(self, amount: float | None) -> None:
        if amount is None or not math.isfinite(amount) or amount < 0:
            self.unknown = True
        else:
            self.spent += amount


def prompt_v2(task: dict, child_cap: float, receipt: Path | None, agent: str) -> str:
    """ccxcheapfirst2 (#346): the shipped #326/#338 delegation guidance, which the evaluation lead does not load as
    a skill: write a test for the new requirement, see it fail, commit it (check.sensitivity needs a clean tree),
    pass it as --check, and give concrete inputs and expected outputs in the brief."""
    ccx = f'python "{(receipt or Path(__file__).with_name("p4_receipt.py")).as_posix()}"'
    return ("The repository has been reset to a different historical parent for this task. "
            "Earlier code changes are intentionally absent; conversation context is preserved. "
            "Implement only the request below. Do not fetch history or packages, or inspect other sessions, "
            "grading files, or evaluation artifacts. Do not change existing tests.\n\n"
            + task["brief"] + "\n\n"
            "Do not edit implementation code yourself. Delegate the work to " + agent.capitalize() + " through ccx, "
            "writing a failing check first:\n"
            "1. Turn the request into at least one new test aimed at the new requirement, in a new file under tests/. "
            "Read only the interface the test needs, not the whole code base.\n"
            "2. Run it with PYTHONPATH=. python -m pytest -q -o addopts= -p no:cacheprovider <that test file> and see it "
            "fail before the change. If it passes, it cannot see the new requirement: fix the test until it fails.\n"
            "3. Commit only that test file (git add <that test file>; git commit -m \"failing check\"), so the tree is "
            "clean when ccx compares the check before and after the change (git status --porcelain must print "
            "nothing). Make no other commit.\n"
            "4. Dispatch with that test as --check. In the brief, state the request with concrete inputs and expected "
            "outputs, and tell the sub-agent not to edit that test. Use the shipped default tradeoff (omit "
            "--tradeoff), review and routing; run synchronously:\n"
            f'{ccx} run --to {agent} --mode write --context auto --new --no-ab --max-usd {child_cap:g} '
            '--check "python -m pytest -q -o addopts= -p no:cacheprovider <that test file>" "<brief>"\n'
            "CCX_LEAD_VIEW=line enables the existing compact receipt. If receipt ok=true, accept that one "
            "line and finish: do not read files, diff, full result, or rerun checks. Only if receipt ok is not "
            "true may you use ccx show <run_id> and ccx resume <run_id> to diagnose or request a repair; "
            "any repair shares the remaining delegation allowance, never increase it. Do not use another "
            "delegation path or run in the background.\nFinish with one line DONE: <summary>.")


def pythonpath(task: dict) -> str:
    """PYTHONPATH for the lead, its sub-agents and the acceptance check: relative (so a ccx worktree uses its own
    tree); a task selected with src_layout (round2_tasks, #364) gets src/ before the root, as it was validated (#365)."""
    return "src" + os.pathsep + "." if task.get("src_layout") else "."


def task_env(env: dict, task: dict, base_utf8: str | None = None) -> dict:
    """The per-task part of an episode's shared environment, set before each task (it reaches the lead, its
    sub-agents and ccx --check): PYTHONPATH (#365), PYTHONUTF8 (#415) and PYTEST_PLUGINS (#424) as the task was
    validated and is scored. A task without pythonutf8 gets the episode's inherited value back, and one without
    pytest_plugins has none, so nothing leaks from the previous task."""
    env["PYTHONPATH"] = pythonpath(task)
    if task.get("pythonutf8") is True:
        env["PYTHONUTF8"] = "1"
    elif base_utf8 is None:
        env.pop("PYTHONUTF8", None)
    else:
        env["PYTHONUTF8"] = base_utf8
    plugins = plugin_env(task)
    if plugins:
        env.update(plugins)
    else:
        env.pop("PYTEST_PLUGINS", None)
    return env


def plugin_env(task: dict) -> dict:
    """PYTEST_PLUGINS for a round-2 task that declares pytest plugins (round2_tasks, #424); autoload stays off."""
    plugins = task.get("pytest_plugins") or ()
    return {"PYTEST_PLUGINS": ",".join(plugins)} if plugins else {}


def prompt(task: dict, arm: str, child_cap: float, receipt: Path | None = None,
           check_command=None, focused=False, child_agent: str = "codex") -> str:
    if not task.get("src_layout"):
        return _prompt(task, arm, child_cap, receipt, check_command, focused, child_agent)
    # Only src-layout tasks change, and only the instructions: the brief (pasted verbatim) is kept out of the
    # replacement. Quoted, since os.pathsep is ";" on Windows and the lead runs a POSIX shell.
    hole = "\x00BRIEF\x00"
    text = _prompt({**task, "brief": hole}, arm, child_cap, receipt, check_command, focused, child_agent)
    return text.replace("PYTHONPATH=.", f"PYTHONPATH='{pythonpath(task)}'").replace(hole, task["brief"])


def _prompt(task: dict, arm: str, child_cap: float, receipt: Path | None,
            check_command, focused, child_agent: str) -> str:
    if arm == DE.ARM2:
        return prompt_v2(task, child_cap, receipt, child_agent)
    common = ("The repository has been reset to a different historical parent for this task. "
              "Earlier code changes are intentionally absent; conversation context is preserved. "
              "Implement only the request below. Do not fetch history or packages, commit, or inspect other "
              "sessions, grading files, or evaluation artifacts. Run relevant existing tests, using "
              "python -m pytest -q -o addopts= with PYTHONPATH=. . Do not change existing tests.\n\n"
              + (P5A.focused_brief(task) if focused and arm != "self" else task["brief"]) + "\n\n")
    if focused and arm != "self":
        common = ("This task starts from a reset historical parent; conversation context persists. "
                  "No downloads, history, commits, other sessions or grading artifacts. Run relevant existing tests "
                  "with PYTHONPATH=.; do not change existing tests.\n\n" + P5A.focused_brief(task) + "\n\n")
    if arm == "self":
        how = "Do all implementation and checking yourself. Do not use Agent, ccx, or another model/CLI."
    else:
        ccx = f'python "{(receipt or Path(__file__).with_name("p4_receipt.py")).as_posix()}"'
        how = ("Do not edit code yourself. Delegate the request verbatim to Codex through ccx. "
               "Use the shipped default tradeoff (omit --tradeoff), review and routing; run synchronously:\n"
               f'{ccx} run --to codex {P5A.initial_model_flags(arm)}--mode write --context auto --new --no-ab '
               f'--max-usd {child_cap:g} --check "python -m pytest -q -o addopts=" "<verbatim request>"\n'
               "CCX_LEAD_VIEW=line enables the existing compact receipt. If receipt ok=true, accept that one "
               "line and finish: do not read files, diff, full result, or rerun checks. Only if receipt ok is not "
               "true may you use ccx show <run_id> and ccx resume <run_id> to diagnose or request a repair; "
               "any repair shares the remaining delegation allowance, never increase it. Do not use another "
               "delegation path or run in the background.")
        if check_command:
            import shlex
            how = how.replace('--check "python -m pytest -q -o addopts="', '--check '+shlex.quote(check_command))
        if focused:
            command = how.split("run synchronously:\n", 1)[1].split("\n", 1)[0]
            how = ("Delegate verbatim; do not implement yourself. Use default tradeoff/review, synchronously:\n"+command+
                   "\nOn receipt ok=true, accept the one line and finish without reading files/diff or rerunning tests. "
                   "Otherwise inspect ccx show or request ccx resume within the remaining child allowance; never raise it, "
                   "use another delegation path or run in background.")
    return common + how + "\nFinish with one line DONE: <summary>."


def lead_argv(unit: PF.Unit, sid: str, turn: int, cap: float) -> list[str]:
    argv = r5.r3.lead_argv("ccx", cap, "sonnet", "medium") + PF.lead_flags(unit)
    return argv + (["--session-id", sid] if turn == 1 else ["--resume", sid])


def telemetry(stream: str) -> dict:
    messages = {}
    for event in PF._events(stream):
        if event.get("type") == "assistant" and not event.get("parent_tool_use_id"):
            message = event.get("message") or {}
            usage = message.get("usage")
            if usage:
                messages[message.get("id") or len(messages)] = usage
    contexts = [sum(int(u.get(k) or 0) for k in ("input_tokens", "cache_read_input_tokens",
                                               "cache_creation_input_tokens")) for u in messages.values()]
    return {"context_tokens": contexts, "context_first": contexts[0] if contexts else None,
            "context_last": contexts[-1] if contexts else None,
            "cache_read_tokens": sum(int(u.get("cache_read_input_tokens") or 0) for u in messages.values()),
            "lead_usage": r5.TL.lead_stream(stream)["usage"]}


def reset_repo(repo: Path, tree: bytes, native=False, caches=False, stubs=(), stub_version=None) -> None:
    # Owned, disposable episode directory only; never git reset the source checkout.
    # `stubs`: the install-time version files a round-2 task was validated with (round2_tasks, #415), reporting
    # its `stub_version` (#424).
    PF.rmtree(repo)
    E.repo_from_tar(tree, {"stubs": list(stubs or ()), "stub_version": stub_version}, repo)
    if native:
        LE.checkout(repo)
    exclude = repo / ".git" / "info" / "exclude"
    with exclude.open("a", encoding="utf-8", newline="") as f:
        f.write("\n/.ccx-eval-tmp-*/\n")
        if caches:
            # ccxcheapfirst2: the lead runs its failing test before dispatching; check.sensitivity needs a clean tree.
            f.write(".pytest_cache/\n__pycache__/\n")


def score(repo: Path, task: dict, material: dict, python: str, native=False) -> dict:
    # The live repo never contains hidden tests or their output. A separate copy
    # also prevents a later --resume from seeing a previous hidden test.
    with tempfile.TemporaryDirectory(prefix="p4-score-") as tmp:
        target = Path(tmp) / "repo"
        shutil.copytree(repo, target, ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache", ".ccx-eval-tmp-*"))
        E.restore_test_setup(target, material["tar"], {"test_dirs": ["tests"]})
        for rel, body in material["tests"].items():
            (target / rel).parent.mkdir(parents=True, exist_ok=True)
            (target / rel).write_bytes(body)
        if native:
            E._git(target, "init", "-q")
            E._git(target, "add", "-A")
            E._git(target, "commit", "-q", "--no-verify", "-m", "score snapshot")
            LE.checkout(target)
        # check_tree extracts a supplied tar; score the already assembled copy.
        return run_hidden(target, task["tests"], python, src_layout=task.get("src_layout") is True,
                          utf8=task.get("pythonutf8") is True, plugins=tuple(task.get("pytest_plugins") or ()))


def run_hidden(repo: Path, tests: list[str], python: str, src_layout: bool = False, utf8: bool = False,
               plugins=()) -> dict:
    # A task that round2_tasks validated with src/ on the path (#364 records src_layout) is scored the same way (#367);
    # likewise one validated with PYTHONUTF8=1 (pythonutf8, #415) and its declared pytest plugins (#424).
    path = (str(repo / "src") + os.pathsep if src_layout else "") + str(repo)
    env = {**PF.base_env(), "PYTHONPATH": path, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
           "PYTHONDONTWRITEBYTECODE": "1", "PIP_NO_INDEX": "1", **({"PYTHONUTF8": "1"} if utf8 else {}),
           **plugin_env({"pytest_plugins": plugins})}
    out, err, rc, _ = PF.run([python, "-m", "pytest", "-q", "-o", "addopts=", "-p", "no:cacheprovider", *tests],
                             cwd=repo, env=env, timeout=180)
    text = out + err
    return {"ok": rc == 0, "rc": rc, "summary": text.strip().splitlines()[-1] if text.strip() else "empty",
            "output": text, "environment_error": rc not in (0, 1)}


def grade_files(a) -> tuple:
    return a.out, a.out.with_suffix(".pending.jsonl"), a.out.with_suffix(".events.jsonl")


def unit_hidden(a, key: str) -> tuple:
    """More folders and files episode `key`'s agents must not open, on top of preflight.forbidden's own list: the
    task cache, this run's evidence, the other episodes' folders, the grade files, and every --hide path (#451:
    another local checkout holding authored tasks' reference solutions and hidden tests)."""
    other_roots = tuple(a.work / (prefix + other) for other in sorted(a.session_keys) if other != key
                        for prefix in ("repo-", "hub-", "x-"))
    return (a.ext_cache, a.artifacts, *other_roots, *grade_files(a), *(getattr(a, "hide", None) or ()))


# With --hide, the audit also flags any tool call naming the authored round-2 task folders, however the path is
# written (relative, from a parent folder, an alias): the agents' own task repositories never contain these names.
HIDE_CONTENT_FLAGS = (r"(?<![a-z0-9_.-])round2_(?:bc|a)(?:_tasks)?(?![a-z0-9_-])",)


def resolve_hide(values) -> list[Path]:
    """--hide paths made absolute against the folder the eval starts in, each in both spellings when they differ:
    as given (absolute(), e.g. a junction or symlink) and with links resolved (resolve()), de-duplicated. Deny rules
    and the audit match the spelling, not the file, so an alias left out would stay readable. A missing path is
    refused: a typo would deny nothing and leave the checkout it meant readable."""
    out: list[Path] = []
    for v in values or ():
        given = Path(v).expanduser().absolute()
        real = given.resolve()
        if not real.exists():
            raise SystemExit(f"--hide {v}: no such file or folder ({real}); no model called")
        for p in (given, real):
            if p not in out:
                out.append(p)
    return out


def check_hide(hide, work: Path | None, python: str | None = None) -> None:
    """Refuse a --hide path that is or holds this checkout (the lead runs its ccx.py; it is denied already), holds
    the run's own work folder (preflight.forbidden drops a folder the work folder is inside, so it would deny
    nothing) or the --ext-python interpreter (every shell call would name a denied path and fail the audit)."""
    for h in hide or ():
        if Path(h).resolve() == ROOT.resolve():
            raise SystemExit(f"--hide {h} is the checkout running this eval, which is denied already; for a counted "
                             "run start from an independent clone and pass this path to it with --hide. "
                             "No model called")
        for what, p in (("the work folder", work), ("this checkout", ROOT), ("--ext-python", python)):
            if p and PF._inside(Path(p), h):
                raise SystemExit(f"--hide {h} holds {what} ({p}); hide the other checkout itself. No model called")


def hide_flags(a) -> tuple:
    """Audit regexes for --hide (empty without it): HIDE_CONTENT_FLAGS, and each hidden folder's parent folders named
    on their own (`rg x D:/parent`, `cd D:/parent`), in canon()'s spelling. A parent holding something the run
    legitimately names (the work folder, this checkout, --ext-python, the task cache, the results, the eval Codex
    home, the person's home) and a drive or filesystem root are left out."""
    hide = getattr(a, "hide", None) or ()
    if not hide:
        return ()
    home = PF.real_paths()["home"]
    used = [Path(p) for p in (getattr(a, "work", None), ROOT, getattr(a, "ext_python", None),
                              getattr(a, "ext_cache", None), getattr(a, "out", None),
                              getattr(a, "codex_home", None) or None, home) if p]
    out = list(HIDE_CONTENT_FLAGS)
    for h in hide:
        for anc in Path(h).parents:
            if anc.parent == anc or any(PF._inside(u, anc) for u in used):
                continue
            rx = re.escape(PF.canon(anc.as_posix(), home).rstrip("/")) + r"/?(?=$|[\s\"'`;|)&,])"
            if rx not in out:
                out.append(rx)
    return tuple(out)


def isolation_plan(a, units: list[dict]) -> dict:
    """What a dry run prints about isolation (#451): the --hide paths and every path the first unit would be denied
    (preflight.forbidden with this run's extra list). Other units differ only in which other episodes' folders they
    deny. Folders made when the run starts are named here as placeholders."""
    from types import SimpleNamespace
    work = Path(a.workdir).resolve() if a.workdir else Path(tempfile.gettempdir()) / "p4-<run id>"
    out = Path(a.out).resolve()
    keys = sorted({f"{u['round']}-{u['episode']}-{u['arm']}" for u in units})
    view = SimpleNamespace(work=work, out=out, session_keys=set(keys), hide=a.hide, ext_python=a.ext_python,
                           codex_home=a.codex_home or None,
                           ext_cache=Path(a.ext_cache).resolve() if a.ext_cache else None,
                           artifacts=out.parent / f"{out.stem}-artifacts" / "<run start>")
    base = {"hide": [str(p) for p in a.hide or ()], "audit_flags": list(hide_flags(view)), "note": ISOLATION_NOTE}
    if not keys:
        return {**base, "unit": None, "forbidden_paths": []}
    key = keys[0]
    u = PF.Unit(key, work, work / ("repo-" + key), work / ("hub-" + key),
                claude=getattr(a, "claude_isolation", "flags"),
                hidden=tuple(p for p in unit_hidden(view, key) if p is not None))
    return {**base, "unit": key, "forbidden_paths": [str(p) for p in PF.forbidden(u)]}


ISOLATION_NOTE = (
    "forbidden_paths: every folder preflight.forbidden gives the first unit (other units also deny the other episodes' "
    "folders; ~/.claude.json, the grade files and, in flags mode, the Claude home's private files are denied on top). "
    "Claude gets Read/Edit deny rules on each. Codex and shell reads are not confined on Windows: the audit (path_hits) "
    "flags a tool call naming one of these folders as an absolute path, in the spellings canon() understands "
    "(either slash, ~, $HOME, %USERPROFILE%, Git Bash /c/..., any case on Windows). It does not recognize a relative "
    "path, an 8.3 short name (e.g. CLAUDE~1), an alias made during the run (junction, symlink, subst) or another "
    "variable; with --hide, audit_flags also flags any mention of the round2_a / round2_bc task folders and a hidden "
    "folder's parent folders named on their own")


class Episode:
    def __init__(self, key: str, a, material: dict, task: dict):
        self.sid = str(uuid.uuid4())
        grades = grade_files(a)
        self.iso = PF.Unit(key, a.work, a.work / ("repo-" + key), a.work / ("hub-" + key),
                           claude=getattr(a, "claude_isolation", "flags"), codex_home=Path(a.codex_home), codex_workspace_tmp=True,
                           hidden=unit_hidden(a, key),
                           # The same settings file reaches ccx's Claude sub-agents (CCX_CLAUDE_SETTINGS).
                           deny=(*WEB_TOOLS, *(f"Read({PF._rule_path(p)})" for p in grades)),
                           flags=(*r5.EXT_FLAGS, r"git\s+(?:fetch|clone|pull)", *hide_flags(a)))
        self.before, self.job = PF.snapshot(), PF.Job()
        self.wall = 0.0
        self.lead_total = 0.0
        self.lead_cost = LeadCost()
        self.child_total = 0.0
        self.review_total = 0.0
        self.run_ids = set()
        self.side_ledger_count = 0
        self.first_context = None
        self.last_context = None
        self.rows = []
        self.streams = []
        self.artifacts = a.artifacts
        self.native = native_checkout(a)
        reset_repo(self.iso.repo, material["tar"], self.native, key.endswith("-" + DE.ARM2), task.get("stubs"),
                   task.get("stub_version"))
        (self.iso.hub / "ccx").mkdir(parents=True)
        self.arm = key.rsplit("-", 1)[-1]
        if self.arm in DE.ARMS:
            DE.configure(self.iso.hub, True, self.arm)
        self.child_agent = child_agent(a, self.arm)
        self.default_rung = first_rung(self.iso.hub, self.child_agent) if self.arm in DE.ARMS else None
        # Fresh hub, shipped settings: unlike r3.make_hub, no model holdbacks.
        self.memory_empty = PF.hub_memory_empty(self.iso.hub)
        # Prepare once per episode. In flags mode native transcripts live in
        # Claude's projects/<slug(repo)>/<sid>.jsonl, outside the reset repo.
        # step() preserves this cwd and home; close() performs session cleanup.
        self.env = {**PF.prepare(self.iso), **E.run_env({"pythonpath": "."}),
                    "CCX_LEAD_VIEW": "line", "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "CCX_P4_ROOT": str(ROOT)}
        self.base_utf8 = self.env.get("PYTHONUTF8")  # restored for a task without pythonutf8 (#415)
        if getattr(a, "focused_retry", False):
            # Only this disposable episode's hub; never modify shipped/user defaults.
            from ccx.config import Paths
            settings = Paths(self.iso.hub).settings
            settings.parent.mkdir(parents=True, exist_ok=True)
            settings.write_text("[defaults]\nfocused_retry = true\n", encoding="utf-8", newline="")
        self.receipt = self.iso.x / "p4_receipt.py"
        shutil.copy2(Path(__file__).with_name("p4_receipt.py"), self.receipt)
        self.python = a.ext_python
        self.env["PATH"] = str(Path(a.ext_python).parent) + os.pathsep + self.env["PATH"]
        if self.native:
            self.env["PYTHONDONTWRITEBYTECODE"] = "1"
        if self.arm == DE.ARM2:
            self.env["PYTHONDONTWRITEBYTECODE"] = "1"   # keep the tree clean for check.sensitivity
        if getattr(a, "codex_web_search", "default") == "disabled":
            # Every Codex exec (sub-agent and reviewer) goes through codex_tmp.py in p4 (codex_workspace_tmp).
            self.env["CCX_EVAL_CODEX_WEB_SEARCH"] = "disabled"

    def step(self, u: dict, task: dict, material: dict, a, cap: float) -> dict:
        reset_repo(self.iso.repo, material["tar"], self.native, self.arm == DE.ARM2, task.get("stubs"),
                   task.get("stub_version"))
        row = {**u, "session_id": self.sid, "reference_commit": task["commit"], "repo": task["repo"],
               "env_clean": False, "ok": None, "usd": None, "cost_complete": False,
               "evidence": getattr(a, "evidence", "not run"),
               "claude_isolation": self.iso.claude,
               "lead_model": "sonnet", "lead_effort": "medium", "tmp_policy": "codex-workspace-private"}
        row["lead_previous_cumulative_usd"] = self.lead_cost.cumulative
        row["focused_retry"] = bool(getattr(a, "focused_retry", False))
        row.update({"lead_cumulative_usd": None, "lead_usd": None,
                    "cost_cumulative_check": False, "cost_basis": COST_BASIS})
        self.rows.append(row)
        lead_cap, child_cap = task_caps(a, u["arm"])
        task_env(self.env, task, self.base_utf8)
        self.env["CCX_P4_CHILD_LIMIT"] = str(child_cap)
        self.env["CCX_P4_CHILD_START"] = str(self.child_total)
        checks_root = self.iso.hub/"ccx"/"check-artifacts"/str(u["turn"])
        self.env["CCX_CHECK_ARTIFACTS"] = str(checks_root)
        if self.native:
            self.env["CCX_P4_CHECK_COMMAND"] = LE.command(self.python)
            check_tmp = self.iso.repo/".ccx-eval-tmp-acceptance"
            check_tmp.mkdir()
            self.env.update({k: str(check_tmp) for k in ("TMP", "TEMP", "TMPDIR")})
        for key in ("CCX_P4_CHILD_MODEL", "CCX_P4_CHILD_EFFORT"):
            self.env.pop(key, None)
        if u["arm"] == P5A.CHEAP:
            self.env.update(CCX_P4_CHILD_MODEL=P5A.MODEL, CCX_P4_CHILD_EFFORT=P5A.EFFORT)
        row.update(checkout_policy=LE.POLICY if self.native else "legacy-lf",
                   focused_context=getattr(a, "focused_context", False))
        if self.native:
            row["checkout_evidence"] = LE.checkout_evidence(self.iso.repo)
        row["budget_envelope"] = budget_envelope(a)
        row.update({"lead_allowance_usd": lead_cap, "child_allowance_usd": child_cap,
                    "reservation_usd": lead_cap + child_cap})
        stream = a.work / f"{self.iso.key}-{u['turn']}.jsonl"
        t0 = time.monotonic()
        out, err, rc, _ = PF.run(lead_argv(self.iso, self.sid, u["turn"], lead_cap),
                                  input=prompt(task, u["arm"], child_cap, self.receipt,
                                               self.env.get("CCX_P4_CHECK_COMMAND"), getattr(a, "focused_context", False),
                                               self.child_agent), cwd=self.iso.repo, env=self.env,
                                  timeout=a.timeout, job=self.job)
        row["wall_s"] = round(time.monotonic() - t0, 3)
        self.wall += row["wall_s"]
        row["episode_wall_s"] = round(self.wall, 3)
        stream.write_text(out, encoding="utf-8", newline="")
        stream.with_suffix(".stderr").write_text(err, encoding="utf-8", newline="")
        self.streams.append((stream, row))
        fin = r5.r3.last_result(out)
        row.update(telemetry(out))
        row["session_match"] = fin.get("session_id") == self.sid
        row.update(self.lead_cost.observe(fin, row["session_match"]))
        lead = row["lead_usd"]
        child = r5.r2.hub_cost(self.iso.hub)
        row.update({"rc": rc, "subtype": fin.get("subtype"), "lead_usd": lead,
                    "ccx_usd": round(child["usd"] - self.child_total, 6),
                    "ccx_review_usd": round(child["review_usd"] - self.review_total, 6),
                    "ccx_run_ids": [rid for rid in child["run_ids"] if rid not in self.run_ids]})
        self.child_total = child["usd"]
        self.review_total = child["review_usd"]
        self.run_ids.update(child["run_ids"])
        ledger = r5.hub_rows(self.iso.hub)
        row["side_ledger"] = [{k: entry[k] for k in
                              ("run_id", "label", "vendor", "model", "rungs", "ae_usd", "dispatch",
                               # #392 handover timings (handover_overhead.py reads them)
                               "startup_seconds", "check_seconds", "check_timing", "review_timing",
                               "review_skipped")
                              if k in entry}
                             for entry in ledger[self.side_ledger_count:] if not entry.get("type")]
        self.side_ledger_count = len(ledger)
        if u["arm"] in DE.ARMS:
            row["dispatch_observed"] = any(e.get("dispatch", {}).get("cheap_first") for e in row["side_ledger"])
        round2 = getattr(a, "max_invalid_rows", None) is not None
        records = []
        if u["arm"] != "self" and (round2 or u["arm"] == DE.ARM2):
            # Sub-agent runs only: a review run's record has no result of its own (as r5.ccx_check_reason).
            records = [rec for rec in (r5.r2.record(self.iso.hub, rid) for rid in row["ccx_run_ids"])
                       if not str(rec.get("label") or "").startswith("review:")]
            # The receipt's status, as ccx builds it (ledger.slim / delegate result): result.status, else "error".
            row["receipt_error"] = any((rec.get("result") or {}).get("status", "error") == "error" for rec in records)
            # ccx --max-usd stop: record["max_usd"] is written only when the cap stopped a step (delegate._capped);
            # p4_receipt refuses a new attempt once the task's child allowance is spent.
            row["child_cap_hit"] = (any(rec.get("kind") == "over_budget" or rec.get("max_usd") for rec in records)
                                    or "child allowance exhausted" in out)
        if u["arm"] == DE.ARM2:
            row["lead_check_commands"] = list(dict.fromkeys(r["check_cmd"] for r in records if r.get("check_cmd")))
            # From the sensitivity receipt: "sensitive" = the check failed before the change.
            row["check_sensitivity"] = [r.get("check_sensitivity") for r in records if "check_sensitivity" in r]
            row["default_first_rung"] = self.default_rung
            row["first_rungs"] = [e["dispatch"].get("first_rung") for e in row["side_ledger"]
                                  if e.get("dispatch", {}).get("cheap_first")]
            row["first_rung_matches_default"] = (all(r == self.default_rung for r in row["first_rungs"])
                                                 if row["first_rungs"] else None)
            row["child_agent"] = self.child_agent
        if round2:
            # Field names unified_summary p4 --paired reads (#347): source stratum, reservation for unknown costs.
            row["source"] = task.get("source")
            row["reserved_usd"] = lead_cap + child_cap
            row["lead_cap_hit"] = fin.get("subtype") == "error_max_budget_usd"
            row["cap_hit"] = row["lead_cap_hit"] or bool(row.get("child_cap_hit"))
            row["timed_out"] = rc == -9
        row.update(P5.costs(row))
        row["known_usd"] = row["ccx_usd"] + (lead or 0)
        if lead is not None:
            row["usd"] = round(lead + row["ccx_usd"], 6)
            row["cost_complete"] = True
            self.lead_total = self.lead_cost.cumulative
        if not row["session_match"]:
            row.update({"cost_complete": False, "usd": None, "environment_error": True})
        row["episode_usd"] = round(self.lead_total + self.child_total, 6) if row["cost_complete"] else None
        if self.first_context is None:
            self.first_context = row["context_first"]
        row["context_growth_tokens"] = (row["context_last"] - self.first_context
                                         if row["context_last"] is not None and self.first_context is not None else None)
        audit = PF.audit(self.iso, out)
        row["audit"] = audit
        redactor = ES.Redactor(self.iso, self.env)
        dest = a.artifacts / f"{self.iso.key}-{u['turn']}"
        dest.mkdir(parents=True)
        row["streams"] = ES.keep(dest / "streams", self.iso, stream, self.env)
        row["checks"] = ES.keep_checks(dest/"checks", checks_root, self.iso, self.env)
        (dest / "stderr.txt").write_text(redactor.text(err), encoding="utf-8", newline="")
        diff = r5.final_diff(self.iso.repo)
        if diff is not None:
            (dest / "diff.patch").write_text(redactor.text(diff), encoding="utf-8", newline="")
        # No raw stream from another arm remains next to its live workspace.
        stream.unlink(missing_ok=True)
        stream.with_suffix(".stderr").unlink(missing_ok=True)
        scoring_start = time.monotonic()
        sc = (score(self.iso.repo, task, material, self.python, True) if self.native else
              score(self.iso.repo, task, material, self.python))
        if round2 and sc["rc"] == 2:
            # Round 2 (#346): hidden tests that fail to import/collect (e.g. the arm never added the function) are the
            # arm's own failure, a valid ok=False row; the task set checks they collect on the reference (#348).
            sc = {**sc, "environment_error": False}
            row["score_collection_error"] = True
        row.update({"ok": sc["ok"], "pytest": sc["summary"], "score_rc": sc["rc"],
                    "environment_error": sc["environment_error"] or not row["session_match"],
                    "score_wall_s": time.monotonic() - scoring_start})
        (dest / "hidden.txt").write_text(redactor.text(sc["output"]), encoding="utf-8", newline="")
        return row

    def close(self, rep: dict, between: list[str]) -> None:
        # An interrupted lead can leave completed host checks before step() exports them.
        for row in self.rows:
            if "checks" not in row:
                dest = self.artifacts/f"{self.iso.key}-{row['turn']}"/"checks"
                source = self.iso.hub/"ccx"/"check-artifacts"/str(row["turn"])
                try:
                    row["checks"] = ES.keep_checks(dest, source, self.iso, self.env)
                except (OSError, ValueError) as exc:
                    row["checks"] = {"status": "Unknown", "error": type(exc).__name__}
        cleanup = PF.after_unit(self.iso, self.before, self.job, [self.sid], keep_repo=False)
        for row in self.rows:
            row.update({"leftovers": cleanup, "hub": {"memory_empty": self.memory_empty},
                        "between_units": between, "fingerprint": PF.fingerprint(rep, self.iso, self.env),
                        "pinned_commit": rep["commit"]})
            row["env_clean"] = PF.env_clean(row, rep) and not row.get("environment_error", False)
        for stream, _ in self.streams:
            stream.unlink(missing_ok=True)
            stream.with_suffix(".stderr").unlink(missing_ok=True)


def _ratio(numerator, denominator):
    return {"numerator": numerator, "denominator": denominator,
            "ratio": numerator / denominator if numerator is not None and denominator else None}


def arm_summary(rs: list[dict]) -> dict:
    """Read-only per-arm statistics, also used by the unified offline summary."""
    wall = [r["wall_s"] for r in rs if r.get("wall_s") is not None]
    result = {"attempted": len(rs), "right": sum(r.get("ok") is True for r in rs),
              "cost_known_usd": round(sum(r.get("usd") if r.get("usd") is not None else
                                           r.get("known_usd", 0) for r in rs), 6),
              "cost_unknown": sum(not r.get("cost_complete") for r in rs),
              "wall_median_s": statistics.median(wall) if wall else None,
              "wall_total_s": sum(wall), "episodes": {}}
    result.update(P5.aggregate(rs))
    groups = {}
    for r in rs:
        groups.setdefault((r.get("tag"), r["round"], r["episode"]), []).append(r)
    result["episodes"] = {"/".join(map(str, k)): {"tasks": len(v), "right": sum(x.get("ok") is True for x in v),
                                  "usd": sum(x.get("usd") or 0 for x in v),
                                  "wall_s": sum(x.get("wall_s") or 0 for x in v)} for k, v in groups.items()}
    return result


def summary(rows: list[dict], expected: int, limits: dict | None = None, gates: str = "p4",
            max_escalation_rate=.3) -> dict:
    evidence = {r.get("evidence", "not run") for r in rows}
    result = {"evidence": next(iter(evidence)) if len(evidence) == 1 else "not run",
              "limitation": LIMITATION}
    result["budget_envelope"] = limits or next((r["budget_envelope"] for r in rows if r.get("budget_envelope")), None)
    for name, subset in (("all", rows), ("env_clean", [r for r in rows if r.get("env_clean") is True])):
        arms = {}
        for arm in dict.fromkeys([*ARMS, *(r["arm"] for r in subset)]):
            rs = [r for r in subset if r["arm"] == arm]
            arms[arm] = arm_summary(rs)
        s, c = arms["self"], arms["ccxlong"]
        ratios = {"cost": _ratio(c["cost_known_usd"], s["cost_known_usd"]),
                  "right": _ratio(c["right"], s["right"]),
                  "wall_median": _ratio(c["wall_median_s"], s["wall_median_s"])}
        complete = all(arms[a]["attempted"] == expected and not arms[a]["cost_unknown"] for a in ARMS)
        # Paired identity, not only equal denominators.
        keys = [{(r.get("tag"), r["round"], r["episode"], r["task"]) for r in subset if r["arm"] == a} for a in ARMS]
        complete = complete and keys[0] == keys[1] and len(keys[0]) == expected
        complete = complete and ratios["cost"]["ratio"] is not None and ratios["wall_median"]["ratio"] is not None
        vals = {"cost": ratios["cost"]["ratio"] is not None and ratios["cost"]["ratio"] <= .8,
                "right": c["right"] >= s["right"],
                "wall_median": ratios["wall_median"]["ratio"] is not None and ratios["wall_median"]["ratio"] <= 2}
        verdict = "Unknown" if not complete or any(r.get("environment_error") for r in subset) else (
            "Pass" if all(vals.values()) else "Fail")
        result[name] = {"arms": arms, "ratios": ratios, "thresholds": {"cost": .8, "right": "ccxlong >= self", "wall_median": 2},
                        "expected_per_arm": expected, "verdict": verdict}
    if gates == "p5":
        result["p5"] = P5.gates(rows, expected)
        result["p5_candidates"] = {arm: P5.gates([r for r in rows if r.get("arm") in ("self", arm)],
                                                 expected, candidate=arm)
                                   for arm in ("ccxlong", P5A.CHEAP)}
        result["p5_arms"] = {arm: P5.arm_summary([r for r in rows if r.get("arm") == arm])
                             for arm in P5A.ARMS}
    if any(r.get("arm") == DE.ARM for r in rows):
        result["dispatch"] = DE.comparison(rows, expected)
    if any(r.get("arm") == DE.ARM2 for r in rows):
        # Escalation rate always recorded (metrics); the verdict is the round-1 point rule, the preregistered
        # round-2 analysis is unified_summary's.
        result["dispatch2"] = DE.comparison(rows, expected, DE.ARM2, max_escalation_rate)
    if any("invalid_reason" in r for r in rows):
        reasons = [r.get("invalid_reason") for r in rows]
        result["invalid_rows"] = {"total": sum(x is not None for x in reasons),
                                  "by_reason": {x: reasons.count(x) for x in sorted(set(filter(None, reasons)))},
                                  "cap_hit_by_arm": {arm: sum(bool(r.get("cap_hit")) for r in rows if r.get("arm") == arm)
                                                     for arm in dict.fromkeys(r.get("arm") for r in rows)}}
    return result


def recompute_rows(rows: list[dict], artifacts: Path | None = None) -> list[dict]:
    """Read-only replay; legacy receipts require an explicit artifact run directory."""
    states, turns, totals, corrected = {}, {}, {}, []
    for original in rows:
        row = dict(original)
        key = tuple(row.get(k) for k in ("tag", "round", "episode", "arm", "session_id"))
        state = states.setdefault(key, LeadCost())
        if row.get("turn") != turns.get(key, 0) + 1:
            state.failed = True
        turns[key] = row.get("turn")
        fin = {}
        if artifacts is not None:
            root = artifacts.resolve()
            stream = (root / row.get("streams", {}).get("dir", "") / "streams" / "lead.jsonl").resolve()
            if stream.is_relative_to(root) and stream.is_file():
                fin = r5.r3.last_result(stream.read_text(encoding="utf-8"))
        elif "lead_cumulative_usd" in row:
            # New rows contain all four normalized counters, so replay needs no streams.
            usage = row.get("lead_model_usage") or {}
            fin = {"total_cost_usd": row.get("lead_cumulative_usd"),
                   "usage": row.get("lead_result_usage"), "session_id": row.get("session_id"),
                   "modelUsage": {"all": {v: usage.get(k) for k, v in USAGE_COUNTERS.items()}}}
        row.update(state.observe(fin, bool(row.get("session_id")) and fin.get("session_id") == row.get("session_id")))
        child = finite_cost(row.get("ccx_usd"))
        lead = row["lead_usd"]
        # Preserve an original interrupted/error receipt's accounting uncertainty.
        row["cost_complete"] = lead is not None and child is not None and original.get("cost_complete") is True
        row["known_usd"] = (lead or 0) + (child or 0)
        row["usd"] = round(row["known_usd"], 6) if row["cost_complete"] else None
        totals[key] = totals.get(key, 0) + row["known_usd"]
        row["episode_usd"] = round(totals[key], 6) if row["cost_complete"] else None
        if not row["cost_complete"]:
            state.failed = True
        row.update(P5.costs(row))
        corrected.append(row)
    return corrected


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    action = p.add_mutually_exclusive_group()
    action.add_argument("--run", action="store_true")
    action.add_argument("--dry-run", action="store_true")
    action.add_argument("--summary", action="store_true")
    action.add_argument("--recompute", type=Path, help="read-only cost correction of an existing results.jsonl; no model calls")
    action.add_argument("--validate-native", action="store_true", help="offline parent full-suite and hidden parent/reference audit; no model calls")
    p.add_argument("--audit-output", type=Path, help="optional JSON output for --validate-native")
    p.add_argument("--native-checkout", action="store_true", help="experimental, default off except p5: native Git EOL checkout plus baseline gate")
    p.add_argument("--focused-retry", action="store_true", help="experimental, default off: enable existing defaults.focused_retry in each isolated ccx hub")
    p.add_argument("--artifacts-root", type=Path, help="explicit artifact run directory for legacy --recompute receipts")
    p.add_argument("--split", choices=("dev", "final", "all", "p5", "dispatch", *ROUND2), default="all",
                   help="r2b / r2c (round 2, #346): tasks from --tasks-file, checked against --tasks-sha256")
    p.add_argument("--tasks-file", type=Path, help="r2b/r2c only: frozen selection JSON {\"accepted\": [...]}, any number of tasks")
    p.add_argument("--tasks-sha256", help="r2b/r2c only: required SHA-256 of --tasks-file")
    p.add_argument("--max-tasks", type=int, help="optional: refuse a task file with more tasks than this")
    p.add_argument("--gates", choices=("p4", "p5"), default="p4", help="opt-in Stage 5 gates; Stage 4 verdicts unchanged")
    p.add_argument("--arms", default=",".join(ARMS), help="opt-in ccxlongcheap / ccxcheapfirst / ccxcheapfirst2; defaults remain self,ccxlong")
    p.add_argument("--child-agent", choices=("claude", "codex"),
                   help="ccxcheapfirst2 only: sub-agent it delegates to (default claude); other ccx arms keep codex")
    p.add_argument("--episode-size", type=int, default=N,
                   help="tasks per lead session (default 4); 1 gives every task its own new session (cheap-first arms always 1)")
    p.add_argument("--self-lead-budget", type=float, default=None,
                   help="self arm's Claude --max-budget-usd per task (default: --lead-budget); set it to lead + child budget for equal caps")
    p.add_argument("--max-escalation-rate", default="0.3",
                   help="stop a cheap-first group when its escalation rate exceeds this (default 0.3); 'none' never stops on it; always recorded")
    p.add_argument("--max-invalid-rows", type=int, default=None,
                   help="keep invalid rows and continue until more than N cost-unknown or N no-dispatch-evidence rows "
                        "(default 3 for r2b/r2c, else round-1 rules: the first stops)")
    p.add_argument("--codex-web-search", choices=("default", "disabled"), default=None,
                   help="'disabled' adds -c web_search=\"disabled\" to every Codex exec (default: disabled for r2b/r2c, else Codex's default)")
    p.add_argument("--max-operational-usd", type=float, default=None,
                   help="optional: refuse a --run whose operational envelope (budget + one reservation) exceeds this")
    p.add_argument("--focused-context", action="store_true", help="experimental, default off: concise delegated brief and implementation file pointers; use a separate tag")
    p.add_argument("--rounds", type=int, default=1)
    p.add_argument("--budget", type=float, default=None, help="must be explicit with --run; dry-run defaults to $12")
    p.add_argument("--lead-budget", type=float, default=1.5, help="Claude --max-budget-usd for each resumed invocation")
    p.add_argument("--child-budget", type=float, default=1.5, help="ccx --max-usd per task, including review and repairs")
    p.add_argument("--task-cap", type=float, default=None, help="legacy total task allowance; overrides lead/child split when explicitly supplied")
    p.add_argument("--pin-commit", default="")
    p.add_argument("--wait-quiet", type=float, default=0)
    p.add_argument("--tag", default="p4")
    p.add_argument("--out", type=Path, default=ROOT / ".ccx" / "eval" / "p4" / "results.jsonl")
    p.add_argument("--workdir", type=Path)
    p.add_argument("--ext-cache", type=Path)
    p.add_argument("--ext-python", default=sys.executable)
    p.add_argument("--timeout", type=int, default=1200)
    p.add_argument("--hide", action="append", default=[], metavar="PATH",
                   help="repeatable (#451): another folder every unit's agents must not open, e.g. your everyday "
                        "relayline checkout when this run uses an independent clone (it holds authored tasks' "
                        "reference solutions and hidden tests); made absolute against the folder you start in. "
                        "The dry-run's isolation field lists every denied path")
    PF.add_options(p)
    p.set_defaults(claude_isolation="flags", codex_workspace_tmp=True)
    return p


def resolve_options(a) -> None:
    """#346 options: refuse combinations that would silently mean something else, fill split-dependent defaults."""
    round2 = a.split in ROUND2
    if round2 and (not a.tasks_file or not a.tasks_sha256):
        raise SystemExit(f"--split {a.split} requires --tasks-file and --tasks-sha256; no model called")
    if not round2 and (a.tasks_file or a.tasks_sha256):
        raise SystemExit("--tasks-file / --tasks-sha256 are only for --split r2b / r2c; no model called")
    raw = str(a.max_escalation_rate).strip().lower()
    try:
        a.max_escalation_rate = None if raw == "none" else float(raw)
    except ValueError:
        raise SystemExit("--max-escalation-rate must be a number in [0, 1] or none") from None
    if a.max_escalation_rate is not None and not 0 <= a.max_escalation_rate <= 1:
        raise SystemExit("--max-escalation-rate must be a number in [0, 1] or none")
    if a.max_invalid_rows is None and round2:
        a.max_invalid_rows = 3
    if a.max_invalid_rows is not None and a.max_invalid_rows < 0:
        raise SystemExit("--max-invalid-rows must be >= 0")
    if a.codex_web_search is None:
        a.codex_web_search = "disabled" if round2 else "default"
    if a.episode_size < 1 or (a.max_tasks is not None and a.max_tasks < 1):
        raise SystemExit("--episode-size and --max-tasks must be positive")
    if a.self_lead_budget is not None and (not math.isfinite(a.self_lead_budget) or a.self_lead_budget <= 0):
        raise SystemExit("--self-lead-budget must be positive")


def main(argv=None) -> int:
    a = parser().parse_args(argv)
    resolve_options(a)
    a.hide = resolve_hide(a.hide)
    check_hide(a.hide, Path(a.workdir).resolve() if a.workdir else None, a.ext_python)
    if a.validate_native:
        if not native_checkout(a) or not a.ext_cache:
            raise SystemExit("--validate-native requires --native-checkout (or --split p5) and --ext-cache; no model called")
        tasks = load_tasks(a)
        if not tasks:
            raise SystemExit("empty native validation is Unknown; no model called")
        audit = LE.audit(tasks, a.ext_cache, a.ext_python)
        audit.update(status="Fail" if audit["excluded"] else "Pass", models_called=False)
        if a.audit_output:
            a.audit_output.parent.mkdir(parents=True, exist_ok=True)
            a.audit_output.write_text(json.dumps(audit, indent=2)+"\n", encoding="utf-8", newline="")
        print(json.dumps(audit, indent=2))
        return 1 if audit["excluded"] else 0
    if a.recompute:
        rows = recompute_rows(read_jsonl(a.recompute), a.artifacts_root)
        selected = [r for r in rows if r.get("tag") == a.tag and
                    (a.split == "all" or r.get("task") in {t["id"] for t in load_tasks(a)})]
        if a.split in ROUND2:
            a.task_count = len(load_tasks(a))
        print(json.dumps({"rows": selected, "summary": summary(selected, expected_count(a), gates=a.gates,
                                                               max_escalation_rate=a.max_escalation_rate)}, indent=2))
        return 0
    explicit_budget = a.budget is not None
    a.budget = (8.0 if a.split == "dispatch" else 12.0) if a.budget is None else a.budget
    if a.run and not explicit_budget:
        raise SystemExit("--run requires explicit --budget; this is a bounded step budget, not an absolute hard cap. No model was called.")
    if (not math.isfinite(a.budget) or a.budget <= 0
            or any(not math.isfinite(x) or x <= 0 for x in (a.lead_budget, a.child_budget))
            or (a.task_cap is not None and (not math.isfinite(a.task_cap) or a.task_cap <= 0))
            or a.rounds < 1 or not math.isfinite(a.wait_quiet) or a.wait_quiet < 0):
        raise SystemExit("budget, task-cap and rounds must be positive; wait-quiet must be finite and nonnegative")
    tasks = load_tasks(a)
    a.task_count = len(tasks)
    if a.max_tasks is not None and len(tasks) > a.max_tasks:
        raise SystemExit(f"{len(tasks)} tasks exceed --max-tasks {a.max_tasks}; no model called")
    arms = tuple(a.arms.split(","))
    if len(set(arms)) != len(arms) or not arms or set(arms)-set((*P5A.ARMS, *DE.ARMS)):
        raise SystemExit("unknown or duplicate arm")
    if a.split == "dispatch" or DE.ARM in arms:
        if a.split != "dispatch" or set(arms) != {"self", DE.ARM} or a.rounds != 1 or a.budget > 8:
            raise SystemExit("cheap-first requires --split dispatch --arms self,ccxcheapfirst --rounds 1 and budget <= $8")
        if a.run and budget_envelope(a)["operational_upper_usd"] > 8:
            raise SystemExit("cheap-first operational budget envelope must be <= $8; reduce budget/task allowances; no model called")
    if DE.ARM2 in arms:
        if a.split not in ROUND2 or set(arms) != {"self", DE.ARM2}:
            raise SystemExit("ccxcheapfirst2 requires --split r2b/r2c and --arms self,ccxcheapfirst2; no model called")
        if native_checkout(a):
            # The native acceptance command would replace the lead's own failing check (p4_receipt pins --check).
            raise SystemExit("ccxcheapfirst2 cannot use --native-checkout: the lead's own --check must reach ccx")
        if a.focused_retry or a.focused_context:
            # focused_retry rewrites the hub settings (dropping cheap_first/sensitivity); focused_context has no v2 prompt.
            raise SystemExit("ccxcheapfirst2 cannot use --focused-retry or --focused-context; no model called")
    elif a.child_agent:
        raise SystemExit("--child-agent applies only to the ccxcheapfirst2 arm; other ccx arms keep codex")
    if set(DE.ARMS) & set(arms) and a.episode_size != N:
        raise SystemExit("cheap-first arms always run one task per session; drop --episode-size")
    if a.run and a.max_operational_usd is not None and budget_envelope(a)["operational_upper_usd"] > a.max_operational_usd:
        raise SystemExit(f"operational budget envelope exceeds --max-operational-usd {a.max_operational_usd:g}; no model called")
    try:
        units = schedule(tasks, a.rounds, arms, a.episode_size)
    except ValueError as exc:
        raise SystemExit(f"{exc}; no model called") from None
    previous = [r for r in read_jsonl(a.out) if r.get("tag") == a.tag]
    if a.summary:
        ids = {t["id"] for t in tasks}
        selected = [r for r in previous if r.get("task") in ids]
        limits = budget_envelope(a) if explicit_budget or not selected else None
        print(json.dumps(summary(selected, expected_count(a), limits, a.gates, a.max_escalation_rate), indent=2))
        return 0
    head = r5.git(ROOT, "rev-parse", "HEAD").strip()
    if pin_refused(a.pin_commit, head):
        return 2
    if previous:
        raise SystemExit("tag already has attempts; use a new tag (never silently restart a lost long session)")
    plan = {"units": units, "estimate": estimate(units, arms, tasks), "budget_usd": a.budget,
            "budget_envelope": budget_envelope(a), "available_tasks": len(tasks), "target_tasks": expected_count(a) // a.rounds,
            "pinned_commit": head, "tasks_sha256": PF.sha256_file(Path(TASKS.__file__)),
            "selection_sha256": PF.sha256_file(TASKS.P5_SELECTION_FILE if a.split == "p5" else TASKS.SELECTION_FILE),
            "claude_isolation": a.claude_isolation,
            "arms": arms, "focused_context": a.focused_context, "focused_retry": a.focused_retry,
            "checkout_policy": LE.POLICY if native_checkout(a) else "legacy-lf",
            "cli_checked": "Claude Code 2.1.316 --help (2026-11-04): --session-id, --resume, -p; cumulative result cost observed in retained development streams; --max-budget-usd resume scope Unknown",
            "limitation": LIMITATION, "run": a.run,
            "budget_semantics": "before a task: spent + lead allowance + child allowance <= budget; unknown accounting stops; operational overrun envelope is not an absolute provider hard cap; Claude Code 2.1.316 --help: --max-budget-usd resume scope (invocation vs session) Unknown"}
    if DE.ARM in arms:
        plan["dispatch"] = {"cheap_first": True, "tasks": 6, "selection": "first six validated P4 tasks in frozen order; reused dev/final, not unseen",
                            "stop_escalation_rate_above": a.max_escalation_rate, "maximum_operational_envelope_usd": 8,
                            "evidence": "not run", "policy": "independent check only; check.baseline on_fail; new failures only"}
    if a.split in ROUND2:
        digest = PF.sha256_file(Path(a.tasks_file))
        plan.update(tasks_file=str(a.tasks_file), tasks_file_sha256=digest, selection_sha256=digest,
                    src_layout_tasks=sum(t.get("src_layout") is True for t in tasks))
    if a.split in ROUND2 or set(DE.ARMS) & set(arms):
        plan.update(plan_settings(a, arms))
    if a.split in ROUND2 or a.hide:
        plan["isolation"] = isolation_plan(a, units)
    if a.split == "p5" and len(tasks) != 8:
        plan["selection_status"] = "Unknown: incomplete eligible episodes; selected estimate is not a full experiment price"
        if len(TASKS.P5_AUDITED_T) == 8:
            plan["audited_estimate"] = {**estimate(schedule(TASKS.P5_AUDITED_T, a.rounds, arms), arms),
                                        "eligibility": "not runnable; original eight audited tasks, hypothetical planning only"}
    print(json.dumps(plan, indent=2), flush=True)
    if not a.run:
        return 0
    if a.split == "p5" and len(tasks) != 8:
        raise SystemExit(f"P5 selection incomplete: {len(tasks)}/8 tasks; no model called")
    a.evidence = "measured"
    return run_experiment(a, tasks, units)


def selected_tasks(split):
    if split == "dispatch":
        return list(TASKS.T[:6])
    return list(TASKS.P5_T) if split == "p5" else [t for t in TASKS.T if split == "all" or t["split"] == split]


def load_task_file(path: Path, sha256: str, split: str) -> list[dict]:
    """A frozen round-2 selection (#346): {"accepted": [{repo, commit, brief, tests, code, ...}]}, any count, its
    SHA-256 given on the command line and checked before anything else reads it."""
    data = Path(path).read_bytes()
    import hashlib
    actual = hashlib.sha256(data).hexdigest()
    if not re.fullmatch(r"[0-9a-f]{64}", (sha256 or "").lower()) or actual != sha256.lower():
        raise SystemExit(f"--tasks-file SHA-256 mismatch: expected {sha256} actual {actual}; no model called")
    try:
        rows = json.loads(data.decode("utf-8"))["accepted"]
    except (ValueError, KeyError, TypeError) as exc:
        raise SystemExit(f"--tasks-file has no accepted task list: {exc}; no model called") from None
    tasks = []
    for i, row in enumerate(rows):
        missing = [k for k in TASK_FIELDS if not row.get(k)]
        if (missing or not re.fullmatch(r"[0-9a-f]{40}", str(row.get("commit", "")))
                or not isinstance(row["tests"], list) or not isinstance(row["code"], list)):
            raise SystemExit(f"--tasks-file task {i}: needs {', '.join(TASK_FIELDS)} (full 40-hex commit, list tests/code); "
                             f"missing {missing}; no model called")
        tasks.append({**row, "id": row.get("id") or f"{split}-{row['commit'][:12]}", "split": split})
    if not tasks or len({t["id"] for t in tasks}) != len(tasks):
        raise SystemExit("--tasks-file needs at least one task and unique ids; no model called")
    return tasks


def load_tasks(a) -> list[dict]:
    if getattr(a, "split", None) in ROUND2:
        return load_task_file(a.tasks_file, a.tasks_sha256, a.split)
    return selected_tasks(a.split)


def child_agent(a, arm: str) -> str | None:
    """Only ccxcheapfirst2 chooses its sub-agent (default Claude, #346); every other ccx arm keeps Codex."""
    if arm == "self":
        return None
    return (getattr(a, "child_agent", None) or "claude") if arm == DE.ARM2 else "codex"


def arm_config(arm: str) -> dict:
    """The configuration a fresh episode hub of this arm loads (shipped defaults plus its settings)."""
    from ccx.config import Paths, load_config
    with tempfile.TemporaryDirectory(prefix="p4-arm-") as tmp:
        hub = Path(tmp)
        (hub / "ccx").mkdir()
        if arm in DE.ARMS:
            DE.configure(hub, True, arm)
        return load_config(Paths(hub))


def first_rung(hub_or_cfg, agent: str) -> str:
    """The rung ccx's cheap-first dispatch starts on: dispatch.prepare uses tier_spec(cfg, "T1", agent)."""
    from ccx.config import Paths, load_config, tier_spec
    cfg = hub_or_cfg if isinstance(hub_or_cfg, dict) else load_config(Paths(Path(hub_or_cfg)))
    spec = tier_spec(cfg, "T1", agent)
    return f"{agent}:{spec['model']}:{spec['effort']}"


def reviewer_rungs(cfg: dict, agent: str) -> list[str]:
    """Review candidates ccx tries first for this worker, assuming Claude Code and Codex are both installed and ready
    (readiness is not probed in a dry run; routing's learned pick, tried after these, is not included)."""
    from ccx import review
    cfg = {**cfg, "routing": {**(cfg.get("routing") or {}), "require_ready": False}}
    return [":".join(r) for r in review.reviewers(cfg, agent, lambda name: name in ("claude", "codex"), cheapest=True)]


def plan_settings(a, arms) -> dict:
    """What a dry run prints for round-2 and cheap-first plans (#346): effective settings per arm, the default first
    rung, reviewers, network and stop rules, so the report copies them from here instead of from memory."""
    out = {"arm_settings": {}, "default_first_rung": {}, "reviewers": {}}
    for arm in arms:
        cfg = arm_config(arm)
        agent = child_agent(a, arm)
        lead, child = task_caps(a, arm)
        out["arm_settings"][arm] = {
            "cheap_first": (cfg.get("dispatch") or {}).get("cheap_first") is True,
            "check_sensitivity": (cfg.get("check") or {}).get("sensitivity", "off"),
            "child_agent": agent, "lead_budget_usd": lead, "child_budget_usd": child,
            "lead_prompt": "failing-check-first (#326/#338)" if arm == DE.ARM2 else "p4 legacy"}
        if agent:
            out["reviewers"][arm] = reviewer_rungs(cfg, agent)
        if arm in DE.ARMS:
            rung = first_rung(cfg, agent)
            _, model, effort = rung.split(":", 2)
            from ccx.config import tier_spec
            asked = tier_spec(cfg, "T2", agent)
            out["default_first_rung"][arm] = {"agent": agent, "model": model, "effort": effort, "rung": rung,
                                              "source": "ccx.config.tier_spec(T1) on this arm's fresh hub (dispatch.prepare)",
                                              "requested_rung": f"{agent}:{asked['model']}:{asked['effort']}",
                                              "requested_source": "Request default tier T2; routing may pick another at "
                                                                  "run time, the ledger's dispatch.requested_rung is authoritative"}
    web = getattr(a, "codex_web_search", "default")
    out["network"] = {"lead_deny": list(WEB_TOOLS), "claude_subagent_deny": list(WEB_TOOLS),
                      "claude_subagent_basis": "CCX_CLAUDE_SETTINGS = the unit's settings file, same deny list as the lead",
                      "codex_web_search": web,
                      "codex_flag": '-c web_search="disabled" on every codex exec via codex_tmp.py' if web == "disabled"
                      else "none added (Codex default; ccx adds it only with lean tools)"}
    rate = getattr(a, "max_escalation_rate", .3)
    limit = getattr(a, "max_invalid_rows", None)
    out["stop_rules"] = {"max_escalation_rate": rate, "max_invalid_rows": limit,
                         "invalid_row": ("environment error, receipt status error, cost unknown, or missing dispatch evidence "
                                         "(kept, group continues); an arm's own timeout, cap or hidden-test collection error "
                                         "with known cost is a valid row with ok=false" if limit is not None else
                                         "round-1 rules: the first error, cost-unknown row or missing dispatch evidence stops the group"),
                         "unknown_cost": ("charged at the task reservation; the group stops past max_invalid_rows such rows"
                                          if limit is not None else "stops the group (round-1 rule)")}
    out["episode_size"] = 1 if set(DE.ARMS) & set(arms) else getattr(a, "episode_size", N)
    return out


def invalid_reason(row: dict) -> str | None:
    """Round-2 invalid rows (#346): kept and counted; the group continues until a limit is passed."""
    if row.get("receipt_error"):
        return "receipt_error"
    if not row.get("cost_complete"):
        return "cost_unknown"
    if row.get("environment_error"):
        return "environment_error"
    if row.get("arm") in DE.ARMS:
        if row.get("dispatch_observed") is not True:
            return "dispatch_evidence_unknown"
        if DE.metrics([row], row["arm"])["first_usd"] is None or DE.metrics([row], row["arm"])["escalation_usd"] is None:
            return "dispatch_cost_unknown"
    return None


def native_checkout(a):
    return getattr(a, "split", None) == "p5" or bool(getattr(a, "native_checkout", False))


def expected_count(a, fallback: int = 0) -> int:
    split = getattr(a, "split", None)
    if split in ROUND2:
        return getattr(a, "task_count", fallback) * a.rounds
    return {"dev": 4, "final": 8, "all": 12, "p5": 8, "dispatch": 6}[split] * a.rounds if split else fallback


def run_experiment(a, tasks: list[dict], units: list[dict]) -> int:
    """Execution engine; only the explicit --run --budget CLI path invokes it."""
    if not a.ext_cache or not a.codex_home:
        raise ValueError("--ext-cache and a dedicated --codex-home are required")
    a.work = (a.workdir or Path(tempfile.gettempdir()) / ("p4-" + uuid.uuid4().hex)).resolve()
    check_hide(getattr(a, "hide", None), a.work, a.ext_python)
    a.out = a.out.resolve()
    a.session_keys = {f"{u['round']}-{u['episode']}-{u['arm']}" for u in units}
    _, a.artifacts = r5.run_artifacts_dir(a.out)
    budget = Budget(a.budget)
    for previous in read_jsonl(a.out):
        budget.charge(previous.get("usd"))
        if previous.get("usd") is None:
            budget.spent += previous.get("known_usd", 0)
    # Read only the explicit bare clones before any model starts, keep solutions
    # in evaluator memory, and deny that cache to the agents.
    materials = {t["id"]: LC.material(a.ext_cache, t) for t in tasks}
    if native_checkout(a):
        # Fail before canaries/models if the exact parent acceptance baseline is broken.
        a.artifacts.mkdir(parents=True, exist_ok=True)
        audit = LE.audit(tasks, a.ext_cache, a.ext_python, a.artifacts/"baseline")
        (a.artifacts/"baseline.json").write_text(json.dumps(audit, indent=2)+"\n", encoding="utf-8", newline="")
        if audit["excluded"]:
            print("Native baseline/reference validation refused; no model called", file=sys.stderr)
            return 2
    if a.wait_quiet and not r5.wait_quiet(a.wait_quiet):
        print(f"P4 wait-quiet failed before preflight (limit={a.wait_quiet:g} minutes)", file=sys.stderr)
        return 2
    rep = PF.run_checks(PF.Options(a.work, ["self", "ccx2"], jobs=1, claude=getattr(a, "claude_isolation", "flags"),
                                  codex_home=Path(a.codex_home), canary=False, start=True,
                                  tasks_file=Path(TASKS.__file__), codex_workspace_tmp=True))
    if not rep["ok"]:
        for problem in rep.get("problems") or ["preflight returned ok=false without a diagnostic"]:
            print(f"P4 preflight refused: {problem}", file=sys.stderr)
        return 2
    if pin_refused(a.pin_commit, rep["commit"]):
        return 2
    sessions, rows = {}, []
    watcher = PF.Watch([str(a.work)]).start()
    between = []
    stopped = None
    not_started = None
    # Round-2 rules (#346): invalid rows are kept and the group goes on; it stops only past this many cost-unknown
    # rows (each charged at its reservation) or rows without dispatch evidence. None: round-1 rules (first stops).
    max_invalid = getattr(a, "max_invalid_rows", None)
    max_rate = getattr(a, "max_escalation_rate", .3)
    cheap_arms = [arm for arm in DE.ARMS if any(u["arm"] == arm for u in units)]
    unknown_cost_rows = missing_evidence_rows = 0
    try:
        for u in units:
            lead_cap, child_cap = task_caps(a, u["arm"])
            if not budget.reserve(lead_cap + child_cap):
                stopped = "budget_unknown" if budget.unknown else "budget"
                not_started = {**u, "spent_known_usd": budget.spent, "lead_allowance_usd": lead_cap,
                               "child_allowance_usd": child_cap, "reservation_usd": lead_cap + child_cap}
                break
            if a.wait_quiet and not r5.wait_quiet(a.wait_quiet, busy=lambda: r5._busy_now([str(a.work)])):
                print(f"P4 wait-quiet failed before task {u['task']} (limit={a.wait_quiet:g} minutes)", file=sys.stderr)
                stopped = "busy"
                break
            task = next(t for t in tasks if t["id"] == u["task"])
            key = f"{u['round']}-{u['episode']}-{u['arm']}"
            session = sessions.get(key)
            try:
                if session is None:
                    session = Episode(key, a, materials[u["task"]], task)
                    sessions[key] = session
                row = session.step({**u, "tag": a.tag}, task, materials[u["task"]], a, lead_cap + child_cap)
            except (Exception, KeyboardInterrupt) as exc:
                # Keep a failed/interrupted attempt. A missing terminal receipt
                # is unknown cost, never a free attempt, and stops the run.
                child = r5.r2.hub_cost(session.iso.hub) if session else {"usd": 0}
                if session and session.rows and session.rows[-1].get("turn") == u["turn"]:
                    row = session.rows[-1]
                else:
                    row = {**u, "tag": a.tag, "usd": None, "cost_complete": False,
                           "claude_isolation": getattr(a, "claude_isolation", "flags")}
                    if session:
                        session.rows.append(row)
                row.update({"ok": None, "env_clean": False, "error": type(exc).__name__, "environment_error": True})
                row["known_usd"] = row.get("known_usd", 0) + max(0, child["usd"] - (session.child_total if session else 0))
                if max_invalid is None or isinstance(exc, KeyboardInterrupt):
                    stopped = "interrupted_or_error"
                else:
                    # Invalid row, group continues. A later turn of a multi-task episode resumes this session,
                    # whose lead accounting has failed closed, so those rows are cost-unknown too.
                    row["cost_complete"], row["usd"] = False, None
                    if session is not None:
                        session.lead_cost.failed = True
            row.update(P5.costs(row))
            rows.append(row)
            if max_invalid is None:
                if any(u["arm"] == DE.ARM for u in units):
                    stopped = stopped or DE.stop_reason(rows, max_rate=max_rate)
                budget.charge(row.get("usd"))
                if row.get("usd") is None:
                    budget.spent += row.get("known_usd", 0)
            else:
                row["invalid_reason"] = invalid_reason(row)
                row["reservation_usd"] = row.get("reservation_usd", lead_cap + child_cap)
                row["reserved_usd"] = row["reservation_usd"]
                row.setdefault("source", task.get("source"))
                if (row.get("usd") is None or not row.get("cost_complete")
                        or row["invalid_reason"] == "dispatch_cost_unknown"):
                    # Unknown cost (including a dispatch phase whose cost is unknown): charge the reservation.
                    unknown_cost_rows += 1
                    budget.spent += max(row.get("usd") or row.get("known_usd") or 0, lead_cap + child_cap)
                else:
                    budget.charge(row["usd"])
                if row.get("arm") in DE.ARMS and row.get("dispatch_observed") is not True:
                    missing_evidence_rows += 1
                for arm in cheap_arms:
                    stopped = stopped or DE.stop_reason(rows, arm, max_rate, evidence=False)
                if unknown_cost_rows > max_invalid:
                    stopped = stopped or "cost_unknown_over_limit"
                if missing_evidence_rows > max_invalid:
                    stopped = stopped or "dispatch_evidence_unknown"
            # Journal outside every agent's allowed roots; never inject a grade
            # into the session, ccx verify, shared memory, or the live repo.
            append_jsonl(a.out.with_suffix(".pending.jsonl"), row)
            between = PF.between_units(rep, True, ours=[str(a.work)], seen=watcher.take())
            if stopped or between or budget.unknown or budget.spent >= a.budget:
                stopped = stopped or ("environment" if between else "budget_unknown" if budget.unknown else "budget")
                break
    finally:
        watcher.close()
        for session in sessions.values():
            try:
                session.close(rep, between)
            except Exception as exc:
                for row in session.rows:
                    row.update({"env_clean": False, "cleanup_error": type(exc).__name__})
        for row in rows:
            append_jsonl(a.out, row)
        limits = {**budget_envelope(a), "spent_known_usd": budget.spent, "cost_unknown": budget.unknown,
                  "observed_overspend_usd": max(0, budget.spent - budget.cap)}
        event = {"event": "stop" if stopped else "complete", "reason": stopped,
                 "spent_known_usd": budget.spent, "cost_unknown": budget.unknown, "budget_usd": budget.cap,
                 "budget_envelope": limits, "not_started": not_started}
        if max_invalid is not None:
            event.update(cost_unknown_rows=unknown_cost_rows, missing_dispatch_evidence_rows=missing_evidence_rows,
                         max_invalid_rows=max_invalid, unknown_cost_charged_at="reservation")
        append_jsonl(a.out.with_suffix(".events.jsonl"), event)
    print(json.dumps(summary(rows, expected_count(a, len(units) // 2), limits, getattr(a, "gates", "p4"),
                             max_rate), indent=2))
    if stopped:
        print(f"P4 stopped: {stopped}; known_spend=${budget.spent:g} budget=${budget.cap:g}", file=sys.stderr)
        for problem in between:
            print(f"P4 environment: {problem}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
