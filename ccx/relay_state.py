"""Small, atomic workspace-local handoff packets. Never read a CLI's private transcript."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
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


def git(cwd: Path, *args: str, timeout: float = 2) -> str:
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, encoding="utf-8", errors="replace",
                       stdin=subprocess.DEVNULL, timeout=timeout)
    if r.returncode:
        raise ValueError("relay requires a Git workspace: " + r.stderr.strip())
    return r.stdout


def root(cwd: Path, *, timeout: float = 2) -> Path:
    return Path(git(cwd, "rev-parse", "--show-toplevel", timeout=timeout).strip()).resolve()


def snapshot(cwd: Path, *, command_timeout: float = 2, total_timeout: float = 6) -> dict:
    # Hooks use one short deadline; manual operations explicitly pass longer bounds. Never persist source hunks.
    deadline = time.monotonic() + total_timeout
    out = {"head": "Unknown", "uncommitted": [], "diffstat": "", "staged_diffstat": ""}
    commands = (("head", ("rev-parse", "HEAD")),
                ("uncommitted", ("status", "--porcelain=v1", "-z", "--untracked-files=all")),
                ("diffstat", ("diff", "--no-ext-diff", "--no-textconv", "--stat")),
                ("staged_diffstat", ("diff", "--cached", "--no-ext-diff", "--no-textconv", "--stat")))
    for key, args in commands:
        try:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired("git", total_timeout)
            value = git(cwd, *args, timeout=min(command_timeout, remaining))
            if key == "uncommitted":
                rows, names = [], []
                entries = iter(value.split("\0"))
                for entry in entries:
                    if not entry:
                        continue
                    rows.append(entry)
                    names.append(entry[3:])
                    if "R" in entry[:2] or "C" in entry[:2]:
                        names.append(next(entries, ""))
                out[key] = [row[:512] for row in rows[:200]]
                if len(rows) > 200 or any(len(row) > 512 for row in rows):
                    out["truncated"] = True
                out["content_fingerprint"] = fingerprint(cwd, names, deadline)
            else:
                out[key] = value.strip()[:4096]
                if len(value.strip()) > 4096:
                    out["truncated"] = True
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            out["snapshot_status"] = "Unknown"
            out["snapshot_reason"] = (f"Git {args[0]} timed out after {exc.timeout:g} seconds"
                                      if isinstance(exc, subprocess.TimeoutExpired) else
                                      f"Git {args[0]} failed: {type(exc).__name__}")
            out["retry_hint"] = "Retry manual capture/continue with --git-timeout-seconds 60; inspect git status first."
            break
    return out


def fingerprint(cwd: Path, names: list[str], deadline: float) -> str:
    """Hash dirty file bytes without persisting them; bound work and never follow outside symlinks."""
    if len(names) > 200:
        return "Unknown"
    digest, total = hashlib.sha256(), 0
    for name in sorted(set(names)):
        path = cwd / name
        resolved = path.resolve()
        private = {".ccx", ".codex", ".claude"}
        if (not name or time.monotonic() >= deadline or not resolved.is_relative_to(cwd.resolve())
                or private.intersection(part.casefold() for part in Path(name).parts)
                or private.intersection(part.casefold() for part in resolved.relative_to(cwd.resolve()).parts)):
            return "Unknown"
        digest.update(name.encode("utf-8", errors="replace"))
        try:
            if path.is_symlink():
                digest.update(os.readlink(path).encode("utf-8", errors="replace"))
            elif path.is_file():
                if total + path.stat().st_size > 8 * 1024 * 1024:
                    return "Unknown"
                with path.open("rb") as stream:
                    while chunk := stream.read(65536):
                        total += len(chunk)
                        if total > 8 * 1024 * 1024 or time.monotonic() >= deadline:
                            return "Unknown"
                        digest.update(chunk)
            elif path.exists():
                return "Unknown"
            else:
                digest.update(b"missing")
        except OSError:
            return "Unknown"
    return digest.hexdigest()


def storage(cwd: Path) -> Path:
    folder = cwd / ".ccx" / "relay"
    folder.mkdir(parents=True, exist_ok=True)
    # A local ignore rule protects packets even in repositories that do not ignore .ccx.
    ignore = folder / ".gitignore"
    previous = ignore.read_text(encoding="utf-8") if ignore.exists() else ""
    if not previous.endswith("*\n"):
        ignore.write_text(previous + ("\n" if previous and not previous.endswith("\n") else "") + "*\n",
                          encoding="utf-8", newline="")
    return folder


def context_path(cwd: Path, session: str) -> Path:
    return storage(cwd) / ("context-" + hashlib.sha256(session.encode()).hexdigest() + ".json")


def capture(cwd: Path, source: str, session: str, evidence: dict, context: dict, *,
            command_timeout: float = 2, total_timeout: float = 6) -> tuple[Path, dict]:
    folder = storage(cwd)
    packet = {"schema_version": 1, "id": uuid.uuid4().hex, "workspace": str(cwd), "source": source,
              "source_session": session[:512], "goal": str(context.get("goal") or "Unknown")[:4096],
              "progress": str(context.get("progress") or "Unknown")[:4096],
              "next_step": str(context.get("next_step") or "Unknown")[:4096],
              "quota_signal": evidence, "git": snapshot(cwd, command_timeout=command_timeout, total_timeout=total_timeout),
              "old_writer_stopped": "Unknown",
              "verification": "not-run"}
    packet["continue_command"] = ("ccx relay continue " + packet["id"] + " --to " +
                                  ("codex" if source == "claude" else "claude") +
                                  " --budget-seconds <seconds>" +
                                  ("" if evidence.get("kind") == "rate_limit_unconfirmed" else " --old-stopped"))
    packet["state"] = ("quota_stopped" if evidence.get("kind") == "quota" else
                       "rate_limit_unconfirmed" if evidence.get("kind") == "rate_limit_unconfirmed" else "captured")
    path = folder / (packet["id"] + ".json")
    atomic_json(path, packet)
    return path, packet


def notice(packet: dict) -> dict:
    unconfirmed = packet["quota_signal"].get("kind") == "rate_limit_unconfirmed"
    return {"packet": packet["id"], "state": packet["state"],
            "message": ("可能只是限速，可以等一下或手动接续。启动接续需显式 --force-unconfirmed。"
                        if unconfirmed else "Quota relay captured; stop the old session before continuing."),
            "continue_command": packet["continue_command"]}


def load_packet(cwd: Path, packet_id: str) -> tuple[Path, dict]:
    if len(packet_id) != 32 or any(c not in "0123456789abcdef" for c in packet_id):
        raise ValueError("relay packet must be its 32-character id")
    path = cwd / ".ccx" / "relay" / (packet_id + ".json")
    packet = json.loads(path.read_text(encoding="utf-8"))
    if Path(packet["workspace"]).resolve() != cwd:
        raise ValueError("relay packet belongs to another workspace")
    return path, packet
