"""Relay accounting (#524): one ledger row for the new lead's usage after `ccx relay continue --launch`, one for the
old lead's session when its usage can be read. Only what a CLI itself reported is written; anything else is the
string "Unknown" (never an estimate), and a failure here never changes the launch result."""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

OLD_LOOKBACK = 7 * 86400     # the old lead's usage is read from the session files this far before the packet's capture


def child_usage(target: str, stdout: str) -> dict | None:
    """The usage the child CLI printed on its own stdout (Claude: the final `result` event; Codex: `turn.completed`
    events), as the normalized four-bucket dict; None when it printed none. Same parsers as a sub-agent run."""
    from .runners import parse_claude, parse_codex      # runners first: importing the agent modules alone is circular
    events = []
    for line in stdout.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    if target == "codex":
        if not any(e.get("type") == "turn.completed" and isinstance(e.get("usage"), dict) for e in events):
            return None
        return parse_codex(stdout, "", 0, None).usage
    if not any(e.get("type") == "result" and isinstance(e.get("usage"), dict) for e in events):
        return None
    return parse_claude(stdout, "", 0).usage


def _row(side: str, agent: str, packet: str, session: str, cwd, usage: dict | None, reason: str = "",
         model: str = "", cfg: dict | None = None) -> dict:
    row = {"type": "relay_usage", "ts": time.time(), "side": side, "agent": agent, "packet": packet,
           "session": session, "cwd": str(cwd)}
    if usage is None:
        row.update(usage="Unknown", reason=reason)
    else:
        row["usage4"] = usage
        if side == "old":
            row["window_days"] = OLD_LOOKBACK // 86400     # a longer session is cut off here: a lower bound
        if model:
            row["model"] = model
        if cfg is not None:
            from . import ledger
            row["quota_units"] = ledger.quota_units(cfg, agent, model, usage)
    return row


def _captured_ts(packet: dict) -> float | None:
    try:
        return datetime.fromisoformat(str(packet["captured_at"]).replace("Z", "+00:00")).timestamp()
    except (KeyError, ValueError):
        return None


def old_lead_usage(packet: dict) -> tuple[dict | None, str, str]:
    """-> (usage, model, reason). Read from the old lead's own session files, only when the packet names the session."""
    session = str(packet.get("source_session") or "")
    if not session or session == "Unknown":
        return None, "", "old lead's session id is Unknown"
    end = _captured_ts(packet)
    if end is None:
        return None, "", "packet capture time is Unknown"
    from . import usage as usage_mod
    w = usage_mod.window_usage(packet["source"], end - OLD_LOOKBACK, end, set(), session)
    if not w["messages"]:
        return None, "", "no turns of that session found in the CLI's own session files"
    return w["usage"], w.get("model") or "", ""


def record(cwd: Path, packet: dict, target: str, stdout_log: Path, out: dict) -> None:
    """Append the two ledger rows and note the result in the launch record (`out["usage_ledger"]`)."""
    try:
        from . import ledger
        from .config import Paths, hub_dir, load_config
        p = Paths(hub_dir())
        cfg = load_config(p)
        rows = []
        new = child_usage(target, stdout_log.read_text(encoding="utf-8", errors="replace"))
        rows.append(_row("new", target, out["packet"], "Unknown", cwd, new,
                         reason="the CLI printed no usage in its output", cfg=cfg))
        try:
            old, model, why = old_lead_usage(packet)
        except Exception as exc:  # noqa: BLE001 — reading the other CLI's files is best effort
            old, model, why = None, "", f"could not read: {type(exc).__name__}"
        source = packet.get("source") or "Unknown"
        rows.append(_row("old", source, out["packet"], str(packet.get("source_session") or "Unknown"), cwd,
                         old, reason=why, model=model, cfg=cfg))
        for r in rows:
            ledger.append_event(p, r)
        out["usage_ledger"] = {"new": "known" if new else "Unknown", "old": "known" if old else "Unknown"}
    except Exception as exc:  # noqa: BLE001 — a missing ledger row must not hide the launch result
        out["usage_ledger"] = f"failed: {type(exc).__name__}: {exc}"[:200]
