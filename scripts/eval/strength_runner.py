"""Serial, budgeted execution of strength manifests using seven_func's isolated ccx mechanism."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time

from common import ROOT, append_jsonl, lead_env, make_repo, score
from l5_memory import CASES, DISTRACTORS
from shared_context_ab import TASKS, lead_transcript
from seven_func import ccx_run, check_env, last_json
import preflight as PF
from ccx import ledger
from ccx.config import Paths
from ccx.runners import group_flags, kill_tree

CCX_RUN_TIMEOUT_S = 300       # one `ccx run` per unit; past this the unit is TimeoutExpired, cost Unknown


def unit_cost(hub: Path) -> float | None:
    rows = [r for r in ledger.rows(Paths(hub)) if not r.get("type")]
    amounts = [r.get("ae_usd") for r in rows]
    if not amounts or any(isinstance(x, bool) or not isinstance(x, (int, float)) or
                          not math.isfinite(x) or x < 0 for x in amounts):
        return None
    return round(sum(amounts), 8)


def run_tree(argv: list[str], *, cwd: Path, env: dict, timeout: float) -> subprocess.CompletedProcess:
    """subprocess.run(capture_output=True, text=True), but a timeout (or Ctrl+C) ends the whole process tree, not
    only the direct child (issue #329: ccx and its codex.exe ran on after a 300 s timeout). The child starts with
    ccx's group_flags() and is stopped with ccx's kill_tree(). On POSIX kill_tree() takes the child's process group,
    and ccx starts its CLI in a group of its own, so the descendants are listed first and killed too. The
    TimeoutExpired is raised again, so the row still says error: TimeoutExpired."""
    proc = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", **group_flags())
    try:
        out, err = proc.communicate(timeout=timeout)
    except BaseException:
        procs = PF.snapshot() if os.name != "nt" else None      # Windows: taskkill /T walks the tree itself
        below = sorted(PF.family(procs, proc.pid)[1]) if procs else []
        if not kill_tree(proc.pid):
            proc.kill()
        PF.kill(below)
        try:
            proc.communicate(timeout=30)
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
        raise
    return subprocess.CompletedProcess(argv, proc.returncode, out, err)


def needs_codex_home(units) -> bool:
    return any(u.get("agent") == "codex" for u in units)


def run_unit(unit: dict, kind: str, dest: Path, budget: float, codex_home: Path | None = None) -> dict:
    """All writes and client state stay in this unit, except a Codex unit's own Codex files: those go to the
    caller's logged-in `codex_home` (shared by the run's Codex units, as in p4_long_session.py), because a fresh
    empty CODEX_HOME has no login (issue #320: every Codex unit got 401). A Codex unit's TMP/TEMP/TMPDIR is its own
    tmp/ folder, and each workspace-write `codex exec` gets a private temp folder inside its working directory,
    as in p4 (issue #327: under the unelevated sandbox the system %TEMP% is not writable and PowerShell hangs).
    Hidden tests arrive after the CLI exits."""
    if unit.get("agent") == "codex" and codex_home is None:
        raise ValueError("a Codex unit needs a logged-in Codex home (--codex-home)")
    task = next(t for t in (TASKS if kind == "context" else CASES) if t["id"] == unit["task"])
    repo = make_repo(task, dest / "repo")
    isolated = lead_env()
    codex_dir = str(codex_home) if unit.get("agent") == "codex" else str(dest / "codex-home")
    isolated.update(CCX_CONFIG=str(dest / "config.toml"), CODEX_HOME=codex_dir, CODEX_SQLITE_HOME=codex_dir,
                    CLAUDE_CONFIG_DIR=str(dest / "claude-home"), CCX_CODEX_ISOLATE="1",
                    DSH_HOME=str(dest / "dsh-home"), CCX_NO_AUTO_ARCHIVE="1",
                    CCX_CLAUDE_NO_SKILLS="1", CCX_CLAUDE_SETTING_SOURCES="project,local")
    env = check_env(dest, isolated)
    for name in ("codex-home", "claude-home", "dsh-home"):
        (dest / name).mkdir(parents=True, exist_ok=True)
    (dest / "config.toml").write_text("", encoding="utf-8", newline="")
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
            sid = "strength-synthetic-lead"
            transcript = dest / "claude-home" / "projects" / "lead" / f"{sid}.jsonl"
            transcript.parent.mkdir(parents=True, exist_ok=True)
            transcript.write_text("".join(json.dumps(e) + "\n" for e in lead_transcript(task, time.time())),
                                  encoding="utf-8", newline="")
            env.update(CCX_LEAD_SESSION=sid, CCX_LEAD_VIEW="full")
        else:
            # Same distractors in every arm; only the relevant note's delivery changes.
            for topic, text in DISTRACTORS:
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


def execute(manifest: dict, out: Path, budget: float, unit_budget: float, codex_home: Path | None = None) -> dict:
    if (not math.isfinite(budget) or not 0 < budget <= manifest["cap_usd"] or
            not math.isfinite(unit_budget) or unit_budget <= 0):
        raise ValueError("invalid budget or unit budget")
    # Refuse before anything starts, never fall back to an empty home (issue #320).
    if needs_codex_home(manifest["units"]) and codex_home is None:
        raise ValueError("units run Codex: pass a logged-in Codex home (--codex-home)")
    # A fresh directory prevents accidental cost resets, repeated units and overwriting evidence.
    out.mkdir(parents=True, exist_ok=False)
    frozen_plan = {**manifest, "runtime_budget_usd": budget, "unit_budget_usd": unit_budget,
                   "codex_home": str(codex_home) if codex_home is not None else None}
    (out / "manifest.json").write_text(json.dumps(frozen_plan, indent=2) + "\n", encoding="utf-8", newline="")
    rows, spent, charged, stopped, reason = [], 0.0, 0.0, False, ""
    for index, unit in enumerate(manifest["units"]):
        if charged >= budget - 1e-9:
            stopped, reason = True, "budget exhausted"
            break
        reservation = min(unit_budget, round(budget - charged, 8))
        try:
            row = run_unit(unit, manifest["kind"], out / f"unit-{index:04d}", reservation, codex_home)
        except (Exception, KeyboardInterrupt) as exc:  # retain a failed unit even when setup could not start
            row = {**unit, "ok": None, "usd": None, "error": type(exc).__name__}
        row.update(code_pin=manifest["code_pin"], reservation_usd=reservation)
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
    report = {"kind": manifest["kind"], "dry_run": False, "evidence": "engineering check",
              "attempted": len(rows), "planned": manifest["n"], "rows": rows,
              "successes": sum(r.get("ok") is True for r in rows), "budget_usd": budget,
              "known_spent_usd": round(spent, 8), "spent_usd": round(spent, 8) if charged == spent else None,
              "charged_usd": round(charged, 8), "budget_stopped": stopped, "stop_reason": reason,
              "gate": "Unknown", "native_hook_execution": "Unknown"}
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="")
    return report
