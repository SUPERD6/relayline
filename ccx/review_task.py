"""Separate saved user wording from the assigned task in experimental test review."""
from __future__ import annotations

import json
from pathlib import Path
import re


def assigned_task(p, req, record: dict) -> tuple[str, str]:
    from .review import task_for_review
    for text, source in ((record.get("user_task"), "user_task (run.json)"),
                         (getattr(req, "user_task", None), "user_task (Request)")):
        if isinstance(text, str) and text.strip():
            return text, source
    rid, seen = req.resume_run, set()
    while rid and rid not in seen:
        seen.add(rid)
        try:
            prev = json.loads((p.runs / rid / "run.json").read_text(encoding="utf-8"))
            if isinstance(prev.get("user_task"), str) and prev["user_task"].strip():
                return prev["user_task"], "user_task (resumed run.json)"
            rid = prev.get("resumed_from")
        except (OSError, ValueError):
            break
    return task_for_review(p, req), "assigned brief (fallback; no user_task)"


def inputs(p, req, record: dict, run_dir: Path) -> tuple[str, tuple[str, ...]]:
    """(labelled prompt, quoteable wording); reuse the exact saved capture and cap notice."""
    from .user_words import HEADER, NOTICE
    task, source = assigned_task(p, req, record)
    labelled = f"## Source: {source}\n{task}"
    try:
        with (run_dir / "user-words.md").open(encoding="utf-8", newline="") as stream:
            block = stream.read()
    except (OSError, UnicodeError):
        return labelled, (task,)
    if not block.strip():
        return labelled, (task,)
    meta = record.get("user_words") or {}
    head = (f"## Source: user-words.md (user_words.source={meta.get('source') or 'Unknown'}, "
            f"retained_chars={meta.get('chars', 'Unknown')})\n")
    # Keep both sources even when their content is identical. Neither source labels
    # nor the capture's permission/truncation notices are new task requirements.
    prefix = HEADER + "\n" + NOTICE + "\n"
    original = block
    for spelling in (prefix, prefix.replace("\n", "\r\n")):
        if block.startswith(spelling):
            original = block[len(spelling):]
            break
    original = re.sub(r"\r?\n\[User's original words truncated at \d+ characters\.\]$", "", original)
    return head + block + "\n\n" + labelled, (original, task)
