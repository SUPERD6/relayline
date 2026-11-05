"""Small, atomic workspace-local handoff packets. Never read a CLI's private transcript."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import uuid


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def git(cwd: Path, *args: str) -> str:
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, encoding="utf-8", errors="replace",
                       stdin=subprocess.DEVNULL, timeout=15)
    if r.returncode:
        raise ValueError("relay requires a Git workspace: " + r.stderr.strip())
    return r.stdout


def root(cwd: Path) -> Path:
    return Path(git(cwd, "rev-parse", "--show-toplevel").strip()).resolve()


def snapshot(cwd: Path) -> dict:
    return {"head": git(cwd, "rev-parse", "HEAD").strip(),
            "uncommitted": git(cwd, "status", "--porcelain=v1", "--untracked-files=all").splitlines(),
            "diff": git(cwd, "diff", "--no-ext-diff", "--no-textconv"),
            "staged_diff": git(cwd, "diff", "--cached", "--no-ext-diff", "--no-textconv")}


def context_path(cwd: Path, session: str) -> Path:
    return cwd / ".ccx" / "relay" / ("context-" + hashlib.sha256(session.encode()).hexdigest() + ".json")


def capture(cwd: Path, source: str, session: str, evidence: dict, context: dict) -> tuple[Path, dict]:
    packet = {"schema_version": 1, "id": uuid.uuid4().hex, "workspace": str(cwd), "source": source,
              "source_session": session, "goal": context.get("goal") or "Unknown",
              "progress": context.get("progress") or "Unknown", "next_step": context.get("next_step") or "Unknown",
              "quota_signal": evidence, "git": snapshot(cwd), "old_writer_stopped": "Unknown",
              "verification": "not-run"}
    packet["continue_command"] = ("ccx relay continue " + packet["id"] + " --to " +
                                  ("codex" if source == "claude" else "claude") +
                                  " --budget-seconds <seconds> --old-stopped")
    path = cwd / ".ccx" / "relay" / (packet["id"] + ".json")
    atomic_json(path, packet)
    return path, packet


def load_packet(cwd: Path, packet_id: str) -> tuple[Path, dict]:
    if len(packet_id) != 32 or any(c not in "0123456789abcdef" for c in packet_id):
        raise ValueError("relay packet must be its 32-character id")
    path = cwd / ".ccx" / "relay" / (packet_id + ".json")
    packet = json.loads(path.read_text(encoding="utf-8"))
    if Path(packet["workspace"]).resolve() != cwd:
        raise ValueError("relay packet belongs to another workspace")
    return path, packet
