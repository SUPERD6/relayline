"""Serial, budgeted execution of strength manifests using seven_func's isolated ccx mechanism."""
from __future__ import annotations

import json
import math
from pathlib import Path
import subprocess
import sys
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


def needs_codex_home(units) -> bool:
    return any(u.get("agent") == "codex" for u in units)


def needs_claude_home(units) -> bool:
    return any(u.get("agent") == "claude" for u in units)


def unit_env(unit: dict, dest: Path, codex_home: Path | None, claude_home: Path | None = None,
             fresh: bool = False) -> dict:
    """The unit's environment and its own folders. Everything stays in `dest` except the logged-in homes a unit's own
    CLI needs: a Codex unit uses `codex_home`, a Claude unit `claude_home` (issue #320 / #345: an empty home has no
    login). Claude units never get web tools; a `fresh` (--tasks) run's Codex units neither."""
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
        perms["deny"] = sorted(set(perms.get("deny") or []) | set(CLAUDE_NO_WEB["permissions"]["deny"]))
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
             claude_home: Path | None = None, tasks: list[dict] | None = None, fresh: bool = False) -> dict:
    """All writes and client state stay in this unit, except a Codex unit's own Codex files: those go to the
    caller's logged-in `codex_home` (shared by the run's Codex units, as in p4_long_session.py), because a fresh
    empty CODEX_HOME has no login (issue #320: every Codex unit got 401). A Claude unit likewise uses the caller's
    logged-in `claude_home`; its synthetic lead transcript gets a unique session id there (#345). A Codex unit's
    TMP/TEMP/TMPDIR is its own tmp/ folder, and each workspace-write `codex exec` gets a private temp folder inside
    its working directory, as in p4 (issue #327: under the unelevated sandbox the system %TEMP% is not writable and
    PowerShell hangs). `tasks`: a frozen --tasks file's tasks instead of the built-in ones. Hidden tests arrive after
    the CLI exits."""
    pool = tasks if tasks is not None else (TASKS if kind == "context" else CASES)
    task = next(t for t in pool if t["id"] == unit["task"])
    env = unit_env(unit, dest, codex_home, claude_home, fresh)
    repo = make_repo(task, dest / "repo")
    if unit.get("agent") == "codex":
        tmp = dest / "tmp"
        tmp.mkdir(parents=True, exist_ok=True)
        env.update({k: str(tmp) for k in ("TMP", "TEMP", "TMPDIR")})
        env.update(PF.codex_workspace_tmp_env(repo, dest))
    hub = Path(env["CCX_HUB"])
    # No app/session archiving: these synthetic homes are retained as evidence.
    def command(args):
        return run_tree([sys.executable, str(ROOT / "ccx.py"), *args], cwd=repo, env=env, timeout=180)

    def setup(args):
        result = command(args)
        if result.returncode:
            raise RuntimeError("synthetic context/memory setup failed")
        return result.stdout

    brief, payload = task["brief"], ""
    row = {**unit, "ok": None, "usd": 0.0, "rc": None, "native_hook_execution": "Unknown"}
    if unit.get("agent") == "codex":
        row["tmp_policy"] = "codex-workspace-private"
    started = False
    t0 = time.monotonic()
    try:
        if kind == "context":
            if unit.get("agent") == "claude":
                # The shared logged-in home holds every Claude unit's transcript: a unique id per unit
                sid, transcript = write_lead_transcript(task, claude_home, f"strength-{uuid.uuid4().hex}",
                                                        SYNTHETIC_LEAD_FOLDER)
                row["lead_transcript"] = str(transcript)
            else:
                sid, _ = write_lead_transcript(task, dest / "claude-home", "strength-synthetic-lead")
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
    # A fresh directory prevents accidental cost resets, repeated units and overwriting evidence.
    out.mkdir(parents=True, exist_ok=False)
    frozen_plan = {**manifest, "runtime_budget_usd": budget, "unit_budget_usd": unit_budget,
                   "codex_home": str(codex_home) if codex_home is not None else None}
    if claude_home is not None:
        frozen_plan["claude_home"] = str(claude_home)
    (out / "manifest.json").write_text(json.dumps(frozen_plan, indent=2) + "\n", encoding="utf-8", newline="")
    if on_invalid == "continue":
        rows, spent, charged, stopped, reason = _run_continuing(manifest, out, budget, unit_budget, codex_home,
                                                                claude_home, tasks, fresh)
        invalid = sum(r.get("invalid") is True for r in rows)
        extra = {"on_invalid": "continue", "invalid": invalid,
                 "unknown_cost_units": sum(r.get("usd") is None for r in rows)}
    else:
        rows, spent, charged, stopped, reason = _run_stopping(manifest, out, budget, unit_budget, codex_home,
                                                              claude_home, tasks, fresh)
        extra = {}
    report = {"kind": manifest["kind"], "dry_run": False, "evidence": "engineering check",
              "attempted": len(rows), "planned": manifest["n"], "rows": rows,
              "successes": sum(r.get("ok") is True for r in rows), "budget_usd": budget,
              "known_spent_usd": round(spent, 8), "spent_usd": round(spent, 8) if charged == spent else None,
              "charged_usd": round(charged, 8), "budget_stopped": stopped, "stop_reason": reason,
              "gate": "Unknown", "native_hook_execution": "Unknown", **extra}
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="")
    return report


