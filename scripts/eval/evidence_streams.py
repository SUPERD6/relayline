"""Keep unit-local event streams before cleanup, with credentials and machine paths redacted.

Only explicit lead/events/stderr files are read; never walk a tool home or copy auth/config/session files.
Event order and JSON structure are preserved. Redaction means these are not byte-identical CLI logs.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re


SECRET_KEY = re.compile(r"authorization|credential|password|secret|(?:api|access|refresh|auth)[_-]?(?:key|token)|"
                        r"(?:^|[_-])token$", re.I)
ASSIGNMENT = re.compile(r"(?i)(?<![\w-])((?:authorization|password|secret|[\w-]*(?:api[_-]?key|token))"
                        r"[\"']?\s*[:=]\s*[\"']?)(?:Bearer\s+)?[^\s\"',;}]+")
TOKEN = re.compile(r"\b(?:sk-[A-Za-z0-9_-]{8,}|eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)\b")
BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
URL_AUTH = re.compile(r"(?i)(https?://)[^/@\s:]+:[^/@\s]+@")
PEM_START = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
PEM_END = re.compile(r"-----END [A-Z ]*PRIVATE KEY-----")
PEM = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)", re.S)
HOME_PATH = re.compile(r"(?i)(?:[a-z]:[\\/]Users[\\/][^\\/\s\"']+|/(?:home|Users)/[^/\s\"']+)")
LOG_NAME = re.compile(r"(?:events|stderr)\.\d+\.log\Z")


class Redactor:
    def __init__(self, unit, env: dict | None):
        self.private_block = False
        self.secrets = sorted({str(v) for k, v in (env or {}).items() if SECRET_KEY.search(k) and len(str(v)) >= 4},
                              key=len, reverse=True)
        paths = [(unit.tmp, "<unit.tmp>"), (unit.repo, "<unit.repo>"), (unit.hub, "<unit.hub>"),
                 (unit.x, "<unit.x>"), (unit.worktrees, "<unit.worktrees>"), (unit.work, "<unit.work>")]
        for key, value in unit.real.items():
            if isinstance(value, Path):
                paths.append((value, f"<real.{key}>"))
            elif key == "root_worktrees":
                paths += [(p, "<real.worktree>") for p in value]
        self.paths = sorted({(s, tag) for p, tag in paths for s in
                             (str(p), Path(p).as_posix(), str(p).replace("\\", "\\\\")) if s},
                            key=lambda item: len(item[0]), reverse=True)

    def text(self, text: str) -> str:
        for secret in self.secrets:
            text = text.replace(secret, "[REDACTED]")
        for path, tag in self.paths:
            text = re.sub(re.escape(path), lambda _: tag, text, flags=re.I)
        text = HOME_PATH.sub("<user-home>", text)
        text = ASSIGNMENT.sub(lambda m: m[1] + "[REDACTED]", text)
        text = BEARER.sub("Bearer [REDACTED]", text)
        text = URL_AUTH.sub(lambda m: m[1] + "[REDACTED]@", text)
        text = PEM.sub("[REDACTED PRIVATE KEY]", text)
        return TOKEN.sub("[REDACTED]", text)

    def value(self, obj):
        if isinstance(obj, dict):
            return {self.text(k): "[REDACTED]" if SECRET_KEY.search(k) else self.value(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self.value(v) for v in obj]
        if isinstance(obj, str):
            # Agent text / tool arguments can themselves be serialized JSON.
            try:
                nested = json.loads(obj)
            except (ValueError, TypeError):
                return self.text(obj)
            if isinstance(nested, (dict, list)):
                return json.dumps(self.value(nested), ensure_ascii=False)
            return self.text(obj)
        return obj

    def line(self, line: str) -> str:
        if self.private_block:
            end = PEM_END.search(line)
            self.private_block = end is None
            return "[REDACTED PRIVATE KEY]" + (self.text(line[end.end():]) if end else "\n")
        try:
            value = json.loads(line)
        except ValueError:
            end = PEM_END.search(line)
            start = PEM_START.search(line)
            if start and end is None:
                self.private_block = True
                return self.text(line[:start.start()]) + "[REDACTED PRIVATE KEY]\n"
            return self.text(line)
        return json.dumps(self.value(value), ensure_ascii=False) + "\n"


def keep(dest: Path, unit, lead: Path, env: dict | None = None) -> dict | None:
    """Full streams (no size truncation), including successful units, all attempts and stderr. No symlinks."""
    sources = [(lead, "lead.jsonl")]
    runs = unit.hub / "ccx" / "runs"
    hub_base = unit.hub.parent.resolve() / unit.hub.name
    # resolve + containment also rejects Windows directory junctions (is_symlink alone misses those on 3.11).
    safe_runs = runs.resolve().is_relative_to(hub_base)
    if safe_runs and runs.is_dir() and not runs.is_symlink():
        for d in sorted(runs.iterdir()):
            if (not d.is_dir() or d.is_symlink() or not re.fullmatch(r"[\w-]+", d.name)
                    or not d.resolve().is_relative_to(runs.resolve())):
                continue
            for f in sorted(d.iterdir()):
                if LOG_NAME.fullmatch(f.name) and f.resolve().is_relative_to(runs.resolve()):
                    sources.append((f, f"subagents/{d.name}/{f.name}"))
    redactor = Redactor(unit, env)
    kept = []
    for src, name in sources:
        if not src.is_file() or src.is_symlink():
            continue
        target = Path(dest) / name
        target.parent.mkdir(parents=True, exist_ok=True)
        redactor.private_block = False
        digest, size = hashlib.sha256(), 0
        with src.open(encoding="utf-8", errors="replace") as reader, target.open("w", encoding="utf-8", newline="") as writer:
            for line in reader:
                safe = redactor.line(line)
                writer.write(safe)
                raw = safe.encode("utf-8")
                digest.update(raw)
                size += len(raw)
        kept.append({"file": name, "bytes": size, "sha256": digest.hexdigest()})
    if not kept:
        return None
    return {"dir": Path(dest).parent.name, "path": "streams", "files": kept, "redacted": True}
