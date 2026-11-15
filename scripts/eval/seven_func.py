"""Seven cores, functional checks on real CLIs (cores 1 and 7; plan section 2). Each check is one real scenario in a
fresh scratch repo, judged by files and the hidden test, not by what an agent says:

  codex-lead   a headless Codex lead (`codex exec`) hands a task to a Claude sub-agent with `ccx run --to claude`
  resume       a sub-agent run started under a task-checkpoint step is killed partway; `ccx task resume` continues it
  undo         a write run, then `ccx undo --apply`: every file back to its bytes before the run
  budget       a parallel task with a tiny `--budget`: the sub-agent's own sub-agents are stopped (kind over_budget)

  python scripts/eval/seven_func.py <check> [--kill-after 25]
  python scripts/eval/seven_func.py summary

Every check runs with a fresh hub of its own under its scratch work dir (CCX_HUB, see check_env): its ccx runs never
write into the person's hub or ledger, and its verdict reads rows only from that hub (by task, or by label and start
time), never old rows of an earlier check with the same label. A check refuses to start when its environment would
point at the default hub. The resume check's `ok` is mechanism_ok (did ccx's stop and resume work), reported beside
task_ok (did the sub-agent's code pass the hidden test).

Rows go to .ccx/eval/seven/func.jsonl (git-ignored). Tests use fakes and never call this with real CLIs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, append_jsonl, bin_argv, ccx_rows, lead_env, make_repo, read_jsonl, run_tree, score  # noqa: E402
from ccx import ledger  # noqa: E402
from ccx.config import Paths  # noqa: E402
from tasks import PARALLEL_TASK, by_id  # noqa: E402

OUT = ROOT / ".ccx" / "eval" / "seven" / "func.jsonl"
CCX = [sys.executable, str(ROOT / "ccx.py")]
CP = [sys.executable, str(ROOT / "skills" / "task-checkpoint" / "scripts" / "checkpoint.py")]
ACCEPT = "python -m pytest -q"
CHEAP = ["--to", "codex", "--model", "gpt-6-luna", "--effort", "low"]
# variables that would send the skills' learned state somewhere other than the check's hub (task-routing, task-split)
STATE_VARS = ("TASK_ROUTING_HOME", "TASK_SPLIT_HOME")
# The resume check's visible test also covers low_stock (it returns SKUs), so ccx's own --check can catch the mistake
# only the hidden test found in a real run (2026-10-29). Only here: the shared task in tasks.py is unchanged.
RESUME_VISIBLE = ("from inventory.models import Item\nfrom inventory.report import low_stock, summary\n"
                  "from inventory.store import Store\n\n\ndef test_summary():\n    s = Store()\n"
                  "    s.add(Item('a', 'A', 5, 1))\n    assert summary(s) == {'skus': 1, 'units': 5, 'low': 0}\n\n\n"
                  "def test_low_stock_returns_skus():\n    s = Store()\n    s.add(Item('x', 'X', 1, 2))\n"
                  "    s.add(Item('y', 'Y', 7, 2))\n    assert low_stock(s) == ['x']\n")


class HubLeak(RuntimeError):
    """A check's environment would let ccx write into the person's own hub."""


def default_hubs(environ=None) -> set[Path]:
    """Every hub that is the person's: this shell's CCX_HUB, the one in their ccx config, and ~/.ccx-hub (the order
    ccx/config.py hub_dir looks in)."""
    environ = os.environ if environ is None else environ
    out = {Path.home() / ".ccx-hub"}
    if environ.get("CCX_HUB"):
        out.add(Path(environ["CCX_HUB"]).expanduser())
    cfg = Path(environ.get("CCX_CONFIG") or Path.home() / ".ccx" / "config.toml").expanduser()
    try:
        hub = tomllib.loads(cfg.read_text(encoding="utf-8")).get("hub")
    except (OSError, tomllib.TOMLDecodeError):
        hub = None
    if hub:
        out.add(Path(hub).expanduser())
    return {p.resolve() for p in out}


def guard(env: dict, work: Path | None = None) -> Path:
    """The check's hub, or HubLeak when its environment would point ccx at the default hub (no CCX_HUB, one of the
    person's hubs, a hub outside the check's work dir) or send learned state elsewhere."""
    if not env.get("CCX_HUB"):
        raise HubLeak("refusing to run: no CCX_HUB, so ccx would use the person's default hub")
    hub = Path(env["CCX_HUB"]).expanduser().resolve()
    if hub in default_hubs():
        raise HubLeak(f"refusing to run: CCX_HUB {hub} is the person's own hub")
    if work is not None and not hub.is_relative_to(Path(work).resolve()):
        raise HubLeak(f"refusing to run: CCX_HUB {hub} is not under the check's work dir {work}")
    leaked = [k for k in STATE_VARS if env.get(k)]
    if leaked:
        raise HubLeak(f"refusing to run: {', '.join(leaked)} would send learned state outside the check's hub")
    return hub


def check_env(work: Path, base: dict | None = None) -> dict:
    """The environment of one check: a fresh hub under its work dir (never the default one), no quota probe (each new
    hub would probe Claude's quota again), no outside state homes. Guarded before it is handed out."""
    hub = Path(work) / "hub"
    hub.mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in (base or lead_env()).items() if k not in STATE_VARS}
    env.update(CCX_HUB=str(hub), CCX_NO_QUOTA_PROBE="1")
    guard(env, work)
    return env


