"""Shared helpers for the scripts in scripts/eval/: scratch repos, the headless Claude lead, scoring, ledger."""
from __future__ import annotations

import json
import math
import os
import random
import shutil
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from ccx import ledger  # noqa: E402
from ccx.config import Paths, paths  # noqa: E402
from ccx.runners import bin_argv  # noqa: E402

CCX = f'python "{ROOT.as_posix()}/ccx.py"'
HIDDEN = "test_zz_hidden_eval.py"
# Variables that would tie a child Claude to the session that started this script (same list as ccx's
# delegate._child_env, plus the desktop app's messaging channel).
PARENT_VARS = ("CLAUDECODE", "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_REMOTE_SESSION_ID", "CLAUDE_EFFORT",
               "CLAUDE_CODE_EFFORT_LEVEL", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_CHILD_SESSION", "CLAUDE_PID", "CLAUDE_CODE_HOST_SESSION_ID",
               "CLAUDE_CODE_MESSAGING_SOCKET", "CLAUDE_CODE_MESSAGING_TOKEN", "CCX_LEAD_SESSION", "CCX_DEPTH",
               "CCX_ROLE", "CCX_PARENT_RUN")


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-c", "user.name=eval", "-c", "user.email=eval@example.invalid", *args],
                          cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace").stdout


def make_repo(task: dict, dest: Path) -> Path:
    """A fresh git repo with the task's start files and its visible test, committed."""
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    for name, text in task["files"].items():
        (dest / name).parent.mkdir(parents=True, exist_ok=True)
        (dest / name).write_text(text, encoding="utf-8")
    if task.get("visible"):
        (dest / "test_task.py").write_text(task["visible"], encoding="utf-8")
    git(dest, "init", "-q")
    git(dest, "add", "-A")
    git(dest, "commit", "-q", "-m", "start")
    return dest


def score(repo: Path, task: dict) -> dict:
    """Run the hidden acceptance test (plus every test in the repo) on the agent's result."""
    f = repo / HIDDEN
    f.write_text(task["hidden"], encoding="utf-8")
    try:
        r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"], cwd=repo,
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    finally:
        f.unlink(missing_ok=True)
    tail = (r.stdout.strip().splitlines() or [""])[-1]
    return {"ok": r.returncode == 0, "pytest": tail[:200]}


def lead_env() -> dict:
    env = {k: v for k, v in os.environ.items() if k not in PARENT_VARS}
    env["PYTHONIOENCODING"] = "utf-8"
    # `python` in the agents' shells is the interpreter running this script (run it from a venv with pytest)
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
    return env


def run_lead(prompt: str, cwd: Path, model: str, effort: str, budget: float, timeout: int = 900,
             persist: bool = False) -> dict:
    """One headless Claude Code lead (slim start-up, the same flags ccx uses for lean Claude sub-agents)."""
    argv = [*bin_argv("claude"), "-p", "--output-format", "stream-json", "--verbose", "--model", model,
            "--effort", effort, "--tools", "Read,Grep,Glob,Edit,Write,Bash", "--permission-mode", "acceptEdits",
            "--allowed-tools", "Read Grep Glob Edit Write Bash", "--strict-mcp-config",
            "--exclude-dynamic-system-prompt-sections", "--disable-slash-commands", "--max-budget-usd", str(budget)]
    if not persist:
        argv.append("--no-session-persistence")
    t0 = time.time()
    try:
        r = subprocess.run(argv, input=prompt, cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", env=lead_env(), timeout=timeout)
        out, rc = r.stdout, r.returncode
    except subprocess.TimeoutExpired as e:
        out, rc = (e.stdout or b"").decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or ""), -9
    res = parse_stream(out)
    res.update(rc=rc, wall_s=round(time.time() - t0, 1))
    return res


