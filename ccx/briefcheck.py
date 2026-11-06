"""Cheap, deliberately incomplete dispatch diagnostics. Never execute brief text."""
from __future__ import annotations

import os
import re
from pathlib import Path, PureWindowsPath

# A dotted API name or version number alone is not a local input file.
_FILE_SUFFIXES = frozenset((".py", ".md", ".json", ".toml", ".txt", ".yaml", ".yml", ".cfg", ".ini",
                            ".js", ".ts", ".jsx", ".tsx", ".html", ".css", ".csv", ".xml", ".rst",
                            ".sh", ".ps1", ".bat", ".cmd", ".sql", ".ipynb", ".pdf", ".docx",
                            ".xlsx", ".pptx"))


def _instructions(text: str) -> str:
    """Quoted examples are data, not dispatch instructions. Prefer skipping a real command to a false refusal."""
    lines = []
    fence = ""
    for line in text.splitlines():
        marker = re.match(r"^\s*(`{3,}|~{3,})", line)
        if marker:
            value = marker.group(1)
            if not fence:
                fence = value
            elif value[0] == fence[0] and len(value) >= len(fence):
                fence = ""
            continue
        if not fence and not line.lstrip().startswith(">"):
            lines.append(line)
    return "\n".join(lines)


def _clauses(text: str) -> list[str]:
    return [re.sub(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)?(?:please\s+)?", "", s, flags=re.I).strip()
            for s in re.split(r"\n|;|[。！？]|(?<=[.!?])\s+", text)]


def _writes(clause: str) -> bool:
    # Imperatives only: 'review how to write ...' and 'do not write ...' are not edits.
    return bool(re.match(
        r"(?i)^(?:(?:edit|modify|rewrite|delete|rename)\s+(?:the\s+)?(?:file\b|[`\"']?\S+[./\\]\S*)"
        r"|(?:write|create|save)\s+(?:(?:a|the)\s+)?(?:files?\b|[`\"']?\S+\.\w+\b)"
        r"|write\s+(?:(?:a|the)\s+)?report\s+to\s+[`\"']?[A-Za-z0-9_./\\-]+\."
        r"(?:md|txt|json|html|csv|pdf|docx)\b"
        r"|写(?:一个|个)?报告文件"
        r"|(?:open|create|submit)\s+(?:(?:a|the)\s+)?(?:PR\b|pull request\b)"
        r"|gh\s+pr\s+create\b|(?:修改|改写|删除|新建|创建|写入)(?:文件|[`\"']?\S+\.\w+)"
        r"|(?:创建|新建|提交)\s*(?:PR\b|拉取请求))", clause))


def _input(clause: str) -> str | None:
    if re.search(r"(?i)\b(?:if (?:it )?exists|if present|optional|example)\b|如果存在|若存在|可选", clause):
        return None
    m = re.match(r"(?i)^(?:(?:read|inspect|open)\s+|(?:阅读|读取)\s*)(?:the\s+)?(?:file\s+)?"
                 r"(?:`([^`]+)`|\"([^\"]+)\"|'([^']+)'|(\S+))", clause)
    if not m:
        return None
    value = next(v for v in m.groups() if v is not None).rstrip(".,:，：")
    # Plain words, URLs, globs, placeholders and tool-private paths are intentionally ignored.
    if re.search(r"[<>*$?{}~]|://", value):
        return None
    # Stop before full-width punctuation or adjacent prose; do not guess Unicode path spellings.
    ascii_path = re.match(r"[A-Za-z0-9_./\\: @+()\[\],=-]+", value)
    if not ascii_path:
        return None
    end = ascii_path.end()
    if end < len(value) and value[end] not in "，。；：！？、（）【】“”‘’":
        return None
    value = ascii_path.group(0).rstrip(".,: ")
    if not re.search(r"[/\\]", value) and Path(value).suffix.lower() not in _FILE_SUFFIXES:
        return None
    if any(p.lower() in (".ccx", ".codex", ".claude") for p in re.split(r"[/\\]", value)):
        return None
    return value


def _platform_problem(command: str, platform: str) -> bool:
    # Only direct native-shell syntax, never commands passed to an explicit interpreter.
    if platform == "nt":
        return bool(re.match(r"\s*(?:export\s+[A-Za-z_]\w*=|(?:\./)?\S+\.sh(?:\s|$)|"
                             r"[A-Za-z_]\w*=[^\s]+\s+\S)", command))
    return bool(re.match(r"\s*(?:\.\\\S+\.ps1(?:\s|$)|\$env:[A-Za-z_]\w*\s*=|"
                         r"[A-Za-z]:\\\S+\.(?:exe|cmd|bat)(?:\s|$))", command, re.I))


def check(brief: str, mode: str, cwd: Path, command: str | None = None, *,
          platform: str | None = None) -> list[dict[str, str]]:
    """Return stable warning codes; existence checks read no file contents or directories."""
    platform = os.name if platform is None else platform
    warnings: list[dict[str, str]] = []
    text = _instructions(brief)
    clauses = _clauses(text)
    if mode == "read" and any(_writes(s) for s in clauses):
        warnings.append({"code": "read_requires_write",
                         "message": "read mode conflicts with an explicit request to edit a file or create a PR"})
    seen = set()
    for clause in clauses:
        value = _input(clause)
        if not value or value in seen:
            continue
        seen.add(value)
        # Foreign absolute paths cannot be checked meaningfully on this platform.
        if platform != "nt" and (PureWindowsPath(value).drive or "\\" in value):
            continue
        if platform == "nt" and value.startswith("/"):
            continue
        try:
            exists = (cwd / value).exists()
        except (OSError, ValueError):
            continue                    # inaccessible is Unknown, not missing
        if not exists:
            warnings.append({"code": "missing_input", "path": value,
                             "message": f"requested input path does not exist relative to --cwd: {value}"})
    commands = [command] if command else []
    # Extract before splitting clauses: semicolons inside a quoted command belong to that command.
    for m in re.finditer(r"(?im)(?:^|(?<=;))\s*(?:[-*+]\s+|\d+[.)]\s+)?(?:please\s+)?"
                         r"(?:run|check|执行|运行)(?:\s+|[:：]\s*)`([^`\n]+)`", text):
        commands.append(m.group(1))
    for cmd in dict.fromkeys(commands):
        if _platform_problem(cmd, platform):
            warnings.append({"code": "platform_command", "command": cmd,
                             "message": "check command uses syntax for a different native platform; "
                                        "use an explicit shell/interpreter if intended"})
    return warnings


def emit(warnings: list[dict[str, str]]) -> None:
    import sys
    for warning in warnings:
        print(f"ccx: brief warning [{warning['code']}]: {warning['message']}", file=sys.stderr, flush=True)
