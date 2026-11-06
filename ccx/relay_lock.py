"""Fail-closed workspace relay ownership and known ccx writer checks."""
from __future__ import annotations

import json
import os
from pathlib import Path
import time
import uuid

from .config import paths
from .runners import pid_alive


def known_writers(cwd: Path) -> dict:
    """Inspect only ccx run records, never client homes or private transcripts."""
    live, unreadable = [], 0
    for path in paths().runs.glob("*/run.json"):
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
            place = Path(rec.get("cwd") or "").resolve()
            workspace = cwd.resolve()
            # ccx may start inside a repository subdirectory. Stop at another worktree/repo boundary.
            while place != workspace and place != place.parent and not (place / ".git").exists():
                place = place.parent
            if place != workspace or rec.get("state") not in ("running", "starting"):
                continue
            for key in ("ccx_pid", "pid"):
                pid = rec.get(key)
                if pid and pid != os.getpid() and pid_alive(pid):
                    live.append({"run": path.parent.name, "pid": pid})
        except (OSError, ValueError, TypeError):
            unreadable += 1
    return {"known_live_writers": live, "unreadable_records": unreadable,
            "untracked_native_processes": "Unknown: native Claude/Codex processes and auto-resume cannot be excluded"}


class WorkspaceLock:
    """Do not auto-delete stale claims: an orphan child may still own the workspace."""
    def __init__(self, folder: Path):
        self.path = folder / "workspace.launch-lock"
        self.token = uuid.uuid4().hex

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                owner = json.loads(self.path.read_text(encoding="utf-8"))
                status = "active" if pid_alive(owner.get("pid")) else "stale"
            except (OSError, ValueError, TypeError):
                status = "Unknown"
            raise ValueError(f"workspace relay lock is {status}; inspect owner and orphan writers before removing {self.path.name}") from None
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump({"pid": os.getpid(), "created_at": time.time(), "token": self.token}, stream)

    def release(self) -> None:
        try:
            owner = json.loads(self.path.read_text(encoding="utf-8"))
            if owner.get("token") == self.token:
                self.path.unlink()
        except (OSError, ValueError):
            pass