def parse_stream(stdout: str) -> dict:
    """Lead cost and behaviour from Claude's stream-json: requests, context per request, tool calls."""
    msgs, tools, bash, final = {}, {}, [], {}
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("type") == "assistant":
            m = ev.get("message") or {}
            if m.get("id"):
                msgs[m["id"]] = m.get("usage") or {}
            for c in m.get("content") or []:
                if c.get("type") == "tool_use":
                    tools[c["name"]] = tools.get(c["name"], 0) + 1
                    if c["name"] == "Bash":
                        bash.append(str((c.get("input") or {}).get("command", ""))[:400])
        elif ev.get("type") == "result":
            final = ev
    ctx = [(u.get("input_tokens", 0) or 0) + (u.get("cache_read_input_tokens", 0) or 0)
           + (u.get("cache_creation_input_tokens", 0) or 0) for u in msgs.values()]
    u = final.get("usage") or {}
    return {"cost_usd": final.get("total_cost_usd"), "num_turns": final.get("num_turns"),
            "duration_ms": final.get("duration_ms"), "is_error": final.get("is_error"),
            "subtype": final.get("subtype"), "answer": str(final.get("result", ""))[-400:],
            "requests": len(msgs), "context_tokens": sum(ctx), "context_max": max(ctx, default=0),
            "output_tokens": u.get("output_tokens"), "usage": u, "tools": tools, "bash": bash}


def ccx_rows(label: str, hub: Path | None = None) -> list[dict]:
    """Ledger rows of the runs under `label`, in the hub ccx uses (or the given one, e.g. a throwaway eval hub)."""
    return [r for r in ledger.rows(Paths(hub) if hub else paths()) if not r.get("type") and r.get("label") == label]


def ccx_verify(run_id: str, ok: bool, note: str, hub: Path | None = None, env: dict | None = None) -> str:
    args = [sys.executable, str(ROOT / "ccx.py"), "verify", run_id, "--ok", "1" if ok else "0", "--note", note]
    if not ok:
        args += ["--reason", "wrong"]
    env = {**(env or lead_env()), **({"CCX_HUB": str(hub)} if hub else {})}
    r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    return (r.stdout or r.stderr).strip()[-300:]


