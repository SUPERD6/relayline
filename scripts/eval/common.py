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
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from ccx import ledger  # noqa: E402
from ccx.config import Paths, paths  # noqa: E402
from ccx.runners import bin_argv, group_flags, kill_tree  # noqa: E402

CCX = f'python "{ROOT.as_posix()}/ccx.py"'
HIDDEN = "test_zz_hidden_eval.py"
# Variables that would tie a child Claude to the session that started this script (same list as ccx's
# delegate._child_env, plus the desktop app's messaging channel).
PARENT_VARS = ("CLAUDECODE", "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_REMOTE_SESSION_ID", "CLAUDE_EFFORT",
               "CLAUDE_CODE_EFFORT_LEVEL", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_CHILD_SESSION", "CLAUDE_PID", "CLAUDE_CODE_HOST_SESSION_ID",
               "CLAUDE_CODE_MESSAGING_SOCKET", "CLAUDE_CODE_MESSAGING_TOKEN", "CCX_LEAD_SESSION", "CCX_DEPTH",
               "CCX_ROLE", "CCX_PARENT_RUN")


_LIVE: set[subprocess.Popen] = set()        # run_tree children still running (any thread)
_LIVE_LOCK = threading.Lock()
_STOPPING = threading.Event()                # set by stop_running(): no run_tree starts or returns normally after it


def _preflight():
    """preflight lists and kills processes on POSIX; it imports this module, so it is imported when first needed
    (before a child starts, so the cleanup path never fails on an import)."""
    import preflight
    return preflight


def _end_tree(proc: subprocess.Popen, PF) -> None:
    """Kill proc and everything under it. On POSIX the descendants are listed first: kill_tree() takes the child's
    process group, and ccx starts its CLI in a group of its own. Windows: taskkill /T walks the tree itself."""
    below = None
    if PF is not None:
        procs = PF.snapshot()
        if procs is None:
            print(f"run_tree: could not list processes; descendants of pid {proc.pid} in a process group of "
                  "their own (e.g. the CLI ccx started) may not have been killed", file=sys.stderr)
        below = sorted(PF.family(procs, proc.pid)[1]) if procs else []
    if not kill_tree(proc.pid):
        proc.kill()
    if below:
        PF.kill(below)


def run_tree(argv: list[str], *, timeout: float, cwd: Path | str | None = None, env: dict | None = None,
             input: str | None = None, errors: str = "replace") -> subprocess.CompletedProcess:
    """subprocess.run(capture_output=True, text=True, encoding="utf-8"), but a timeout (or Ctrl+C) ends the whole
    process tree, not only the direct child (issues #329, #332: ccx and the CLI it started ran on after a timeout).
    The child starts with ccx's group_flags() and is stopped with ccx's kill_tree() (see _end_tree). The exception is
    raised again; a TimeoutExpired carries the output read so far as text in .stdout and .stderr, as subprocess.run's
    does (None or bytes if a descendant that escaped the kill still holds the pipes after 30 s; callers accept all
    three). stdin is `input` when given, else DEVNULL (subprocess.run inherited it; every caller passes its prompt as
    an argument or as `input`). The child no longer gets the terminal's Ctrl+C (its own group): a run_tree in a worker
    thread is ended by stop_running(), which map_stopping() calls on Ctrl+C; a call that finishes just as
    stop_running() runs raises KeyboardInterrupt too, so its result is not recorded."""
    if _STOPPING.is_set():
        raise KeyboardInterrupt("run_tree: stopped")
    PF = _preflight() if os.name != "nt" else None
    proc = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.PIPE if input is not None else subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                            errors=errors, **group_flags())
    with _LIVE_LOCK:
        _LIVE.add(proc)
    try:
        if _STOPPING.is_set():                  # stop_running() came between the check above and the add
            raise KeyboardInterrupt("run_tree: stopped")
        out, err = proc.communicate(input, timeout=timeout)
        if _STOPPING.is_set():                  # ended by stop_running(): not a normal result
            raise KeyboardInterrupt("run_tree: stopped")
    except BaseException as exc:
        if not (_STOPPING.is_set() and proc.returncode is not None):    # else stop_running() ended it: the pid is
            _end_tree(proc, PF)                                          # reaped, POSIX may already reuse it
        try:
            rest = proc.communicate(timeout=30)
            if isinstance(exc, subprocess.TimeoutExpired):
                exc.stdout, exc.stderr = rest
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
        raise
    finally:
        with _LIVE_LOCK:
            _LIVE.discard(proc)
    return subprocess.CompletedProcess(argv, proc.returncode, out, err)


def stop_running() -> int:
    """End every run_tree tree still running, in any thread, and make later run_tree calls raise KeyboardInterrupt.
    Returns how many trees were ended."""
    _STOPPING.set()
    with _LIVE_LOCK:
        procs = list(_LIVE)
    PF = _preflight() if os.name != "nt" else None
    for proc in procs:
        _end_tree(proc, PF)
    return len(procs)


def map_stopping(ex, fn, items) -> list:
    """list(ex.map(fn, items)) for a ThreadPoolExecutor whose workers call run_tree: on Ctrl+C the queued items are
    dropped and the running trees ended (stop_running), so leaving the `with` block does not wait for them. Their
    children run in groups of their own and no longer get the terminal's Ctrl+C (issue #332 review).
    The loop waits in time.sleep, holding no lock (issue #373): concurrent.futures.wait takes each future's lock, and a
    Ctrl+C landing while that lock is held left it held for good, so the worker finishing that future blocked in
    set_result and the executor's shutdown(wait=True) never returned."""
    finished, futures = set(), []
    def run(i, x):                              # in the worker: marks item i ended, no lock taken by the main thread
        try:
            return fn(x)
        finally:
            finished.add(i)
    try:
        for i, x in enumerate(items):           # inside the try: a Ctrl+C while submitting also drops the queue
            futures.append(ex.submit(run, i, x))
        out = []
        for i, f in enumerate(futures):         # in order, the first error raised first, as ex.map
            while i not in finished or not f.done():    # short sleeps: Ctrl+C gets through on Windows too
                time.sleep(.05)
            out.append(f.result())
        return out
    except KeyboardInterrupt:
        ex.shutdown(wait=False, cancel_futures=True)
        stop_running()
        raise
    except BaseException:
        for f in futures:                       # as ex.map: the ones not started yet are dropped
            f.cancel()
        raise


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
        r = run_tree(argv, input=prompt, cwd=cwd, env=lead_env(), timeout=timeout)
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

    A terminal receipt with a normal kind or successful Claude result event is evidence; an ok/score,
    run id, exit code or protocol flag alone is not. Missing legacy evidence stays Unknown.
    """
    # P13 records protocol violations as errors too, after the worker may have delivered.
    # Only these known protocol errors defer to its saved receipts; infrastructure errors still stop delivery.
    protocol_error = row.get("error") in (
        "RuntimeError: lead must dispatch exactly one ccx run without edits or retries",
        "RuntimeError: discussion protocol not met",
    ) and bool(row.get("worker_results"))
    if row.get("error") and not protocol_error:
        return False
    if row.get("is_error") or any(row.get(k) is True for k in ("timeout", "quota", "env_stop")):
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
    if subtype == "success":
        return True
    if status == "done" and kind is not None:
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
    missing = sum(missing for _cost, missing in costs)
    return {"started": len(rows), "spend_all_started": round(sum(known), 6) if known else (0.0 if not rows else None),
            "missing_cost_n": missing, "spend_complete": missing == 0 and bool(known)}


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
