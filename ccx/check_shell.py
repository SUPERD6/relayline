"""Select a POSIX shell only for acceptance commands that need it on Windows."""
from __future__ import annotations

import os
from pathlib import Path
import re
import shlex
import shutil


def _bash_expansion(token: str) -> bool:
    for match in re.finditer(r"(?<![\\^])\$(?:[A-Za-z_][A-Za-z_0-9]*(?![A-Za-z_0-9:])|\{|\()", token):
        # A dollar embedded in a literal path is not enough to select a shell.
        # A leading expansion such as $ROOT/tests is still shell syntax.
        prefix = token[:match.start()].strip("\"'")
        if not re.match(r"[A-Za-z]:", prefix) and not any(separator in prefix for separator in ("/", "\\")):
            return True
    return False


def needs_bash(cmd: str) -> bool:
    """Recognize shell-level syntax, leaving shared cmd.exe operators alone.

    Quoted program text is not scanned for commands such as export. Single-quoted
    dollars are literal; double-quoted dollars still request shell expansion.
    """
    lexer = shlex.shlex(cmd, posix=False, punctuation_chars=";&|\n")
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    lexer.commenters = ""
    start = True
    interpreter = False
    program_text = False
    try:
        for token in lexer:
            if program_text:
                program_text = False
                continue
            if token in ("&&", "||", ";", "|", "&", "\n"):
                start = True
                interpreter = False
                continue
            if interpreter and token.lower() in ("-c", "-command", "/c"):
                program_text = True
                continue
            if start:
                executable = token.strip("\"'").replace("\\", "/").rsplit("/", 1)[-1]
                interpreter = bool(re.fullmatch(
                    r"(?:python(?:\d+(?:\.\d+)*)?|node|ruby|perl|php|bash|sh|cmd|powershell|pwsh)(?:\.exe)?",
                    executable, re.I))
            if token.startswith("'"):
                start = False
                continue
            if _bash_expansion(token):
                return True
            if start and (token == "export" or re.match(r"[A-Za-z_][A-Za-z_0-9]*=", token)):
                return True
            start = False
    except ValueError:
        pass  # Malformed quotes remain the native shell's responsibility.
    return False


def find_bash(env: dict) -> str | None:
    """Find PATH's Bash or Git Bash beside git.exe; exclude the WSL launcher.

    A WSL bash.exe needs a separately configured Linux distribution and does not
    share native Windows executable/path semantics with Git Bash.
    """
    path = next((v for k, v in env.items() if k.upper() == "PATH"), "")
    bash = shutil.which("bash", path=path)
    if bash and not re.search(
            r"[\\/](?:windows[\\/](?:system32|syswow64|sysnative)|windowsapps(?:[\\/].*)?)[\\/]bash\.exe$",
            bash, re.I):
        return bash
    git = shutil.which("git", path=path)
    if git:
        # Git may be exposed from cmd/, mingw64/bin/, or a Scoop shim/symlink.
        roots = list(Path(git).resolve().parents)[:4]
        for root in roots:
            for relative in ("bin/bash.exe", "usr/bin/bash.exe", "apps/git/current/bin/bash.exe",
                             "apps/git/current/usr/bin/bash.exe"):
                candidate = root / relative
                if candidate.is_file():
                    return os.fspath(candidate)
    return None
