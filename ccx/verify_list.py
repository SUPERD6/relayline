"""Read-only selection of runs waiting for a verdict."""
from __future__ import annotations

import math
import os
import time
from pathlib import Path

from . import ledger
from .config import Paths

_WINDOWS = os.name == "nt"


def matches(record: dict, project: str | None, state: str | None) -> bool:
    """Project is an exact folder name or path; state is the result status."""
    if project:
        cwd = record.get("cwd")
        if not cwd:
            return False
        try:
            from .ui import project_root
            root = project_root(str(Path(cwd).resolve()))
            if root is None:
                return False
            target = Path(project).resolve()
            # Names intentionally select every matching project; a full path disambiguates.
            name, wanted = root.name, project
            actual_path, wanted_path = str(root.resolve()), str(target)
            if _WINDOWS:
                name, wanted = name.casefold(), wanted.casefold()
                actual_path, wanted_path = actual_path.casefold(), wanted_path.casefold()
            if wanted != name and wanted_path != actual_path:
                return False
        except (OSError, ValueError, RuntimeError, TypeError):
            return False
    status = (record.get("result") or {}).get("status") or record.get("status") or record.get("state")
    return not state or status == state


def pending(p: Paths, days: float = 7, project: str | None = None,
            state: str | None = None, include_evals: bool = False, *, counts: dict | None = None) -> list[dict]:
    """Finished, unjudged runs; days=0 removes the age limit. Report unreadable records in counts."""
    if not math.isfinite(days) or days < 0:
        raise ValueError("--days must be a finite non-negative number (0 = all history)")
    since = time.time() - days * 86400 if days else float("-inf")
    if counts is None:
        counts = {}
    counts["unreadable"] = 0
    events = {}
    for row in ledger.rows(p):
        if row.get("type") in ("verify", "dismiss"):
            events[row.get("run_id")] = row
    out = []
    for file in p.runs.glob("*/run.json"):
        try:
            rec = ledger.read_record(file)
        except (OSError, ValueError):
            counts["unreadable"] += 1
            continue
        if not isinstance(rec, dict):
            counts["unreadable"] += 1
            continue
        rid = rec.get("run_id")
        if not rid or rec.get("state") == "running" or rec.get("ephemeral"):
            continue
        if rec.get("verdict") or rec.get("dismissed") or rid in events:
            continue
        if not include_evals and (ledger.is_eval(rec) or str(rec.get("label") or "").startswith(
                ("review:", "quota-probe", "handoff-from-transcript"))):
            continue
        if float(rec.get("ts") or 0) < since or not matches(rec, project, state):
            continue
        result = rec.get("result") or {}
        out.append({"run_id": rid, "ts": rec.get("ts"), "cwd": rec.get("cwd"),
                    "state": result.get("status") or rec.get("status") or rec.get("state"),
                    "kind": rec.get("kind"), "label": rec.get("label") or "",
                    "summary": (result.get("summary") or "")[:400]})
    return sorted(out, key=lambda r: (float(r.get("ts") or 0), r["run_id"]), reverse=True)
