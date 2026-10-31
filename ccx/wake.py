"""Wake the lead when a background run lands (P0-11 item 1): one line, pushed, instead of the lead polling.

A lead that starts `ccx run --bg` (and does not wait in the same call) used to learn the result only by asking:
`ccx show <id> --wait` or `--any`, each a lead request that re-reads its whole conversation. Now the detached run,
when it is finished, sends the lead its recap line itself, by the first of these that works:

1. Claude Code's own inbox (cross-session messaging, Claude Code 2.1.224+; native Windows 2.1.234+). Claude Code
   exports CLAUDE_CODE_MESSAGING_SOCKET and CLAUDE_CODE_MESSAGING_TOKEN to the Bash commands it runs, and the
   detached child inherits them, so it posts into the very session that started it, as that session's own child
   (verified by the token). An idle session starts a turn with it; a busy one reads it between tool calls.
   Wire, checked on 2.1.309 on native Windows (2026-10-31, desktop app, bypass mode: delivered): one connection,
   line 1 `{"type":"auth","token":...}`, line 2 `{"type":"user","message":{"role":"user","content":TEXT}}`.
   The docs give only the auth line; three other shapes were dropped without a word. The docs say a message the
   session verifies as its own child's is delivered unless crossSessionInbound is set; an explicit `hold` keeps it
   (no expiry), and only a default-held message expires after 5 minutes (dialogExpiry). So a sent line is not
   also left for the hook; `[wake] trust_socket = false` leaves it there too (a held or expired line then still
   reaches the lead on its next turn, at the price of seeing a delivered one twice).
2. The per-turn hook (`ccx turn`, UserPromptSubmit in Claude Code and Codex): a pending notice is a file under
   <state>/wake/, shown once, on the lead's next turn, then removed.
3. Polling (`ccx show <id> --wait` / `--any`) stays as it was: the fallback for everything else.

A lead already waiting on the run (`ccx run --bg --wait N`, `ccx show <id> --wait`) gets the result on stdout, so
the notice is skipped then: a waiter leaves a `waiting.<pid>` file in the run's folder while it waits.

Off with `ccx config set wake.enabled false` ([wake] in tiers.toml). Nothing here changes what a run does.
"""
from __future__ import annotations

import json
import os
import socket
import time
from contextlib import contextmanager
from pathlib import Path

SOCK = "CLAUDE_CODE_MESSAGING_SOCKET"
TOKEN = "CLAUDE_CODE_MESSAGING_TOKEN"
MAX_LINE = 600                  # one line: the recap and where the rest is
KEEP_SEC = 24 * 3600            # a pending notice older than this is dropped unseen (the lead moved on)
TIMEOUT = 5.0


def enabled(cfg: dict) -> bool:
    return bool((cfg.get("wake") or {}).get("enabled", True))


def _dir(p) -> Path:
    return p.state / "wake"


@contextmanager
def waiting(p, run_id: str):
    """Mark `run_id` as waited on by this process for as long as the block runs (the run then sends no notice)."""
    f = p.runs / run_id / f"waiting.{os.getpid()}"
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(str(time.time()), encoding="utf-8")
    except OSError:
        f = None
    try:
        yield
    finally:
        if f is not None:
            try:
                f.unlink()
            except OSError:
                pass


def _waited_on(p, run_id: str) -> bool:
    from .runners import pid_alive
    try:
        marks = list((p.runs / run_id).glob("waiting.*"))
    except OSError:
        return False
    for m in marks:
        try:
            if pid_alive(int(m.suffix[1:])):
                return True
        except ValueError:
            continue
    return False


def text(record: dict, recap: str) -> str:
    """The one line the lead gets. Starts with the board mark: the per-turn hook knows a person did not type it."""
    from .board import MARK
    line = " ".join(str(recap or "").split())
    if len(line) > MAX_LINE:
        line = line[: MAX_LINE - 3] + "..."
    return (f"{MARK}: the background ccx run {record['run_id']} you started has finished] {line} "
            f"(this is ccx's notice, not the person; details: `ccx show {record['run_id']}`)")


def _send_socket(addr: str, token: str | None, msg: str) -> None:
    """Post one user message into the Claude Code session listening at `addr` (named pipe or Unix socket)."""
    lines = (json.dumps({"type": "auth", "token": token}) + "\n" if token else "") + \
        json.dumps({"type": "user", "message": {"role": "user", "content": msg}}, ensure_ascii=False) + "\n"
    data = lines.encode("utf-8")
    if addr.startswith("\\\\") or os.name == "nt":
        with open(addr, "r+b", buffering=0) as f:        # a Windows named pipe opens like a file
            f.write(data)
        return
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)  # type: ignore[attr-defined]
    try:
        s.settimeout(TIMEOUT)
        s.connect(addr)
        s.sendall(data)
    finally:
        s.close()


def _pending(p, record: dict, line: str) -> Path:
    d = _dir(p)
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{record['run_id']}.json"
    f.write_text(json.dumps({"run_id": record["run_id"], "ts": time.time(), "lead": record.get("caller"),
                             "lead_session": record.get("lead_session"), "cwd": record.get("cwd"), "line": line},
                            ensure_ascii=False), encoding="utf-8")
    return f


def notify(p, cfg: dict, record: dict, recap: str, env: dict | None = None, send=_send_socket) -> dict:
    """Called by the detached child of `--bg` once the run (and any fix round) is finished. Returns what it did,
    kept in the run's folder as wake.json (for `ccx show --full` and the measurement); never raises."""
    env = os.environ if env is None else env
    out: dict = {"ts": time.time()}
    try:
        if not enabled(cfg):
            out["via"] = "off"
        elif _waited_on(p, record["run_id"]):
            out["via"] = "waiter"                # the lead is reading stdout right now
        else:
            line = text(record, recap)
            via = []
            if env.get(SOCK) and record.get("caller") == "claude":
                try:
                    send(env[SOCK], env.get(TOKEN), line)
                    via.append("claude-inbox")
                except OSError as e:
                    out["socket_error"] = repr(e)[:200]
            trust = bool((cfg.get("wake") or {}).get("trust_socket", True))
            if not (via and trust):
                _pending(p, record, line)
                via.append("hook")
            out["via"] = "+".join(via)
    except Exception as e:  # noqa: BLE001 — a notice must never fail the run
        out["error"] = repr(e)[:300]
    try:
        (p.runs / record["run_id"] / "wake.json").write_text(json.dumps(out), encoding="utf-8")
    except OSError:
        pass
    return out


def take(p, agent: str, session: str | None, cwd: Path | None = None) -> list[str]:
    """For the per-turn hook: the pending notices for this lead, removed as they are shown (once). A notice for
    another session is left alone; one without a session goes to the first lead of its vendor in its folder."""
    d = _dir(p)
    if not d.is_dir():
        return []
    out = []
    now = time.time()
    for f in sorted(d.glob("*.json")):
        try:
            n = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if now - float(n.get("ts") or 0) > KEEP_SEC:
            _rm(f)
            continue
        if n.get("lead") != agent:
            continue
        if n.get("lead_session"):
            if n["lead_session"] != session:
                continue
        elif cwd is not None and n.get("cwd") and Path(n["cwd"]).resolve() != Path(cwd).resolve():
            continue
        out.append(str(n.get("line") or ""))
        _rm(f)
    return [x for x in out if x]


def _rm(f: Path) -> None:
    try:
        f.unlink()
    except OSError:
        pass
