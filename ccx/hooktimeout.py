"""L4: a session hook (`ccx mem delta`, `ccx turn`, `ccx lead --hint`) preserves complete hints at its time limit and
exits 0, so a slow disk or a big journal never holds up the lead's start or its turn. The command runs in a worker
thread with its output caught; past the limit the process leaves with os._exit(0) (works the same on Windows,
no signals) and the hub gets one line in ccx/hook-timeouts.jsonl: the command, how long it had run, and the step it
was in. `[hooks] timeout_s` sets the limit (0 = no limit); `ccx doctor` shows the recent count."""
from __future__ import annotations

import io
import json
import os
import sys
import threading
import time
from datetime import datetime, timedelta, timezone

DEFAULT_S = 2.0


def hook_name(argv: list[str]) -> str | None:
    """The hook command in this argv, or None for any other command."""
    a = [x for x in argv if x]
    if a[:1] == ["turn"]:
        return "turn"
    if a[:2] == ["mem", "delta"]:
        return "mem delta"
    if a[:1] == ["lead"] and "--hint" in a:
        return "lead --hint"
    return None


def log_file(p):
    return p.state / "hook-timeouts.jsonl"


def limit(p) -> float:
    if (env := os.environ.get("CCX_HOOK_TIMEOUT_S")) is not None:     # tests, and a quick check by hand
        try:
            return float(env)
        except ValueError:
            pass
    try:
        from .config import load_config
        return float(((load_config(p).get("hooks") or {}).get("timeout_s", DEFAULT_S)))
    except Exception:  # noqa: BLE001 — a broken config must not break the hook either
        return DEFAULT_S


def _step(thread: threading.Thread) -> str:
    """Where the worker was when time ran out: its innermost ccx frame (module:function:line)."""
    frame = sys._current_frames().get(thread.ident)
    where = ""
    while frame is not None:
        mod = frame.f_globals.get("__name__", "")
        if mod.startswith("ccx.") and mod != __name__:
            where = f"{mod}:{frame.f_code.co_name}:{frame.f_lineno}"
            break
        frame = frame.f_back
    return where or "?"


def run(name: str, fn, p, timeout: float | None = None, *, clock=time.monotonic) -> int:
    """Run fn() (the command) under the hook limit; returns its exit code, or leaves the process after the limit."""
    timeout = limit(p) if timeout is None else timeout
    if timeout <= 0:
        return fn()
    out, err = io.StringIO(), io.StringIO()
    result: dict = {}
    from .hookbudget import Budget, Exhausted, using
    budget = Budget(timeout, clock)

    def work():
        try:
            with using(budget):
                result["rc"] = fn()
        except Exhausted:
            result["rc"] = 0
            result["exhausted"] = True
        except BaseException as e:  # noqa: BLE001 — carried back to the main thread
            result["exc"] = e

    real_out, real_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    t0 = time.monotonic()
    t = threading.Thread(target=work, name="ccx-hook", daemon=True)
    try:
        t.start()
        t.join(timeout)
    except BaseException:
        sys.stdout, sys.stderr = real_out, real_err
        raise
    if t.is_alive():                   # output stays caught: whatever the worker prints now goes nowhere
        real_out.write(budget.ready or out.getvalue())
        real_out.flush()
        rec = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "cmd": name,
               "elapsed_s": round(time.monotonic() - t0, 2), "limit_s": timeout, "step": _step(t)}
        try:
            log_file(p).parent.mkdir(parents=True, exist_ok=True)
            with open(log_file(p), "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except OSError:
            pass
        os._exit(0)                    # the worker may sit in a read; nothing waits for it
    sys.stdout, sys.stderr = real_out, real_err
    real_out.write(budget.ready if result.get("exhausted") else out.getvalue())
    real_err.write(err.getvalue())
    if "exc" in result:
        raise result["exc"]
    return result.get("rc", 0)


def recent(p, days: int = 7) -> list[dict]:
    try:
        lines = log_file(p).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    since = datetime.now(timezone.utc) - timedelta(days=days)
    out = []
    for line in lines:
        try:
            rec = json.loads(line)
            if datetime.fromisoformat(rec["at"]) >= since:
                out.append(rec)
        except (ValueError, KeyError, TypeError):
            continue
    return out


def doctor_row(p, days: int = 7) -> tuple[str, str]:
    recs = recent(p, days)
    lim = limit(p)
    if not recs:
        return "ok", f"none in {days} days (limit {lim:g}s, [hooks] timeout_s)"
    by: dict[str, int] = {}
    for r in recs:
        by[r.get("cmd", "?")] = by.get(r.get("cmd", "?"), 0) + 1
    last = recs[-1]
    return "WARN", (f"{len(recs)} in {days} days (" + ", ".join(f"{k} {v}" for k, v in sorted(by.items()))
                    + f"); last {last.get('cmd')} at {last.get('step')} after {last.get('elapsed_s')}s. "
                    f"Limit {lim:g}s: `ccx config set hooks.timeout_s N`; log {log_file(p)}")
