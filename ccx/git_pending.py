"""Additive Git handoff evidence; optional parent-side staging, never commit/continue."""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
from pathlib import Path

from .config import git_auto_stage

MAX_FILE_BYTES = 4 * 1024 * 1024


def _git(cwd: Path, *args: str, input_data: bytes | None = None) -> str:
    r = subprocess.run(["git", "--literal-pathspecs", *args], cwd=cwd, capture_output=True,
                       input=input_data, **({"stdin": subprocess.DEVNULL} if input_data is None else {}),
                       timeout=15)
    if r.returncode:
        raise OSError("git " + args[0] + " failed (exit " + str(r.returncode) + ")")
    return os.fsdecode(r.stdout)


def _paths(cwd: Path, *args: str, only: str | None = None) -> set[str]:
    return set(filter(None, _git(cwd, *args, "-z", *(["--", only] if only else [])).split("\0")))


def _types(root: Path, only: str | None = None) -> dict[str, str]:
    fields = _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=no",
                  *(["--", only] if only else [])).split("\0")
    out, index = {}, 0
    while index < len(fields):
        entry = fields[index]
        index += 1
        if len(entry) < 4:
            continue
        code = entry[:2]
        if code in ("UU", "AA", "DU", "UD", "AU", "UA", "DD"):
            out[entry[3:]] = code
        if "R" in code or "C" in code:
            index += 1
    return out


def _file(root: Path, name: str, size: int) -> dict:
    path = root / name
    if not path.resolve().is_relative_to(root.resolve()) or any(
            p.is_symlink() for p in (path, *path.parents) if p != root and p.is_relative_to(root)):
        return {"unsafe": True}
    try:
        with path.open("rb") as stream:
            data = stream.read(MAX_FILE_BYTES + 1)
    except FileNotFoundError:
        return {"fingerprint": "missing"}
    except OSError:
        return {"unsafe": True, "unknown": "unreadable conflict file"}
    if len(data) > MAX_FILE_BYTES:
        return {"unknown": "conflict file exceeds 4 MiB inspection limit"}
    patterns = []
    # Existing default-size markers remain markers if attributes changed after the merge began.
    for length in sorted({7, size}):
        count = str(length).encode("ascii")
        patterns.append(rb"(?:={" + count + rb"}|(?:<{" + count + rb"}|>{" + count +
                        rb"}|\|{" + count + rb"})(?: [^\r\n]*)?)")
    marker = re.compile(rb"^(?:" + b"|".join(patterns) + rb")\r?$", re.MULTILINE)
    return {"fingerprint": hashlib.sha256(data).hexdigest(), "marker": bool(marker.search(data)),
            "unsafe": b"\0" in data}


def inspect(cwd: Path, before: dict | None = None, *, only: str | None = None) -> dict:
    """Inspect conflict paths only; targeted rechecks receive the already resolved root as cwd."""
    out = {"status": "Unknown", "operations": [], "unmerged": [], "conflict_markers": [],
           "resolved_unstaged": [], "unsafe_paths": [], "unknown_paths": {}, "steps": [],
           "fingerprints": {}, "conflict_types": {}, "known_conflicts": [], "manual_paths": []}
    before = before or {}
    try:
        root = cwd if only is not None else Path(_git(cwd, "rev-parse", "--show-toplevel").strip())
        unmerged = _paths(root, "diff", "--name-only", "--diff-filter=U", only=only)
        unstaged = _paths(root, "diff", "--name-only", only=only)
        types = _types(root, only)
        known = set(before.get("unmerged") or [])
        scan = unmerged | known
        if only:
            scan &= {only}
        sizes = {}
        if scan:
            attrs = _git(root, "check-attr", "-z", "--stdin", "conflict-marker-size",
                         input_data=b"".join(os.fsencode(name) + b"\0" for name in sorted(scan))).split("\0")
            for name, _, value in zip(attrs[0::3], attrs[1::3], attrs[2::3]):
                sizes[name] = int(value) if value.isdigit() and 0 < int(value) < 10000 else 7
        markers, unsafe, fingerprints, unknown = set(), set(), {}, {}
        for name in scan:
            state = _file(root, name, sizes.get(name, 7))
            if state.get("marker"):
                markers.add(name)
            if state.get("unsafe"):
                unsafe.add(name)
            if state.get("unknown"):
                unknown[name] = state["unknown"]
            if "fingerprint" in state:
                fingerprints[name] = state["fingerprint"]
        eligible = unmerged | (known & unstaged)
        changed = {name for name in eligible if name in fingerprints
                   and name in (before.get("fingerprints") or {})
                   and fingerprints[name] != before["fingerprints"][name]}
        prior_types = before.get("conflict_types") or {}
        supported = {name for name in eligible if prior_types.get(name) in ("UU", "AA")
                     and types.get(name, prior_types[name]) in ("UU", "AA")}
        resolved = (changed & supported) - markers - unsafe - set(unknown)
        manual = eligible - resolved - markers - unsafe - set(unknown)
        operations = []
        if only is None:
            for op, names in (("merge", ("MERGE_HEAD",)), ("rebase", ("rebase-merge", "rebase-apply")),
                              ("cherry-pick", ("CHERRY_PICK_HEAD",))):
                for name in names:
                    location = Path(_git(root, "rev-parse", "--git-path", name).strip())
                    if not location.is_absolute():
                        location = root / location
                    if location.exists():
                        operations.append(op)
                        break
        steps = []
        if markers:
            steps.append("resolve conflict markers")
        if unmerged or resolved:
            steps.append("git add resolved paths")
        if manual:
            steps.append("review conflict choices and stage manually")
        if unknown:
            steps.append("inspect Unknown conflict paths manually")
        steps.extend("finish " + op + " (commit/continue after review)" for op in operations)
        out.update(status="Unknown" if unknown else "known", operations=operations, unmerged=sorted(unmerged),
                   conflict_markers=sorted(markers), resolved_unstaged=sorted(resolved),
                   unsafe_paths=sorted(unsafe), unknown_paths=unknown, fingerprints=fingerprints,
                   conflict_types=types, known_conflicts=sorted(known), manual_paths=sorted(manual), steps=steps)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        out["reason"] = "Git pending state unavailable (not a repository or Git inspection failed)"
    return out


def finish(cwd: Path, cfg: dict, before: dict | None = None, *, write: bool = False) -> dict:
    """Stage only changed UU/AA conflicts established by the dispatch-time content snapshot."""
    pending = inspect(cwd, before)
    reason = None
    try:
        enabled = git_auto_stage(cfg) and write
    except ValueError as error:
        enabled, reason = False, str(error)
    staged, failed = [], []
    candidates = pending["resolved_unstaged"]
    if enabled and pending["status"] == "known" and candidates:
        try:
            root = Path(_git(cwd, "rev-parse", "--show-toplevel").strip())
        except (OSError, subprocess.TimeoutExpired):
            root = None
        for name in candidates:
            current = inspect(root, before, only=name) if root else {}
            if name not in current.get("resolved_unstaged", []):
                failed.append(name)
                continue
            try:
                _git(root, "add", "--", name)
                staged.append(name)
            except (OSError, subprocess.TimeoutExpired):
                failed.append(name)
        pending = inspect(cwd, before)
    pending["auto_stage"] = {"enabled": enabled, "staged": staged, "failed": failed,
                             "not_staged": sorted(set(candidates) - set(staged) | set(pending["unmerged"]))}
    if reason:
        pending["auto_stage"]["reason"] = reason
    return pending
