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
The notice is about the run the lead started (the id `--bg` printed), however it ended: its final result after any
review fix round, a refusal or "not delegated" record, or a crash that left no record.

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


def text(run_id: str, recap: str) -> str:
    """The one line the lead gets. Starts with the board mark: the per-turn hook knows a person did not type it."""
    from .board import MARK
    line = " ".join(str(recap or "").split())
    if len(line) > MAX_LINE:
        line = line[: MAX_LINE - 3] + "..."
    return (f"{MARK}: the background ccx run {run_id} you started has finished] {line} "
            f"(this is ccx's notice, not the person; details: `ccx show {run_id}`)")


def _send_socket(addr: str, token: str | None, msg: str) -> None:
    """Post one user message into the Claude Code session listening at `addr` (named pipe or Unix socket), within
    TIMEOUT seconds: an inbox nobody reads must not keep the finished run alive."""
    lines = (json.dumps({"type": "auth", "token": token}) + "\n" if token else "") + \
        json.dumps({"type": "user", "message": {"role": "user", "content": msg}}, ensure_ascii=False) + "\n"
    data = lines.encode("utf-8")
    if os.name == "nt":
        import threading
        err: list = []

        def write():
            try:
                with open(addr, "r+b", buffering=0) as f:    # a Windows named pipe opens like a file
                    f.write(data)
            except Exception as e:  # noqa: BLE001 — raised below as the send's failure
                err.append(e)
        t = threading.Thread(target=write, daemon=True)
        t.start()
        t.join(TIMEOUT)
        if t.is_alive():
            raise OSError(f"the inbox did not take the message within {TIMEOUT:g} s")
        if err:
            raise OSError(repr(err[0])[:200])
        return
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)  # type: ignore[attr-defined]
    try:
        s.settimeout(TIMEOUT)
        s.connect(addr)
        s.sendall(data)
    finally:
        s.close()


def _vendor(who: str | None) -> str:
    """The tool the lead runs in, whose turn hook shows the notice: a provider through Claude Code (deepseek, kimi,
    ...) is Claude Code's; `*-codex` is Codex's; dsh is deepseek (as `ccx turn --as dsh` names it)."""
    from .board import vendor_of
    c = (who or "").split(":", 1)[0].strip().lower()
    if c == "codex" or c.endswith("-codex"):
        return "codex"
    if c in ("dsh", "", "user", "unknown"):
        return vendor_of(c)
    return "claude"


def _pending(p, run_id: str, lead: str | None, session: str | None, cwd: str | None, line: str) -> None:
    d = _dir(p)
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{run_id}.json").write_text(json.dumps({"run_id": run_id, "ts": time.time(), "lead": _vendor(lead),
                                                  "lead_session": session, "cwd": cwd, "line": line},
                                                 ensure_ascii=False), encoding="utf-8")


def notify(p, cfg: dict, run_id: str, recap: str, lead: str | None, session: str | None = None,
           cwd: str | None = None, env: dict | None = None, send=_send_socket) -> dict:
    """Tell the lead that started background run `run_id` its one-line result. `lead` is the caller under any name
    (claude, deepseek on Claude Code, dsh, codex), `session` its conversation, `cwd` the folder it started the run
    in. The inbox is used whenever the run inherited one (only Claude Code exports it), whatever the caller is
    called. Returns what it did, also kept in the run's folder as wake.json; never raises."""
    env = os.environ if env is None else env
    out: dict = {"ts": time.time()}
    try:
        if not enabled(cfg):
            out["via"] = "off"
        elif _waited_on(p, run_id):
            out["via"] = "waiter"                # the lead is reading stdout right now
        else:
            line = text(run_id, recap)
            via = []
            if env.get(SOCK):
                try:
                    send(env[SOCK], env.get(TOKEN), line)
                    via.append("claude-inbox")
                except Exception as e:  # noqa: BLE001 — any failure: the hook copy below still reaches the lead
                    out["socket_error"] = repr(e)[:200]
            if not (via and bool((cfg.get("wake") or {}).get("trust_socket", True))):
                _pending(p, run_id, lead, session, cwd, line)
                via.append("hook")
            out["via"] = "+".join(via)
    except Exception as e:  # noqa: BLE001 — a notice must never fail the run
        out["error"] = repr(e)[:300]
    try:
        (p.runs / run_id / "wake.json").write_text(json.dumps(out), encoding="utf-8")
    except OSError:
        pass
    return out


