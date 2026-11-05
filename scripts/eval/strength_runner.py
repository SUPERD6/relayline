"""Serial, budgeted execution of strength manifests using seven_func's isolated ccx mechanism."""
from __future__ import annotations

import json
import math
from pathlib import Path
import subprocess
import sys
import time

from common import ROOT, append_jsonl, lead_env, make_repo, score
from l5_memory import CASES, DISTRACTORS
from shared_context_ab import TASKS, lead_transcript
from seven_func import ccx_run, check_env, last_json
from ccx import ledger
from ccx.config import Paths


def unit_cost(hub: Path) -> float | None:
    rows = [r for r in ledger.rows(Paths(hub)) if not r.get("type")]
    amounts = [r.get("ae_usd") for r in rows]
    if not amounts or any(isinstance(x, bool) or not isinstance(x, (int, float)) or
                          not math.isfinite(x) or x < 0 for x in amounts):
        return None
    return round(sum(amounts), 8)


def run_unit(unit: dict, kind: str, dest: Path, budget: float) -> dict:
    """All writes and client state stay in this unit; hidden tests arrive after the CLI exits."""
    task = next(t for t in (TASKS if kind == "context" else CASES) if t["id"] == unit["task"])
    repo = make_repo(task, dest / "repo")
    isolated = lead_env()
    isolated.update(CCX_CONFIG=str(dest / "config.toml"), CODEX_HOME=str(dest / "codex-home"),
                    CLAUDE_CONFIG_DIR=str(dest / "claude-home"), CCX_CODEX_ISOLATE="1",
                    DSH_HOME=str(dest / "dsh-home"), CCX_NO_AUTO_ARCHIVE="1",
                    CCX_CLAUDE_NO_SKILLS="1", CCX_CLAUDE_SETTING_SOURCES="project,local")
    env = check_env(dest, isolated)
    for name in ("codex-home", "claude-home", "dsh-home"):
        (dest / name).mkdir(parents=True, exist_ok=True)
    (dest / "config.toml").write_text("", encoding="utf-8", newline="")
    hub = Path(env["CCX_HUB"])
    # No app/session archiving: these synthetic homes are retained as evidence.
    def command(args):
        return subprocess.run([sys.executable, str(ROOT / "ccx.py"), *args], cwd=repo, env=env,
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)

    def setup(args):
        result = command(args)
        if result.returncode:
            raise RuntimeError("synthetic context/memory setup failed")
        return result.stdout

    brief, payload = task["brief"], ""
    row = {**unit, "ok": None, "usd": 0.0, "rc": None, "native_hook_execution": "Unknown"}
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
        result = subprocess.run(ccx_run(repo, "strength-retest", brief, extra), cwd=repo, env=env,
                                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
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


def execute(manifest: dict, out: Path, budget: float, unit_budget: float) -> dict:
    if (not math.isfinite(budget) or not 0 < budget <= manifest["cap_usd"] or
            not math.isfinite(unit_budget) or unit_budget <= 0):
        raise ValueError("invalid budget or unit budget")
    # A fresh directory prevents accidental cost resets, repeated units and overwriting evidence.
    out.mkdir(parents=True, exist_ok=False)
    frozen_plan = {**manifest, "runtime_budget_usd": budget, "unit_budget_usd": unit_budget}
    (out / "manifest.json").write_text(json.dumps(frozen_plan, indent=2) + "\n", encoding="utf-8", newline="")
    rows, spent, charged, stopped, reason = [], 0.0, 0.0, False, ""
    for index, unit in enumerate(manifest["units"]):
        if charged >= budget - 1e-9:
            stopped, reason = True, "budget exhausted"
            break
        reservation = min(unit_budget, round(budget - charged, 8))
        try:
            row = run_unit(unit, manifest["kind"], out / f"unit-{index:04d}", reservation)
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
    report = {"kind": manifest["kind"], "dry_run": False, "evidence": "engineering check",
              "attempted": len(rows), "planned": manifest["n"], "rows": rows,
              "successes": sum(r.get("ok") is True for r in rows), "budget_usd": budget,
              "known_spent_usd": round(spent, 8), "spent_usd": round(spent, 8) if charged == spent else None,
              "charged_usd": round(charged, 8), "budget_stopped": stopped, "stop_reason": reason,
              "gate": "Unknown", "native_hook_execution": "Unknown"}
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="")
    return report
