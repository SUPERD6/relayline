"""Run an agent CLI headless and read what comes back: the parts every agent shares. What differs per tool (its
command line, its output, where its files are, what it can do) lives in ccx/agents/<name>.py."""
from __future__ import annotations

import json
import locale
import os
import shutil
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path


LAUNCHER_VARS = ("CCX_RUN_ID", "CCX_LEAD_VIEW", "CCX_DISCUSS_ID")


def without_launcher_vars(env: Mapping[str, str]) -> dict[str, str]:
    """Copy an environment without ccx's detached-launch controls.

    These identify the launcher process or select its log output. Inheriting them in checks or agent CLIs
    can bind nested runs to the wrong receipt or change their default output (notably CCX_LEAD_VIEW=full).
    Other settings, including the intentional CCX_DEPTH / CCX_ROLE / CCX_PARENT_RUN identity, stay intact.
    Match case-insensitively on every platform because Windows treats environment names that way.
    """
    return {key: value for key, value in env.items() if key.upper() not in LAUNCHER_VARS}


def decode_output(data: bytes) -> str:
    """Text an agent CLI wrote (its stdout, stderr or an output file), without losing a character (#335).

    UTF-8 first (what Codex, Claude and DeepSeek write). A line that is mostly UTF-8 with a stray bad byte stays
    UTF-8; a line with more bad bytes than valid UTF-8 characters is tried in this machine's locale encoding
    (cp936/GBK on a Chinese Windows, where a CLI that follows the code page writes it). Bytes still undecodable are
    kept visible as \\xNN instead of becoming U+FFFD, which could never be turned back (best effort: a fragment of
    such a line that happens to be valid UTF-8 is shown as that character). Newlines are normalised the way
    text-mode pipes did (\\r\\n and \\r become \\n)."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        loose = data.decode("utf-8", errors="surrogateescape")       # bad bytes become U+DC80..U+DCFF
        bad = sum(1 for c in loose if "\udc80" <= c <= "\udcff")
        good = sum(1 for c in loose if ord(c) > 127) - bad
        text = None
        if good <= bad:
            try:
                text = data.decode(locale.getpreferredencoding(False))
            except (UnicodeDecodeError, LookupError):
                pass
        if text is None:
            text = "".join(f"\\x{ord(c) - 0xDC00:02x}" if "\udc80" <= c <= "\udcff" else c for c in loose)
    return text.replace("\r\n", "\n").replace("\r", "\n")


AUTH_HINTS = ("401", "unauthorized", "not logged in", "login", "authenticate", "api key")
QUOTA_HINTS = ("429", "rate limit", "rate_limit", "usage limit", "quota", "resource_exhausted", "too many requests",
               "limit reached", "credits", "exhausted your capacity")


MODEL_HINTS = ("model is not supported", "is not supported when using", "model_not_found", "model not found",
               "does not exist or you do not have access", "unsupported model", "not available for your",
               "invalid model", "unknown model")


def match_hint(text: str, hints: tuple[str, ...]) -> tuple[str, int] | None:
    """Return the first matching hint and its position, preserving hint-list priority.

    Text hints keep substring matching; numeric hints reject adjacent ASCII letters/digits so ASCII identifiers
    and longer numbers cannot look like HTTP statuses. Non-ASCII text, underscores and punctuation are valid boundaries.
    """
    low = (text or "").lower()
    for hint in hints:
        numeric = hint.isdigit()
        # Keep numeric offsets in the original text; lowercasing can expand a letter (e.g. U+0130).
        source = (text or "") if numeric else low
        i = source.find(hint)
        while i != -1:
            end = i + len(hint)
            if not numeric or (
                (i == 0 or not (source[i - 1].isascii() and source[i - 1].isalnum()))
                and (end == len(source) or not (source[end].isascii() and source[end].isalnum()))
            ):
                return hint, i
            i = source.find(hint, i + 1)
    return None


def classify(text: str) -> str:
    if match_hint(text, MODEL_HINTS):
        return "model"          # this account can't use this model: try another model, not a stronger effort
    if match_hint(text, QUOTA_HINTS):
        return "quota"
    if match_hint(text, AUTH_HINTS):
        return "auth"
    return "error"


def find_bin(agent: str) -> str | None:
    override = os.environ.get(f"CCX_{agent.upper()}_BIN")
    if override:
        return override
    found = shutil.which(agent) or (shutil.which(agent + ".cmd") if os.name == "nt" else None)
    if found or os.environ.get("CCX_NO_LOCATE"):     # tests set it: never find a real CLI by itself
        return found
    try:                                  # not on PATH: the adapter may know where its app keeps it
        from .agents import NAMES, get
        ad = get(agent) if agent in NAMES else None
    except Exception:  # noqa: BLE001
        return None
    return ad.locate() if ad and ad.locate else None


def bin_argv(agent: str) -> list[str]:
    """argv prefix for the agent. Overrides may be 'python path/to/fake.py'."""
    b = find_bin(agent)
    if not b:
        raise FileNotFoundError(
            f"{agent} CLI not found on PATH. Install it or set CCX_{agent.upper()}_BIN.")
    if b.endswith(".py"):
        import sys
        return [sys.executable, b]
    return [b]


@lru_cache(maxsize=None)
def cli_version(agent: str) -> str:
    """First line of `<agent> --version`, "" when unknown. Cached per process."""
    try:
        r = subprocess.run([*bin_argv(agent), "--version"], capture_output=True, text=True, timeout=20,
                           stdin=subprocess.DEVNULL, encoding="utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError):
        return ""
    return (r.stdout.strip().splitlines() or [""])[0] if r.returncode == 0 else ""


@dataclass
class Invocation:
    argv: list[str]
    stdin: str
    cwd: Path
    last_message_file: Path | None = None


@dataclass
class Outcome:
    ok: bool
    session_id: str | None = None
    result: dict | None = None
    raw_text: str = ""
    usage: dict = field(default_factory=dict)
    cost_usd: float | None = None
    error: str | None = None
    auth_problem: bool = False
    kind: str = "ok"            # ok | quota | auth | error | timeout
    retry_after: str | None = None
    permission_denials: int | None = None   # tool calls the CLI refused (Claude's result event); None: not reported
    stalled: bool = False       # kind "timeout" because no stdout line came for stall_sec (run.stall_minutes)
    # #392 timing (None: the process never started, or no stdout line came): when the CLI process started and when
    # its first event (stdout line) arrived, wall clock (UTC ISO 8601); startup_seconds is the gap on a monotonic clock
    started_at: str | None = None
    first_event_at: str | None = None
    startup_seconds: float | None = None


# Usage is normalized to the same four buckets for every agent (billing differs per bucket):
#   input_tokens        fresh, uncached input
#   cache_write_tokens  input written to the prompt cache (Anthropic bills 1.25x input for 5-minute,
#                       2x for 1-hour entries; cache_write_1h_tokens is the 1-hour part)
#   cached_input_tokens input read from the cache (~0.1x input)
#   output_tokens       output incl. reasoning
# OpenAI/Codex reports cached tokens INSIDE input_tokens; Anthropic reports them separately.
def usage_dict(fresh=0, write=0, write_1h=0, cached=0, out=0) -> dict:
    return {"input_tokens": int(fresh), "cache_write_tokens": int(write), "cache_write_1h_tokens": int(write_1h),
            "cached_input_tokens": int(cached), "output_tokens": int(out)}


def _json_from_text(text: str) -> dict | None:
    if not text:
        return None
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`")
        t = t[t.find("{"):] if "{" in t else t
    try:
        v = json.loads(t)
        return v if isinstance(v, dict) else None
    except json.JSONDecodeError:
        a, b = t.find("{"), t.rfind("}")
        if a != -1 and b > a:
            try:
                v = json.loads(t[a:b + 1])
                return v if isinstance(v, dict) else None
            except json.JSONDecodeError:
                return None
    return None




def _first_session_id(agent: str, line: str) -> str | None:
    try:
        ev = json.loads(line)
    except json.JSONDecodeError:
        return None
    if agent == "codex" and ev.get("type") == "thread.started":
        return ev.get("thread_id")
    if agent != "codex":
        return ev.get("session_id")
    return None


def group_flags() -> dict:
    """Popen arguments that start a child in its own process group, so it and everything it starts (a .cmd shim's
    real CLI, the CLI's own tool processes) can be stopped together by kill_tree."""
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def kill_tree(pid: int | None) -> bool:
    """Kill a process started with group_flags() and every process under it: Windows `taskkill /T /F`, POSIX its
    process group (start_new_session makes the group id the child's pid, and the group outlives its leader)."""
    if not pid:
        return False
    try:
        if os.name == "nt":
            r = subprocess.run(["taskkill", "/PID", str(int(pid)), "/T", "/F"], capture_output=True,
                               stdin=subprocess.DEVNULL, timeout=30)
            return r.returncode == 0
        import signal
        os.killpg(int(pid), signal.SIGKILL)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def pid_alive(pid: int | None) -> bool:
    """Is this process still running? (Windows: os.kill(pid, 0) would terminate it, so ask the kernel instead.)"""
    if not pid:
        return False
    if os.name == "nt":
        import ctypes
        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x1000, False, int(pid))          # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        try:
            code = ctypes.c_ulong()
            return bool(k.GetExitCodeProcess(h, ctypes.byref(code))) and code.value == 259   # STILL_ACTIVE
        finally:
            k.CloseHandle(h)
    try:
        os.kill(int(pid), 0)
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def wall_now() -> str:
    """The wall-clock moment, UTC ISO 8601 with milliseconds (a timestamp to read back, never to subtract: durations
    come from a monotonic clock, time.perf_counter, which wall-clock changes cannot move on Windows or POSIX)."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def execute(agent: str, inv: Invocation, timeout: int, env: dict, on_session=None, watch=None,
            watch_every: float = 20.0, on_start=None, stop_file: Path | None = None,
            stall_sec: float = 0) -> tuple[Outcome, str, str]:
    """Run the sub-agent, streaming stdout so the session id is persisted the moment it appears. `watch()` is
    asked every `watch_every` seconds while it runs; a reason it returns stops the run (e.g. a spending cap).
    `on_start(pid)` gets the child's pid at once; `stop_file` appearing (`ccx stop`) stops the run the same way.
    `stall_sec` > 0 (experimental, run.stall_minutes): no stdout line for that long stops the tree too, as a
    timeout marked `stalled`; 0 leaves the run exactly as before."""
    import threading
    import time
    try:
        # bytes, decoded line by line with decode_output (#335): a text-mode pipe with errors="replace" turned any
        # non-UTF-8 byte into U+FFFD for good
        proc = subprocess.Popen(inv.argv, cwd=str(inv.cwd), env=env, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, **group_flags())
    except OSError as e:
        oc = Outcome(ok=False, error=f"could not start {agent}: {e}", kind="error")
        return oc, "", ""
    started_at, t_launch = wall_now(), time.perf_counter()       # #392: launch moment
    first_event: list = []                                         # [(wall, monotonic)] of the first stdout line
    if on_start:
        try:
            on_start(proc.pid)
        except Exception:  # noqa: BLE001 — bookkeeping must never kill the run
            pass
    err_chunks: list[str] = []
    t_err = threading.Thread(target=lambda: err_chunks.extend(decode_output(raw) for raw in proc.stderr),
                             daemon=True)
    t_err.start()
    try:
        # UTF-8 with the platform's line ending, as the former text-mode pipe wrote it
        proc.stdin.write(inv.stdin.replace("\n", os.linesep).encode("utf-8"))
        proc.stdin.close()
    except (BrokenPipeError, OSError):
        pass
    out_lines: list[str] = []
    seen = False
    fired: list[bool] = []

    def _stop():
        if not kill_tree(proc.pid):       # the whole tree: a .cmd shim's child would otherwise run on
            proc.kill()

    def _kill():
        fired.append(True)
        _stop()

    timer = threading.Timer(timeout, _kill)
    timer.start()
    stopped: list[tuple[str, str]] = []      # (kind, why)
    done_ev = threading.Event()

    def _watch():
        import time
        nxt = time.monotonic() + watch_every
        while not done_ev.wait(min(1.0, watch_every) if stop_file else watch_every):
            if stop_file and stop_file.exists():
                stopped.append(("user_stopped", "stopped by `ccx stop`"))
                _stop()
                return
            if not watch or time.monotonic() < nxt:
                continue
            nxt = time.monotonic() + watch_every
            try:
                why = watch()
            except Exception:  # noqa: BLE001 — a failing check never stops the run
                why = None
            if why:
                stopped.append(("over_budget", why))
                _stop()
                return
    if watch or stop_file:
        threading.Thread(target=_watch, daemon=True).start()
    last_event = [time.monotonic()]          # the last stdout line (each is one event of the CLI's JSON stream)

    def _stall():
        while not done_ev.wait(min(1.0, stall_sec / 4)):
            quiet = time.monotonic() - last_event[0]
            if quiet >= stall_sec and not fired and not stopped and not (stop_file and stop_file.exists()):
                stopped.append(("stalled", f"stalled: no event from {agent} for {quiet:.0f}s "
                                           f"(run.stall_minutes = {stall_sec / 60:g})"))
                _stop()
                return
    if stall_sec and stall_sec > 0:
        threading.Thread(target=_stall, daemon=True).start()
    rc = -1
    try:
        for raw in proc.stdout:
            last_event[0] = time.monotonic()
            if not first_event:
                first_event.append((wall_now(), time.perf_counter()))
            line = decode_output(raw)
            out_lines.append(line)
            if not seen and on_session:
                sid = _first_session_id(agent, line.strip())
                if sid:
                    seen = True
                    try:
                        on_session(sid)
                    except Exception:  # noqa: BLE001 — bookkeeping must never kill the run
                        pass
        rc = proc.wait()
    except BaseException:
        _stop()                 # Ctrl+C or a crash in ccx: its own process group no longer gets the signal
        raise
    finally:
        timer.cancel()
        done_ev.set()
    timed_out = bool(fired)
    t_err.join(timeout=5)
    so, se = "".join(out_lines), "".join(err_chunks)
    oc = PARSERS[agent](so, se, rc, inv.last_message_file)
    oc.started_at = started_at
    if first_event:
        oc.first_event_at = first_event[0][0]
        oc.startup_seconds = round(max(0.0, first_event[0][1] - t_launch), 3)
    if timed_out and not oc.ok:
        oc.error, oc.kind = f"timed out after {timeout}s", "timeout"
    if not stopped and stop_file and stop_file.exists() and not oc.ok:
        stopped.append(("user_stopped", "stopped by `ccx stop`"))   # `ccx stop` killed the tree itself
    if stopped and not (stopped[0][0] in ("user_stopped", "stalled") and oc.ok):
        # a stop that came as the sub-agent finished keeps its finished result: nothing done is thrown away
        oc.ok, oc.kind, oc.error = False, *stopped[0]
        if oc.kind == "stalled":
            # kept as a timeout: every rule for a timeout (no climb, resumable, not learned as the model's
            # failure, ccx resume / ui / lanes / merge) applies unchanged; `stalled` says which kind of timeout
            oc.kind, oc.stalled = "timeout", True
    return oc, so, se


# per-agent builders and parsers, from the adapters (imported last: they use the shared pieces above)
from .agents import all_adapters as _adapters  # noqa: E402
from .agents.claude import claude_invocation, parse_claude  # noqa: E402,F401
from .agents.codex import CODEX_KEEP, _codex_kept_settings, codex_invocation, parse_codex  # noqa: E402,F401
from .agents.gemini import GEMINI_P, gemini_invocation, parse_gemini  # noqa: E402,F401

BUILDERS = {a.name: a.build for a in _adapters()}
PARSERS = {a.name: a.parse for a in _adapters()}
TESTED_VERSIONS = {a.name: a.tested_version for a in _adapters()}
