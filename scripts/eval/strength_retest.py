"""Context/memory retest plans; execution requires explicit --run and --budget."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, lead_env
from l5_memory import CASES
from shared_context_ab import TASKS, MODELS


def plan(kind: str, reps: int = 3, unit_usd: float | None = None) -> dict:
    if reps < 1 or (unit_usd is not None and (not math.isfinite(unit_usd) or unit_usd < 0)):
        raise ValueError("reps must be positive; unit estimate must be finite and non-negative")
    if kind == "context":
        units = [{"task": t["id"], "scenario": "neutral" if t["neutral"] else "favourable",
                  "agent": agent, "model": model, "effort": effort, "arm": arm, "rep": rep}
                 for rep in range(1, reps + 1) for t in TASKS
                 for agent, (model, effort) in MODELS.items() for arm in ("off", "on")]
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
        units = [{"task": t["id"], "arm": arm, "rep": rep, "agent": "codex",
                  "model": "gpt-6-luna", "effort": "low", "previously_used": True}
                 for rep in range(1, reps + 1) for t in CASES
                 for arm in ("nomem", "mem", "hubmem", "hubstart")]
        cap = 3.0
        historical = ROOT / "docs/research/data/2026-10-25-l5-memory.json"
        old = json.loads(historical.read_text(encoding="utf-8"))
        proxy = old["summary"]["spend_usd"] / old["summary"]["units"]
        source = historical.name
        arms = {"nomem": "no convention", "mem": "ccx ctx add (project context)",
                "hubmem": "ccx mem add (delegation brief)",
                "hubstart": "ccx mem add; ccx mem delta --as codex --peek (startup payload)"}
    else:
        raise ValueError("unknown retest kind")
    estimate = len(units) * (proxy if unit_usd is None else unit_usd)
    # Trust only this script's repository for these invocations, never alter global Git configuration.
    git = ["git", "-c", f"safe.directory={ROOT.as_posix()}"]
    pin = subprocess.run([*git, "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True,
                         encoding="utf-8", errors="replace", check=True).stdout.strip()
    dirty = bool(subprocess.run([*git, "status", "--porcelain"], cwd=ROOT, capture_output=True,
                                text=True, encoding="utf-8", errors="replace", check=True).stdout.strip())
    return {"evidence": "not run", "dry_run": True, "kind": kind, "code_pin": pin, "dirty": dirty,
            "reps": reps, "tasks": len(TASKS) if kind == "context" else len(CASES), "arms": arms,
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
    hook = sub.add_parser("probe-hook")
    hook.add_argument("--hub", required=True, type=Path, help="synthetic hub only")
    hook.add_argument("--cwd", required=True, type=Path)
    hook.add_argument("--as", dest="agent", choices=("codex", "claude"), default="codex")
    a = p.parse_args(argv)
    try:
        if a.cmd == "execute":
            data = plan(a.kind, a.reps)
            if a.budget is not None and (not math.isfinite(a.budget) or not 0 < a.budget <= data["cap_usd"]):
                raise ValueError("budget must be positive, finite and within the kind's cap")
            if not math.isfinite(a.unit_budget) or a.unit_budget <= 0:
                raise ValueError("unit budget must be positive and finite")
            data.update(budget_usd=a.budget if a.budget is not None else data["cap_usd"],
                        unit_budget_usd=a.unit_budget)
            data["within_budget"] = data["estimated_usd"] <= data["budget_usd"]
            if a.run:
                if a.budget is None or a.out is None:
                    raise ValueError("execution requires --run --budget USD --out FRESH_DIRECTORY")
                from strength_runner import execute
                data = execute(data, a.out, a.budget, a.unit_budget)
        else:
            data = plan(a.kind, a.reps, a.unit_usd) if a.cmd == "plan" else probe_hook(a.hub, a.cwd, a.agent)
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
