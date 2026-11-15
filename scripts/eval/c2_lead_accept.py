"""C2: would acceptance tests that a lead writes from the brief alone catch the wrong units? Written, priced, the
paid step NOT run yet.

Three steps:

  plan      (free; --dry-run) which tasks need a test file (every task that has a wrong unit in the chosen arm,
            plus the tasks of the right units used to count false alarms), how many units each file runs on, and
            the $ estimate of writing them
  generate  (paid) one fresh lead per task (claude --model, through `ccx run --mode write` in a scratch git folder
            holding only BRIEF.md: no repository, so it can only test the behaviour the brief states) writes
            accept_<task>.py; files land in --tests. Each session runs in the round-5 clean room (preflight.prepare:
            its own empty hub, no user CLAUDE.md, skills, MCP or auto-memory), so ccx injects no shared notes into
            its brief; a file whose brief did carry notes (`shared_notes`) is not kept
  score     (free) runs every accept_<task>.py against every recorded unit of that task: the archived final tree,
            with the cwd outside the repository (a temp folder) and CCX_REPO=<tree> on PYTHONPATH, real processes
            (no mocking of kill); a wrong unit that fails = caught, a right unit that fails = false alarm

Gate (improvement plan, C2): caught >= 2 of the wrong units and false alarms <= ~3% of the right ones.

  python scripts/eval/c2_lead_accept.py plan --results <results.jsonl> --dry-run
  python scripts/eval/c2_lead_accept.py generate --results ... --tests <dir> --budget 1.5      # spends money
  python scripts/eval/c2_lead_accept.py score --results ... --tests <dir> [--json out.json]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import offline_common as oc  # noqa: E402

EST_USD = {"sonnet": 0.12, "opus": 0.30, "haiku": 0.04}     # one test-writing session (brief only, ~1 file)
WRITE = """Write an acceptance test for the change described in BRIEF.md, as one pytest file `accept_{task}.py` in this
folder. You do not have the repository: test only behaviour the brief states (its interface section names the
functions and outputs). The code under test is importable once the test runs (`import ccx` etc.: the repository
is on sys.path through PYTHONPATH, its folder is in the environment variable CCX_REPO). Real processes, files and
kills are fine; keep it under 60 seconds. Do not test anything the brief does not ask for."""


def units(base: Path, results: dict[str, dict], arm: str, tags) -> list[dict]:
    out = []
    for tag, repo in oc.unit_dirs(base, tags):
        row = results.get(oc.unit_key(tag, repo.name))
        if row and row.get("arm") == arm and row.get("ok") is not None:
            out.append({"label": row["label"], "task": row["task"], "ok": bool(row["ok"]), "repo": str(repo)})
    return out


def plan(us: list[dict], model: str) -> dict:
    wrong = sorted({u["task"] for u in us if not u["ok"]})
    tasks = sorted({u["task"] for u in us})
    return {"model": model, "units": len(us), "wrong_units": sum(not u["ok"] for u in us),
            "right_units": sum(u["ok"] for u in us), "tasks_with_wrong_units": wrong, "tasks": tasks,
            "est_usd": round(len(tasks) * EST_USD.get(model, EST_USD["sonnet"]), 2)}


def run_accept(test: Path, tree: Path, timeout: int = 180) -> dict:
    """One acceptance file on one tree: cwd is a fresh temp folder (outside the repository)."""
    with tempfile.TemporaryDirectory(prefix="c2-cwd-") as cwd:
        env = {**os.environ, "CCX_REPO": str(tree),
               "PYTHONPATH": os.pathsep.join([str(tree), str(tree / "src"), os.environ.get("PYTHONPATH", "")])}
        try:
            r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                                "--rootdir", str(test.parent), str(test)], cwd=cwd,
                               env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
                               timeout=timeout)
            return {"passed": r.returncode == 0, "rc": r.returncode, "tail": r.stdout[-300:]}
        except subprocess.TimeoutExpired:
            return {"passed": False, "rc": "timeout", "tail": ""}


def score(us: list[dict], tests: Path, runner=run_accept) -> dict:
    rows = []
    for u in us:
        f = tests / f"accept_{u['task']}.py"
        if not f.exists():
            continue
        rows.append({**u, **runner(f, Path(u["repo"]))})
    wrong, right = [r for r in rows if not r["ok"]], [r for r in rows if r["ok"]]
    caught, alarms = sum(not r["passed"] for r in wrong), sum(not r["passed"] for r in right)
    return {"scored": len(rows), "wrong": len(wrong), "caught": caught, "right": len(right), "false_alarms": alarms,
            "false_alarm_rate": round(alarms / len(right), 3) if right else None,
            "passes_gate": caught >= 2 and bool(right) and alarms / len(right) <= 0.03, "rows": rows}


NOTES_HEAD = "Shared notes that may bear on this task"      # ccx/delegate.py _brief_notes (I6)


def clean_env(task: str, work: Path) -> tuple[dict, Path, Path]:
    """(environment, scratch repo, hub) of one test-writing session in the round-5 clean room (preflight.prepare):
    allow-listed environment, a fresh empty hub (no shared notes, ledger or memory of the person's), no user
    settings, CLAUDE.md, skills or auto-memory for Claude. The writer must know only BRIEF.md."""
    import preflight as PF
    d, hub = work / task, work / "hubs" / task
    d.mkdir(parents=True, exist_ok=True)
    hub.mkdir(parents=True, exist_ok=True)
    return PF.prepare(PF.Unit(key=f"c2-{task}", work=work, repo=d, hub=hub)), d, hub


def notes_injected(hub: Path) -> bool:
    """Did any brief ccx wrote in this hub carry shared notes? (Must be False for a brief-only writer.)"""
    return any(NOTES_HEAD in f.read_text(encoding="utf-8", errors="replace") for f in hub.rglob("runs/*/prompt.md"))


def generate(tasks: list[str], tests: Path, model: str, budget: float, work: Path) -> list[dict]:  # pragma: no cover
    import r5
    from common import run_tree           # late, with r5 (which imports common)
    tests.mkdir(parents=True, exist_ok=True)
    out, spent = [], 0.0
    for t in tasks:
        if spent + EST_USD.get(model, 0.12) > budget:
            break
        env, d, hub = clean_env(t, work)
        (d / "BRIEF.md").write_text(r5.by_id(t)["brief"] + "\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=d, env=env)
        r = run_tree([sys.executable, str(ROOT / "ccx.py"), "run", "--to", "claude", "--model", model,
                      "--mode", "write", "--no-ab", "--review", "off", "--label", f"c2-accept:{t}",
                      WRITE.format(task=t)], cwd=d, env=env, timeout=1200)
        try:
            rec = json.loads(r.stdout[r.stdout.find("{"):])
        except ValueError:
            rec = {}
        spent += float(rec.get("cost_usd") or rec.get("usd") or EST_USD.get(model, 0.12))
        f = d / f"accept_{t}.py"
        leaked = notes_injected(hub)
        if f.exists() and not leaked:
            (tests / f.name).write_bytes(f.read_bytes())
        out.append({"task": t, "written": f.exists(), "shared_notes": leaked, "kept": f.exists() and not leaked,
                    "spent": round(spent, 4)})
    return out


def main(argv: list[str] | None = None) -> dict:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("step", choices=("plan", "generate", "score"))
    ap.add_argument("--records", default="")
    ap.add_argument("--results", default=str(ROOT / ".ccx/eval/r5/results.jsonl"))
    ap.add_argument("--tags", default=",".join(oc.TAGS), type=lambda x: [t for t in x.split(",") if t])
    ap.add_argument("--arm", default="ccx2")
    ap.add_argument("--model", default="sonnet")
    ap.add_argument("--tests", default="")
    ap.add_argument("--budget", type=float, default=0.0)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--json", default="")
    a = ap.parse_args(argv)
    base = Path(a.records) if a.records else oc.temp_root()
    us = units(base, oc.results_or_exit(Path(a.results), a.tags), a.arm, a.tags)
    p = plan(us, a.model)
    if a.step == "plan" or a.dry_run:
        print(json.dumps(p))
        return p
    if a.step == "generate":
        if p["est_usd"] > a.budget:
            raise SystemExit(f"estimate ${p['est_usd']} is over --budget ${a.budget}")
        out = generate(p["tasks"], Path(a.tests), a.model, a.budget, Path(tempfile.mkdtemp(prefix="c2-gen-")))
        print(json.dumps(out))
        return {"generated": out}
    s = score(us, Path(a.tests))
    print(json.dumps({k: v for k, v in s.items() if k != "rows"}))
    if a.json:
        Path(a.json).write_text(json.dumps(s, indent=1), encoding="utf-8")
    return s


if __name__ == "__main__":
    main()