def _one(manifest, index, unit, out, reservation, codex_home, claude_home, tasks, fresh) -> dict:
    try:
        row = run_unit(unit, manifest["kind"], out / f"unit-{index:04d}", reservation, codex_home,
                       claude_home=claude_home, tasks=tasks, fresh=fresh)
    except (Exception, KeyboardInterrupt) as exc:  # retain a failed unit even when setup could not start
        row = {**unit, "ok": None, "usd": None, "error": type(exc).__name__}
    row.update(code_pin=manifest["code_pin"], reservation_usd=reservation)
    return row


ENVIRONMENT_KINDS = ("auth", "quota")   # a receipt saying the CLI could not work at all: no task outcome follows
ARM_LIMIT_KINDS = ("timeout", "over_budget", "max_usd")   # the sub-agent's own time/cost cap (ccx/delegate.py)


def _run_continuing(manifest, out, budget, unit_budget, codex_home, claude_home, tasks, fresh):
    """--on-invalid continue (the round-2 preregistration): an environment error, a receipt status "error" or an
    unknown cost makes the row invalid (recorded, "invalid": true) and the group goes on. An arm's own timeout or
    cap hit with a known cost is a valid row with ok false. The group stops only on: the budget, a unit that spent
    more than its reservation, Ctrl-C, more than MAX_UNKNOWN_COST_UNITS unknown-cost units (each charged at its
    reservation), or the environment check: a receipt of kind auth/quota (issue #321: 42 units ran on with 401)."""
    from strength_retest import MAX_UNKNOWN_COST_UNITS
    rows, spent, charged, unknown = [], 0.0, 0.0, 0
    for index, unit in enumerate(manifest["units"]):
        if charged >= budget - 1e-9:
            return rows, spent, charged, True, "budget exhausted"
        reservation = min(unit_budget, round(budget - charged, 8))
        row = _one(manifest, index, unit, out, reservation, codex_home, claude_home, tasks, fresh)
        amount = row["usd"]
        if (row.get("status") == "error" and row.get("kind") in ARM_LIMIT_KINDS and amount is not None
                and not row.get("error")):
            # The sub-agent's own timeout or cap: ccx has no structured result, so the receipt says status "error",
            # but the preregistration counts it as a valid row with ok = False (hidden test kept as hidden_ok)
            row.update(arm_limit=row["kind"], hidden_ok=row.get("ok"), ok=False)
        receipt_error = row.get("status") == "error" and "arm_limit" not in row
        reasons = [r for r, bad in (("error", bool(row.get("error"))), ("receipt status error", receipt_error),
                                    ("unknown cost", amount is None), ("no outcome", row.get("ok") is None)) if bad]
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


def _run_stopping(manifest, out, budget, unit_budget, codex_home, claude_home, tasks, fresh):
    """The default: the group stops on the first errored, receipt-error or unknown-cost unit (round 1)."""
    rows, spent, charged, stopped, reason = [], 0.0, 0.0, False, ""
    for index, unit in enumerate(manifest["units"]):
        if charged >= budget - 1e-9:
            stopped, reason = True, "budget exhausted"
            break
        reservation = min(unit_budget, round(budget - charged, 8))
        row = _one(manifest, index, unit, out, reservation, codex_home, claude_home, tasks, fresh)
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
        if row.get("status") == "error":
            # The ccx receipt says the run itself failed (e.g. kind=auth): the preregistration stops the group on
            # an errored row, not only on a Python exception here (issue #321: 42 units ran on with 401).
            stopped, reason = True, f"ccx receipt status error (kind={row.get('kind')})"
            break
    return rows, spent, charged, stopped, reason