def archive_hub(hub: Path, env: dict | None = None) -> int:
    """At the end of an eval: archive every sub-agent session a throwaway hub's runs left, final or not. Nothing will
    continue them, and the person's own hub (whose `ccx archive` would) never sees them: without this they stayed in
    the apps' session lists (seen 2026-10-25). Returns how many sessions were archived. `env`: the unit's own
    environment (scripts/eval/preflight.py), so the sessions are looked for in the homes the unit used."""
    env = {**(env or lead_env()), "CCX_HUB": str(hub)}
    r = subprocess.run([sys.executable, str(ROOT / "ccx.py"), "archive", "--apply"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env)
    try:
        rows = json.loads(r.stdout).get("sessions") or []
    except ValueError:
        return 0
    return sum("-> ok" in str(x.get("action")) or str(x.get("action", "")).startswith("move ") for x in rows)


def append_jsonl(f: Path, row: dict) -> None:
    f.parent.mkdir(parents=True, exist_ok=True)
    with f.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_jsonl(f: Path) -> list[dict]:
    if not f.exists():
        return []
    # split on "\n" only: str.splitlines() also breaks at U+2028, \x1c and the like, which json.dumps(...,
    # ensure_ascii=False) leaves unescaped inside strings (a reviewer's note had one: round 2, 10/25)
    return [json.loads(x) for x in f.read_text(encoding="utf-8").split("\n") if x.strip()]


def spent(rows: list[dict]) -> float:
    return sum((r.get("lead", {}).get("cost_usd") or 0) + (r.get("sub_ae_usd") or 0) for r in rows)


def valid_completion(row: dict) -> bool | None:
    """Delivery evidence, independent of hidden tests and experiment protocol compliance.

    A recorded terminal receipt or successful Claude result event is evidence; an ok/score,
    run id, exit code or protocol flag alone is not. Missing legacy evidence stays Unknown.
    """
    if row.get("error") or row.get("is_error") or any(row.get(k) is True for k in ("timeout", "quota", "env_stop")):
        return False
    if row.get("rc") is not None and row["rc"] not in (0, 2):
        return False
    status, kind, subtype = row.get("status"), row.get("kind"), row.get("subtype")
    if status in ("error", "failed", "timeout", "timed_out", "quota", "quota_exhausted", "env_error",
                  "blocked", "partial", "cancelled", "stopped", "interrupted"):
        return False
    if kind not in (None, "ok", "no_changes", "check_failed", "ok_self_checked"):
        return False
    if subtype is not None and subtype != "success":
        return False
    if row.get("worker_results"):
        states = [valid_completion(r) for r in row["worker_results"]]
        return False if False in states else True if all(s is True for s in states) else None
    if status == "done" or subtype == "success":
        return True
    return None


def _known_usd(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def _unit_spend(row: dict) -> tuple[float | None, bool]:
    """Known subtotal and whether the unit's total cost is incomplete; never add overlapping rollups."""
    total = row.get("usd")
    # R5's exception path historically defaulted usd to zero even without billing evidence.
    default_zero = total == 0 and row.get("error") and not any(
        _known_usd(row.get(k)) for k in ("lead_usd", "ccx_usd"))
    if _known_usd(total) and not default_zero:
        return float(total), False
    components = [row.get("lead_usd"), row.get("ccx_usd")]
    if not _known_usd(components[1]) and any(k in row for k in ("discuss_usd", "worker_usd")):
        components = [row.get(k) for k in ("lead_usd", "discuss_usd", "worker_usd")]
    known = [float(v) for v in components if _known_usd(v)]
    return (sum(known) if known else None), len(known) != len(components)


def _started_cost(rows: list[dict]) -> dict:
    costs = [_unit_spend(r) for r in rows]
    known = [cost for cost, _missing in costs if cost is not None]
    return {"started": len(rows), "spend_all_started": round(sum(known), 6) if known else (0.0 if not rows else None),
            "missing_cost_n": sum(missing for _cost, missing in costs)}


def completion_cost_summary(rows: list[dict], *, right, arm=lambda r: r.get("arm")) -> dict:
    """Additive report on all recorded unit attempts, before any legacy eligibility/pair filter.

    Environment strata never pool their rates. batch_cost includes every stratum for billing only.
    Costs and scores are already unit rollups: do not add children, reviews or component totals twice.
    """
    def metrics(rs):
        states = [(valid_completion(r), right(r)) for r in rs]
        valid = sum(v is True for v, _s in states)
        correct = sum(s is True for _v, s in states)
        valid_right = sum(v is True and s is True for v, s in states)
        costs = _started_cost(rs)
        spend = costs["spend_all_started"]
        return {**costs, "valid_completion": valid, "right": correct,
                "unknown": sum(v is None or s is None for v, s in states),
                "completion_unknown": sum(v is None for v, _s in states),
                "right_unknown": sum(s is None for _v, s in states),
                "valid_over_started": valid / len(rs) if rs else None,
                "right_over_started": correct / len(rs) if rs else None,
                "right_over_valid": correct / valid if valid and correct == valid_right else None,
                "right_valid_completion": valid_right,
                "cost_per_success_all": round(spend / correct, 6) if correct and spend is not None else None}

    def strata(rs):
        return {"clean": metrics([r for r in rs if r.get("env_clean") is True]),
                "unclean": metrics([r for r in rs if r.get("env_clean") is False]),
                "env_unknown": metrics([r for r in rs if r.get("env_clean") is not True and r.get("env_clean") is not False]),
                "batch_cost": _started_cost(rs)}

    arms = sorted({str(arm(r)) for r in rows})
    return {**strata(rows), "by_arm": {a: strata([r for r in rows if str(arm(r)) == a]) for a in arms}}


def sign_test(diffs: list[float]) -> float | None:
    """Two-sided exact sign test p-value for paired differences (ties dropped)."""
    nz = [d for d in diffs if d]
    n, k = len(nz), sum(d > 0 for d in nz)
    if not n:
        return None
    from math import comb
    tail = sum(comb(n, i) for i in range(0, min(k, n - k) + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def boot_ci(xs: list[float], stat=statistics.median, n: int = 4000, seed: int = 7) -> tuple[float, float] | None:
    if len(xs) < 2:
        return None
    rnd = random.Random(seed)
    vals = sorted(stat([rnd.choice(xs) for _ in xs]) for _ in range(n))
    return vals[int(0.025 * n)], vals[int(0.975 * n) - 1]
