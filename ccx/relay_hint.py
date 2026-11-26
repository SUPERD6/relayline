"""Session-start line about an unfinished relay packet (#523). Opt-in: only when relay.enabled is true.

`ccx mem delta` (the SessionStart hook of both tools) calls `pending_line`. It only looks: it never continues,
launches or changes a packet; the person still types `ccx relay continue` after the old session is stopped."""
from __future__ import annotations

import json
import re
from pathlib import Path

PENDING_STATES = ("quota_stopped", "rate_limit_unconfirmed", "captured")
_ID = re.compile(r"[0-9a-f]{32}\.json")
MAX_PACKETS = 50                    # a hook must stay fast: look at the newest few only


def pending(root: Path, me: str | None) -> dict | None:
    """The newest packet of this workspace that came from the *other* tool and has no continue record yet."""
    if me not in ("claude", "codex"):               # a DeepSeek-behind-Claude lead or no --as is not told
        return None
    folder = root / ".ccx" / "relay"
    if not folder.is_dir():
        return None
    files = sorted((f for f in folder.iterdir() if _ID.fullmatch(f.name)),
                   key=lambda f: f.stat().st_mtime, reverse=True)[:MAX_PACKETS]
    best = None
    for f in files:
        try:
            packet = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(packet, dict) or packet.get("id") != f.stem or packet.get("state") not in PENDING_STATES:
            continue
        if packet.get("source") == me or packet.get("source") not in ("claude", "codex"):
            continue                                  # only the other tool continues
        if any(folder.glob(f.stem + ".continue-*.json")):
            continue                                  # already handled once
        try:
            if Path(str(packet.get("workspace"))).resolve() != root.resolve():
                continue
        except OSError:
            continue
        if best is None or str(packet.get("captured_at")) > str(best.get("captured_at")):
            best = packet
    return best


def pending_line(cwd: Path, me: str | None, p=None) -> str:
    """One line (or "" when relay is off, no workspace, or nothing waits). Never raises."""
    try:
        from .config import load_config, relay_enabled
        from . import relay_state as state
        from .lang import say
        if not relay_enabled(load_config(p) if p else load_config()):
            return ""
        packet = pending(state.root(cwd, timeout=2), me)
        if not packet:
            return ""
        goal = " ".join(str(packet.get("goal") or "Unknown").split())[:120]
        return say("hint_relay_pending", p, id=packet["id"], goal=goal, cmd=packet.get("continue_command") or "")
    except Exception:  # noqa: BLE001 — never break session start
        return ""
