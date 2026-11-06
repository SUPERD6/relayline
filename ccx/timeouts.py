"""Additive timeout evidence and an opt-in, up-front deadline reminder."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

MESSAGE_CHARS = 4000


def deadline_prompt(prompt: str, cfg: dict, seconds: int) -> str:
    """No runtime injection: each attempt receives its own configured time limit."""
    if (cfg.get("defaults") or {}).get("timeout_reminder") is not True:
        return prompt
    return (prompt + f"\n[ccx time limit] This attempt has a time limit of {seconds / 60:g} minutes "
            f"({seconds} seconds). As the limit approaches, write a partial result first, including "
            "changes, checks already run, and the next step, before continuing work.\n")


def last_assistant_message(agent: str, stdout: str) -> str | None:
    """Only assistant text from JSON events; tool output, errors and reasoning are excluded."""
    last, gemini_text = None, ""
    for line in stdout.splitlines():
        try:
            ev = json.loads(line)
        except (ValueError, TypeError):
            continue
        if not isinstance(ev, dict):
            continue
        kind, text = ev.get("type"), None
        if agent == "codex" and kind == "item.completed":
            item = ev.get("item") or {}
            if isinstance(item, dict) and item.get("type") in ("agent_message", "assistant_message"):
                text = item.get("text")
        elif agent == "claude" and kind == "assistant":
            msg = ev.get("message") or {}
            if isinstance(msg, dict):
                content = msg.get("content") or []
                if isinstance(content, str):
                    text = content
                elif isinstance(content, list):
                    text = "".join(b.get("text", "") for b in content if isinstance(b, dict)
                                   and b.get("type") == "text" and isinstance(b.get("text"), str))
        elif agent == "gemini" and kind == "message" and ev.get("role") == "assistant":
            content = ev.get("content")
            if isinstance(content, str):
                gemini_text = gemini_text + content if ev.get("delta") is True else content
                text = gemini_text
        elif agent == "gemini" and kind == "message":
            gemini_text = ""
        elif agent == "dsh" and kind in ("text", "final"):
            text = ev.get("text")
        if isinstance(text, str) and text.strip():
            last = text
    return last


def changed_paths(snap: dict) -> list[str]:
    """Only ask Git for paths since the snapshot; never open untracked file contents."""
    from .runners import without_launcher_vars
    from .workspace import _unquote

    def git(*args: str) -> list[str]:
        result = subprocess.run(["git", "-c", "core.quotepath=off", *args], cwd=Path(snap["repo"]),
                                capture_output=True, text=True, encoding="utf-8", errors="replace",
                                stdin=subprocess.DEVNULL, timeout=30,
                                env=without_launcher_vars(os.environ))
        result.check_returncode()
        return [name for name in result.stdout.split("\0") if name and not name.startswith(".ccx/")]

    names = git("diff", "--name-only", "-z", snap["base"], "--", ".", ":(exclude).ccx")
    before = {_unquote(name) for name in snap.get("untracked") or []}
    names += [name for name in git("ls-files", "--others", "--exclude-standard", "--full-name", "-z")
              if name not in before]
    return sorted(set(names))


def timeout_context(agent: str, stdout: str, snap: dict | None) -> dict:
    """Collect paths without diff bodies for either workspace layout.

    None means Unknown (no Git snapshot / assistant event), not an empty successful result.
    """
    files = None
    if snap:
        try:
            files = changed_paths(snap)
        except Exception:  # noqa: BLE001 — recovery evidence must not change the outcome
            pass
    message = last_assistant_message(agent, stdout)
    return {"files_changed": files,
            "last_assistant_message": message[-MESSAGE_CHARS:] if message is not None else None,
            "last_assistant_message_truncated": bool(message and len(message) > MESSAGE_CHARS)}