def hub_of(env: dict) -> Path:
    return Path(env["CCX_HUB"])


def task_rows(hub: Path, task: str) -> list[dict]:
    """Ledger rows of this check's task, from its own hub."""
    return [r for r in ledger.rows(Paths(hub)) if not r.get("type") and r.get("task") == task]


def label_rows(hub: Path, label: str, since: float) -> list[dict]:
    """Ledger rows under `label` that started at or after `since`, from the given hub."""
    return [r for r in ccx_rows(label, hub) if (r.get("ts") or 0) >= since - 5]


def run_record(hub: Path, run_id: str | None) -> dict:
    try:
        return ledger.load_run(Paths(hub), run_id) if run_id else {}
    except (OSError, ValueError):
        return {}


def task_records(hub: Path, task: str) -> list[dict]:
    """Run records (run.json) of the task, oldest first: a killed run has one but no ledger row."""
    runs, out = Paths(hub).runs, []
    for f in (runs.glob("*/run.json") if runs.exists() else []):
        try:
            rec = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if rec.get("task") == task:
            out.append(rec)
    return sorted(out, key=lambda r: r.get("ts") or 0)


def sh(argv: list[str], cwd: Path, timeout: int = 900, env: dict | None = None) -> tuple[int, str, str]:
    env = env or lead_env()
    guard(env)
    try:
        r = run_tree(argv, cwd=cwd, env=env, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -9, "", "timeout"


def last_json(text: str) -> dict:
    for line in reversed((text or "").strip().splitlines()):
        if line.strip().startswith("{"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                pass
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return {}


def tree_hash(repo: Path) -> dict[str, str]:
    """sha256 of every file outside .git and .ccx (what a run may change and undo must put back)."""
    out = {}
    for f in sorted(repo.rglob("*")):
        rel = f.relative_to(repo).as_posix()
        if f.is_file() and not rel.startswith((".git/", ".ccx/")) and "__pycache__" not in rel \
                and ".pytest_cache" not in rel:
            out[rel] = hashlib.sha256(f.read_bytes()).hexdigest()
    return out


def kill_tree(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True)
    else:
        import signal
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except OSError:
            pass


def ccx_run(repo: Path, label: str, brief: str, extra: list[str]) -> list[str]:
    return [*CCX, "run", "--mode", "write", "--new", "--no-ab", "--force", "--label", label, "--check", ACCEPT,
            *extra, brief]


def check_codex_lead(a, work: Path) -> dict:
    task = by_id("roman")
    repo = make_repo(task, work / "codex-lead")
    env = check_env(work)
    label = "eval-7c:func:codex-lead"
    ccx = " ".join(f'"{x}"' for x in CCX)
    if os.name == "nt":  # Codex's shell is PowerShell 5.1: a quoted program needs the call operator (as agent-delegate teaches)
        ccx = "& " + ccx
    prompt = (f"You are the lead agent in this repository.\nTask: {task['brief']}\n"
              f"Acceptance: `{ACCEPT}` must pass. Do not do the work yourself: hand it to Claude with one shell "
              f"command:\n  {ccx} run --from codex --to claude --model haiku --effort low --mode write --new --no-ab "
              f"--force --label {label} --check \"{ACCEPT}\" \"<a short brief>\"\nIt prints a JSON result; ccx "
              "has already re-run the acceptance command (its check field). Then answer DONE or FAILED.")
    argv = [*bin_argv("codex"), "exec", "--json", "-m", a.lead_model, "-c", f'model_reasoning_effort="{a.lead_effort}"',
            *([] if a.lead_sandbox == "config" else ["-s", a.lead_sandbox]), "--skip-git-repo-check",
            "-C", str(repo), "-"]
    t0 = time.time()
    try:
        r = run_tree(argv, input=prompt, cwd=repo, env=env, timeout=900)
        out, rc = r.stdout, r.returncode
    except subprocess.TimeoutExpired:
        out, rc = "", -9
    rows = label_rows(hub_of(env), label, t0)
    # a read-only look at the person's hubs: a Codex shell that dropped CCX_HUB would have written there instead
    leaked = sum(len(label_rows(h, label, t0)) for h in default_hubs())
    sc = score(repo, task)
    used, cmds, said = [], [], []
    for x in out.splitlines():
        try:
            ev = json.loads(x) if x.startswith("{") else {}
        except json.JSONDecodeError:
            continue
        it = ev.get("item") or {}
        if ev.get("type") == "turn.completed":
            used.append(ev.get("usage"))
        elif ev.get("type") == "item.completed" and it.get("type") == "command_execution":
            cmds.append({"command": str(it.get("command"))[:300], "exit_code": it.get("exit_code"),
                         "output": str(it.get("aggregated_output"))[-300:]})
        elif ev.get("type") == "item.completed" and it.get("type") == "agent_message":
            said.append(str(it.get("text"))[:300])
    sub = any(r.get("to") == "claude" and r.get("caller") == "codex" for r in rows)
    # a run that wrote into the person's hub fails the check even when another one used the check's own hub
    return {"check": "codex-lead", "sandbox": a.lead_sandbox, "ok": sc["ok"] and sub and leaked == 0,
            "hidden_ok": sc["ok"], "pytest": sc["pytest"], "rc": rc, "wall_s": round(time.time() - t0, 1),
            "hub": str(hub_of(env)), "rows_in_default_hub": leaked,
            "sub_runs": [{k: r.get(k) for k in ("run_id", "caller", "to", "rungs", "ok", "ae_usd", "seconds")}
                         for r in rows], "lead_usage": used, "lead_commands": cmds, "lead_said": said}


def check_resume(a, work: Path) -> dict:
    task = {**by_id("inventory"), "visible": RESUME_VISIBLE}
    repo = make_repo(task, work / "resume")
    env = {**check_env(work), "CHECKPOINT_ROOT": str(repo)}
    hub = hub_of(env)
    rc, out, err = sh([*CP, "init", "--title", "7c resume check", "--step", "implement the inventory changes"],
                      repo, env=env)
    tid = (out.strip().splitlines() or [""])[-1].strip()
    label = "eval-7c:func:resume"
    argv = ccx_run(repo, label, task["brief"], [*CHEAP, "--task", tid, "--step", "1", "--review", "off"])
    t0 = time.time()
    proc = subprocess.Popen(argv, cwd=repo, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
                            start_new_session=os.name != "nt")
    try:
        proc.wait(timeout=a.kill_after)
        killed, killed_after = False, None
    except subprocess.TimeoutExpired:
        kill_tree(proc.pid)
        proc.wait()
        killed, killed_after = True, round(time.time() - t0, 1)     # the kill itself, not scoring and resuming too
    before = score(repo, task)
    killed_recs = task_records(hub, tid)
    status_rc, status, _ = sh([*CCX, "task", "status", tid, "--cwd", str(repo)], repo, env=env)
    t1 = time.time()
    rc2, out2, err2 = sh([*CCX, "task", "resume", tid, "--cwd", str(repo)], repo, env=env)
    resume_s = round(time.time() - t1, 1)
    res = last_json(out2)
    after = score(repo, task)
    from_id = res.get("resumed") or res.get("restarted")
    prev = next((r for r in killed_recs if r.get("run_id") == from_id), {})
    new = run_record(hub, res.get("run_id"))
    # the killed run's session continued (None: it was killed before its session began, so ccx restarts the step)
    # the id the resumed CLI itself reported (the record's top-level id is copied forward from the killed run, so
    # it would match even when the CLI never started a session)
    reported = next((t.get("session_id") for t in reversed(new.get("attempts") or []) if t.get("session_id")), None)
    same_session = (reported is not None and reported == prev["session_id"]) if prev.get("session_id") else None
    inherited = {"label": new.get("label") == label, "check": new.get("check_cmd") == ACCEPT,
                 "review": new.get("review_mode") == "off"}
    mechanism = {
        "killed_run_unfinished": killed and bool(prev) and not prev.get("ok"),
        "same_task": bool(new) and new.get("task") == tid,
        "same_session": same_session is True or (same_session is None and bool(res.get("restarted"))),
        "inherited": all(inherited.values()),
        "resume_rc0": rc2 == 0,
    }
    mechanism_ok = all(mechanism.values())
    return {"check": "resume", "ok": mechanism_ok, "mechanism_ok": mechanism_ok, "task_ok": after["ok"],
            "mechanism": mechanism, "inherited": inherited, "same_session": same_session,
            "task": tid, "killed": killed, "killed_after_s": killed_after, "resume_s": resume_s,
            "killed_run": from_id, "resumed_run": res.get("run_id"), "hub": str(hub),
            "hidden_ok_after_kill": before["ok"], "hidden_ok_after_resume": after["ok"], "pytest": after["pytest"],
            "status_after_kill": status[-600:], "resume_rc": rc2, "resumed": res.get("resumed"),
            "resume_status": res.get("status"), "resume_err": err2[-400:],
            "runs": [{k: r.get(k) for k in ("run_id", "rungs", "ok", "kind", "ae_usd", "session_id")}
                     for r in task_rows(hub, tid)] + [{"resumed_run": res.get("run_id"), "ok": res.get("ok")}]}


def check_undo(a, work: Path) -> dict:
    task = by_id("slugify")
    repo = make_repo(task, work / "undo")
    env = check_env(work)
    h0 = tree_hash(repo)
    rc, out, err = sh(ccx_run(repo, "eval-7c:func:undo", task["brief"], [*CHEAP, "--review", "off"]), repo,
                      env=env)
    res = last_json(out)
    h1 = tree_hash(repo)
    mid = score(repo, task)
    rid = res.get("run_id", "")
    _, dry, _ = sh([*CCX, "undo", rid], repo, env=env)
    _, app, uerr = sh([*CCX, "undo", rid, "--apply"], repo, env=env)
    h2 = tree_hash(repo)
    changed = sorted(k for k in set(h0) | set(h1) if h0.get(k) != h1.get(k))
    return {"check": "undo", "ok": bool(changed) and h2 == h0, "run_id": rid, "run_ok": res.get("ok"),
            "hidden_ok_after_run": mid["ok"], "changed_by_run": changed, "restored": h2 == h0,
            "left_different": sorted(k for k in set(h0) | set(h2) if h0.get(k) != h2.get(k)),
            "dry_run": dry[-500:], "apply": app[-500:], "apply_err": uerr[-300:], "hub": str(hub_of(env))}


def check_budget(a, work: Path) -> dict:
    task = PARALLEL_TASK
    repo = make_repo(task, work / f"budget-{a.budget_to}")
    env = check_env(work)
    pick = ["--to", "claude", "--model", "haiku", "--effort", "low"] if a.budget_to == "claude" else CHEAP
    label = f"eval-7c:func:budget:{a.budget_to}"
    t0 = time.time()
    rc, out, err = sh(ccx_run(repo, label, task["brief"], [*pick, "--parallel", "--budget", str(a.budget),
                                                           "--no-escalate", "--no-fallback", "--review", "off"]),
                      repo, env=env)
    res = last_json(out)
    rows = label_rows(hub_of(env), label, t0)
    return {"check": f"budget-{a.budget_to}", "ok": any(r.get("kind") == "over_budget" for r in rows),
            "budget": a.budget, "kinds": [r.get("kind") for r in rows], "status": res.get("status"),
            "hint": res.get("hint") or res.get("error"), "subagents": res.get("subagents"),
            "ae_usd": sum(r.get("ae_usd") or 0 for r in rows), "wall_s": round(time.time() - t0, 1),
            "hidden_ok": score(repo, task)["ok"], "run_ids": [r["run_id"] for r in rows], "hub": str(hub_of(env))}


CHECKS = {"codex-lead": check_codex_lead, "resume": check_resume, "undo": check_undo, "budget": check_budget}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("check", choices=[*CHECKS, "summary"])
    ap.add_argument("--kill-after", type=float, default=25.0, help="resume: kill the sub-agent after this long (s)")
    ap.add_argument("--budget", type=float, default=0.0001, help="budget: the cap ($)")
    ap.add_argument("--budget-to", choices=["claude", "codex"], default="claude")
    ap.add_argument("--lead-model", default="gpt-6-luna")
    ap.add_argument("--lead-effort", default="low")
    ap.add_argument("--lead-sandbox", default="config",
                    help="codex-lead: config = the user's own Codex setting, or a -s mode such as workspace-write")
    ap.add_argument("--out", default="")
    a = ap.parse_args(argv)
    out = Path(a.out) if a.out else OUT
    if a.check == "summary":
        for r in read_jsonl(out):
            print(f"{r['check']:12} ok={r['ok']}  " + json.dumps({k: v for k, v in r.items()
                                                                if k in ("killed", "restored", "kinds", "sub_runs",
                                                                         "hidden_ok", "hidden_ok_after_resume",
                                                                         "mechanism_ok", "task_ok")},
                                                               ensure_ascii=False)[:300])
        return 0
    try:
        row = CHECKS[a.check](a, Path(tempfile.mkdtemp(prefix=f"ccx-7c-{a.check}-")))
    except HubLeak as e:
        print(f"seven_func: {e}", file=sys.stderr)
        return 2
    row["ts"] = time.time()
    append_jsonl(out, row)
    print(json.dumps(row, ensure_ascii=False, indent=1))
    return 0 if row["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
