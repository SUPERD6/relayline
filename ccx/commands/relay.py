"""Opt-in relay capture and explicit continuation commands."""
from __future__ import annotations

import json
from pathlib import Path
import sys

from ..config import load_config, relay_enabled
from .. import quota_signals, relay, relay_state as state
from .common import _out


def command(a) -> int:
    cfg = load_config()
    if a.action == "capture" and a.hook and not relay_enabled(cfg):
        return 0  # stale installed hooks are silent when disabled
    relay.require_enabled(cfg)
    if a.action == "capture":
        event = json.load(sys.stdin) if a.hook else {}
        evidence = quota_signals.identify(event) if a.hook else {"kind": "unknown", "source": "manual"}
        if a.hook and evidence["kind"] != "quota":
            return 0
        cwd = state.root(Path(event.get("cwd") or a.cwd).resolve())
        session = str(event.get("session_id") or a.session_id or "Unknown")
        context_file = state.context_path(cwd, session)
        context = json.loads(context_file.read_text(encoding="utf-8")) if context_file.exists() else {}
        for name in ("goal", "progress", "next_step"):
            if getattr(a, name) is not None:
                context[name] = getattr(a, name)
        if not a.hook and session != "Unknown":
            state.atomic_json(context_file, context)
        path, packet = state.capture(cwd, a.source, session, evidence, context)
        notice = {"packet": packet["id"], "message": "Quota relay captured; stop the old session before continuing.",
                  "continue_command": packet["continue_command"]}
        state.atomic_json(path.with_suffix(".notification.json"), notice)
        if a.hook:
            # Documented exception to ignored StopFailure output. Durable notice is authoritative.
            _out({"terminalSequence": "\a", "relay": notice})
        else:
            _out({"path": str(path), **notice})
        return 0
    out = relay.continue_packet(state.root(Path(a.cwd).resolve()), a.packet, a.to, a.budget_seconds,
                                a.old_stopped, a.launch)
    _out(out)
    return 0 if out["state"] == "prepared" or (out["state"] == "exited" and out["exit_code"] == 0) else 2


def register(sub) -> None:
    ap = sub.add_parser("relay", help="experimental opt-in quota handoff (no transparent takeover)")
    actions = ap.add_subparsers(dest="action", required=True)
    capture = actions.add_parser("capture", help="capture workspace metadata; no private transcript is read")
    capture.add_argument("--hook", action="store_true", help="read Claude StopFailure JSON on stdin")
    capture.add_argument("--cwd", default=".")
    capture.add_argument("--source", choices=("claude", "codex"), default="claude")
    capture.add_argument("--session-id", help="save context for this source session's later hook")
    for key in ("goal", "progress", "next-step"):
        capture.add_argument("--" + key)
    cont = actions.add_parser("continue", help="prepare another vendor's new lead; --launch starts it")
    cont.add_argument("packet", help="packet id from capture")
    cont.add_argument("--cwd", default=".")
    cont.add_argument("--to", required=True, choices=("codex", "claude"))
    cont.add_argument("--budget-seconds", required=True, type=float, help="hard wall-time budget; not a dollar cap")
    cont.add_argument("--old-stopped", action="store_true", help="attest old session and native auto-resume are stopped")
    cont.add_argument("--launch", action="store_true", help="explicitly start supervised codex exec / claude -p")
    for parser in (ap, capture, cont):
        parser.set_defaults(fn=command)