def final_line(p, run_id: str, error: BaseException | None = None) -> str:
    """The recap of what became of background run `run_id`: the last record of its review fix round chain, a
    refusal / not-delegated record, or the crash that left none."""
    from . import ledger
    from .commands.records import follow_chain
    from .delegate import compact, recap
    try:
        rec, _ = follow_chain(p, ledger.load_run(p, run_id))
    except Exception:  # noqa: BLE001 — no readable record: said below
        rec = None
    if not rec or rec.get("state") == "running":
        why = f": {error!r}"[:300] if error is not None else ""
        return f"ccx run {run_id}: ended without a result{why}; see `ccx show {run_id} --full` and its bg.log"
    try:
        return recap(rec, compact(rec))
    except Exception:  # noqa: BLE001 — a refusal / not-delegated record is not a run's: say what it says
        said = " ".join(str(rec.get("error") or rec.get("summary") or rec.get("advice") or "").split())[:400]
        return (f"ccx run {run_id}: ok={str(bool(rec.get('ok'))).lower()} {said}; next: ccx show {run_id}")


@contextmanager
def after_bg(p, run_id: str):
    """Around the detached child of `--bg`: when it ends, however it ends, the lead that started it is told once."""
    from .commands.common import lead_identity, lead_session_id
    lead = lead_identity()
    session = lead_session_id(lead)          # read before run() changes the environment; a resume's record has none
    cwd = os.getcwd()                         # the lead's folder (the run's own may be a worktree)
    err: BaseException | None = None
    try:
        yield
    except BaseException as e:
        err = e
        raise
    finally:
        try:
            from . import ledger
            from .config import load_config
            try:
                lead = ledger.load_run(p, run_id).get("caller") or lead     # `--from` names it, when given
            except Exception:  # noqa: BLE001 — no record: the environment's guess
                pass
            crash = None if isinstance(err, SystemExit) else err
            notify(p, load_config(p), run_id, final_line(p, run_id, crash), lead, session, cwd)
        except Exception:  # noqa: BLE001 — the notice never changes the run's own outcome
            pass


def take(p, agent: str, session: str | None, cwd: Path | None = None) -> list[str]:
    """For the per-turn hook: the pending notices for this lead, removed as they are shown (once). A notice for
    another session is left alone; one without a session goes to the first lead of its vendor in its folder. A file
    that cannot be read is removed, so it never costs a turn its other lines."""
    d = _dir(p)
    if not d.is_dir():
        return []
    out = []
    now = time.time()
    from .board import vendor_of
    me = vendor_of(agent)
    for f in sorted(d.glob("*.json")):
        try:
            n = json.loads(f.read_text(encoding="utf-8"))
            if not isinstance(n, dict) or now - float(n.get("ts") or 0) > KEEP_SEC:
                raise ValueError("stale, or not a notice")
        except (OSError, ValueError, TypeError):
            _rm(f)
            continue
        if n.get("lead") != me:                 # stored as the tool it runs in (_vendor)
            continue
        if n.get("lead_session"):
            if n["lead_session"] != session:
                continue
        elif cwd is not None and n.get("cwd"):
            try:
                if Path(n["cwd"]).resolve() != Path(cwd).resolve():
                    continue
            except (OSError, ValueError):
                continue
        if _rm(f):                            # shown only when it could be taken away (else it would show every turn)
            out.append(str(n.get("line") or ""))
    return [x for x in out if x]


def _rm(f: Path) -> bool:
    try:
        f.unlink()
        return True
    except OSError:
        return False
