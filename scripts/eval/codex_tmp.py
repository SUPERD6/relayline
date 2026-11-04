"""Opt-in eval-only launcher: give each Codex invocation temp space inside its actual working directory.

ccx's first exec and resume both launch with the child's cwd. No sandbox flags or user configuration are changed.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def workspace_write(args: list[str]) -> bool:
    mode = None
    for i, arg in enumerate(args):
        if arg in ("-s", "--sandbox") and i + 1 < len(args):
            mode = args[i + 1]
        if arg.startswith("--sandbox="):
            mode = arg.partition("=")[2]
        if arg in ("-c", "--config") and i + 1 < len(args):
            key, _, value = args[i + 1].partition("=")
            if key == "sandbox_mode":
                mode = value.strip('"\'')
    return args[:1] == ["exec"] and mode == "workspace-write"


def main() -> int:
    argv = json.loads(os.environ["CCX_EVAL_CODEX_ARGV"])
    args = sys.argv[1:]
    if not workspace_write(args):
        return subprocess.call([*argv, *args])
    # ccx sets both cwd and -C; retain the latter's semantics for direct evaluation invocations as well.
    cwd = Path.cwd()
    for flag in ("-C", "--cd"):
        if flag in args:
            cwd = Path(args[args.index(flag) + 1]).resolve()
            break
    with tempfile.TemporaryDirectory(prefix=".ccx-eval-tmp-", dir=cwd) as temp:
        env = {**os.environ, **{k: temp for k in ("TMP", "TEMP", "TMPDIR")}}
        # stdout/stderr/stdin stay attached: raw events, exit codes, and resume prompts keep their wire format.
        return subprocess.call([*argv, *args], env=env)


if __name__ == "__main__":
    sys.exit(main())
