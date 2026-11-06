"""Avoid cmd.exe's lossy JSON/empty-argument forwarding for semantic isolation."""
from __future__ import annotations

from pathlib import Path
import shutil


def direct_argv(argv: list[str]) -> list[str]:
    """Resolve known npm layout without executing/reading a batch shim. Unknown layouts fail closed."""
    if not argv or Path(argv[0]).suffix.lower() not in (".cmd", ".bat"):
        return argv
    shim = Path(argv[0]).resolve()
    native = shim.with_suffix(".exe")
    if native.is_file():
        return [str(native), *argv[1:]]
    entry = shim.parent / "node_modules" / "@anthropic-ai" / "claude-code" / "cli.js"
    node = shim.parent / "node.exe"
    runtime = str(node) if node.is_file() else shutil.which("node")
    if entry.is_file() and runtime:
        return [runtime, str(entry), *argv[1:]]
    raise ValueError("semantic CLI requires a native executable or known npm entry; batch shim quoting is unsafe")
