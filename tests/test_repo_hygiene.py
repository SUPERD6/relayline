"""No personal data in tracked files: machine paths, e-mail addresses, machine names, local-state folders.

A path like <drive>:\\Users\\<someone>\\... or /home/<someone>/... in the repo leaks who wrote it and how their machine
is laid out; so does an e-mail address or a Windows machine name (DESKTOP- or LAPTOP- and 6-8 characters with a
digit). The check is generic on purpose: it knows the *shape* of these things, never anyone's real name, address or
machine. Placeholders (<you>, example, runner, single letters used in tests, example.com / .invalid addresses, ...)
are allowed. Text files are scanned line by line (UTF-16 with a BOM too), binary files (images) for the printable
strings they contain. CI runs this file on every push, docs-only ones included (.github/workflows/hygiene.yml).
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import unquote

import pytest

ROOT = Path(__file__).resolve().parents[1]

NAME = r"([^\\/\s\"'`<>*$%{}()\[\],;:|]+)"
SLUG_NAME = r"([^\\/\s\"'`<>*$%{}()\[\],;:|-]+)"
# Any case: Windows ignores it, and Codex writes its trust entries lowercased ([projects.'c:\users\...']).
PATTERNS = [
    # C:\Users\<name>, c:\users\<name>, C:/Users/<name>, //c/Users/<name>, /c/Users/<name> (Git Bash)
    re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:?[\\/]+Users[\\/]+" + NAME, re.IGNORECASE),
    # /Users/<name> (macOS), /home/<name> (Linux): only at the start of a path, not inside x/home/...
    re.compile(r"(?<![\w.~-])/(?:Users|home)/" + NAME, re.IGNORECASE),
    # C--Users-<name>-proj: Claude Code's project-folder name for a Windows path
    re.compile(r"(?<![A-Za-z0-9])[A-Za-z]--Users-" + SLUG_NAME, re.IGNORECASE),
    # Temp/claude/<project folder name>/...: Claude Code's scratch folder is named after the project's full path
    re.compile(r"(?<![\w.~-])(?:Temp|tmp)[\\/]+claude[\\/]+" + NAME, re.IGNORECASE),
    # .claude/projects/<drive>--<folder>-<name>-proj: Claude Code's memory and transcript folder, for a project on
    # any drive and in any folder; the first word after the drive is checked (a placeholder like C--someone-else passes)
    re.compile(r"\.claude[\\/]+projects[\\/]+[A-Za-z]--" + SLUG_NAME, re.IGNORECASE),
    # pytest-of-<name>: pytest's temp folder (<tmp>/pytest-of-<login>/pytest-N) is named after the OS login, so it
    # leaks through error lines and logs; the name after "pytest-of-" is checked (<USER>, someone, runner pass)
    re.compile(r"(?<![\w-])pytest-of-" + NAME, re.IGNORECASE),
]
# In scrubbed evaluation data (docs/research/data/) no absolute drive path belongs at all, whatever its folders are
# called: the scrubber writes ~ or <scratch>. In JSON a backslash path is written with doubled backslashes.
DATA_DIR = "docs/research/data/"
DRIVE_PATH = re.compile(r"(?<![\w])[A-Za-z]:(?:\\\\|/)[\w.-]+")

# Folder names that are not a person: placeholders, CI runners, test stand-ins.
PLACEHOLDERS = {
    "you", "your", "yourname", "your-name", "user", "username", "user-name", "me", "name", "someone", "somebody",
    "example", "example-user", "alice", "bob", "carol", "jane", "john", "johndoe", "foo", "bar", "test", "tester",
    "runner", "runneradmin", "root", "public", "default", "shared", "all", "all users", "hub", "x", "a", "b", "u",
}


def _allowed(name: str) -> bool:
    n = name.strip().lower()
    if not n.strip(".~…"):                 # "...", "…", "~"
        return True
    if n in PLACEHOLDERS or len(n) == 1:
        return True
    return n.startswith("runner")               # RUNNER~1, the 8.3 name of a CI runner's home


def find_personal_paths(text: str) -> list[str]:
    hits = []
    for pat in PATTERNS:
        for m in pat.finditer(text):
            if not _allowed(m.group(1)):
                hits.append(m.group(0))
    return hits


# An e-mail address that is not a documented placeholder. Allowed domains: RFC 2606 / 6761 names (example.*,
# *.invalid, *.test, *.localhost) and GitHub's noreply addresses. Allowed local parts, at any domain: service
# addresses (noreply@, git@ in SSH clone addresses).
EMAIL = re.compile(r"(?<![\w.+\\-])([\w.+-]+)@([\w-]+(?:\.[\w-]+)*\.[A-Za-z]{2,})(?![\w-])")
EMAIL_DOMAINS_OK = re.compile(
    r"^(?:(?:[\w-]+\.)*example\.(?:com|net|org)|[\w.-]+\.(?:invalid|test|localhost)|(?:[\w-]+\.)*noreply\.github\.com"
    r")$", re.IGNORECASE)
EMAIL_LOCAL_OK = {"noreply", "no-reply", "git"}
# Windows names a fresh machine DESKTOP-<7 chars> (or LAPTOP-), letters and digits; such a name identifies one
# machine. A digit is required so that words like DESKTOP-FRIENDLY pass.
MACHINE = re.compile(r"(?<![\w-])(?:DESKTOP|LAPTOP)-(?=[A-Z0-9]*\d)[A-Z0-9]{6,8}(?![\w-])", re.IGNORECASE)
_ESCAPES = re.compile(r"\\[ntr\"']")         # escape sequences inside string literals: "a\nme@x.test" hides an address


def find_personal_data(text: str) -> list[str]:
    """Paths, e-mail addresses and machine names in one line of text (URL-encoded forms included)."""
    # the raw line, the line with string escapes blanked (an address after a \n), and the URL-decoded forms of both;
    # the raw line keeps a home folder like ...\Users\tom, whose \t the blanking would eat
    blanked = _ESCAPES.sub(" ", text)
    variants = list(dict.fromkeys((text, blanked, unquote(text), unquote(blanked))))
    hits: list[str] = []
    for v in variants:
        hits.extend(find_personal_paths(v))
        for m in EMAIL.finditer(v):
            if "://" in v[max(0, m.start() - 4):m.start()]:     # git+ssh://git@..., https://user@host
                continue
            if EMAIL_DOMAINS_OK.match(m.group(2)) or m.group(1).lower() in EMAIL_LOCAL_OK:
                continue
            hits.append(m.group(0))
        hits.extend(m.group(0) for m in MACHINE.finditer(v))
    return list(dict.fromkeys(hits))


def _tracked_files() -> list[str]:
    if not shutil.which("git") or not (ROOT / ".git").exists():
        pytest.skip("not a git checkout")
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True).stdout
    return [p for p in out.decode("utf-8", "replace").split("\0") if p]


def _lines_of(data: bytes) -> list[str]:
    """A text file's lines (UTF-8, or UTF-16 with a BOM); for a binary file, the printable strings it holds
    (ASCII and UTF-16LE runs of 12+ characters), so a path in an image's metadata is seen too."""
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16", "replace").splitlines()
    if b"\0" not in data[:8192]:
        return data.decode("utf-8", "replace").splitlines()
    runs = [m.group(0).decode("ascii") for m in re.finditer(rb"[\x20-\x7e]{12,}", data)]
    runs += [m.group(0).decode("utf-16-le", "replace") for m in re.finditer(rb"(?:[\x20-\x7e]\x00){12,}", data)]
    return runs


def test_no_personal_paths_in_tracked_files():
    found = []
    for rel in _tracked_files():
        path = ROOT / rel
        try:
            data = path.read_bytes()
        except OSError:                         # deleted in the working tree, a submodule, ...
            continue
        in_data = rel.startswith(DATA_DIR)
        for lineno, line in enumerate(_lines_of(data), 1):
            extra = [m.group(0) for m in DRIVE_PATH.finditer(line)] if in_data else []
            for hit in find_personal_data(line) + extra:
                found.append(f"{rel}:{lineno}: {hit}")
    assert not found, ("personal data in tracked files (a machine path, e-mail address or machine name; use <you>, "
                       "example.com or a placeholder):\n" + "\n".join(found))


# Folders and files that hold one person's local state, at any depth. .gitignore lists them; this makes sure a
# `git add -f` or an older ignore file never lets one through. Not the plugin folders (.claude-plugin/, .codex-plugin/).
LOCAL_STATE = re.compile(r"(?:^|/)(?:\.claude|\.ccx|\.codex|\.ccx-worktrees|_site)/|\.ccx-backup-|-test-log\.txt$"
                         r"|\.local\.[^/]+$", re.IGNORECASE)


def test_no_local_state_files_tracked():
    tracked = [p for p in _tracked_files() if LOCAL_STATE.search(p)]
    assert not tracked, "local-state files are tracked (they belong to one machine):\n" + "\n".join(tracked)


_N = "jdoe42"      # spelled through a variable so this file does not trip its own scan


@pytest.mark.parametrize("text", [
    f"C:\\Users\\{_N}\\proj", f"D:/Users/{_N}/x", f"//c/Users/{_N}/.codex", f"/c/Users/{_N}/x",
    f"see /home/{_N}/.config", f"cd /Users/{_N}/code", f"[projects.'c:\\users\\{_N}\\x']", f"C:\\USERS\\{_N}",
    f"C--Users-{_N}-proj", f"c--users-{_N}", "~/AppData/Local/Temp/" + f"claude/D--Work-{_N}-proj/abc/scratchpad",
    f"\\\\?\\C:\\Users\\{_N}", f"C:\\\\Users\\\\{_N}\\\\x",
    "~/.claude/" + f"projects/D--Work-{_N}-proj/memory", "c:/x/.claude/" + "projects/E--Code-shop/x.jsonl",
    f"/tmp/pytest-of-{_N}/pytest-0/x", f"C:\\Temp\\pytest-of-{_N}\\pytest-3", f"PYTEST-OF-{_N}",
    f"WinError 32: 'pytest-of-{_N}/pytest-1/a.db'",
])
def test_detects_home_folders(text):
    assert find_personal_paths(text)
    assert find_personal_data(text)


# names that start like a string escape (\t, \n, \r): the escape blanking must not hide them
_U = "C:\\" + "Users\\"     # spelled in two parts so this file does not trip its own scan


@pytest.mark.parametrize("text", [
    _U + "tom\\proj", _U.replace("\\", "\\\\") + "tom", _U + "nancy\\x", _U + "rachel\\.codex",
])
def test_names_that_look_like_escapes_are_still_found(text):
    assert find_personal_data(text)


def test_drive_paths_in_scrubbed_data():
    assert DRIVE_PATH.search('"cwd": "D:\\\\Work\\\\proj"') and DRIVE_PATH.search('"cwd": "D:/Work/proj"')
    assert not DRIVE_PATH.search('"code):\\nfrom x import y"') and not DRIVE_PATH.search('"~/AppData/Local/Temp/x"')


@pytest.mark.parametrize("text", [
    "C:\\Users\\<you>\\hub", "/home/<you>/.ccx-hub", "C:\\Users\\RUNNER~1\\AppData", "/home/runner/work",
    "//c/Users/a/.codex", "/Users/example/x", "C:\\Users\\...\\x", "D:/x/home/memories/MEMORY.md", "~/.ccx-hub",
    "$HOME/.agents", "%USERPROFILE%\\.codex", "C:\\Users\\All Users\\x", "c:\\users\\…\\x", "C--Users-you-proj",
    "Temp/claude/<project>/x", "/tmp/claude/x/scratchpad", "~/.claude/projects/<project-slug>/x",
    "/h/.claude/projects/C--someone-else/memory/", "/h/.claude/projects/-w-1-t-ccx/memory/",
    "/tmp/pytest-of-<USER>/pytest-0", "pytest-of-USER", "pytest-of-someone", "pytest-of-SomeOne/pytest-1",
    "pytest-of-runner", "pytest-of-user", "pytest-of-root", "pytest-of-[^\\\\/\\s]+", "pytest-of-<you>", "pytest-of-",
])
def test_allows_placeholders(text):
    assert not find_personal_paths(text)


_D = "gmail" + ".com"      # spelled in two parts so this file does not trip its own scan
_M = "DESKTOP" + "-AB12CD3"
_L = "LAPTOP" + "-9XK2Q7PZ"


@pytest.mark.parametrize("text", [
    f"wrote to {_N}@{_D} yesterday", f"author: {_N}42@outlook.{_D.split('.')[1]}", f"<{_N}@my-company.co.uk>",
    f"machine {_M}", f"host: {_L}", f"{_M.lower()}\\{_N}", f"[user]\n\temail = {_N}@{_D}",
    f'"line one\\n{_N}@{_D}"', f"mailto:{_N}@{_D}", f"file:///c%3A/Users/{_N}/x", f"{_N}%40{_D}",
    f"me@{_N}-home.net", f"ci@{_N}.dev", f"ssh {_N}@corp-mail.com", f"me@{_N}.com",
])
def test_detects_addresses_and_machine_names(text):
    assert find_personal_data(text)


@pytest.mark.parametrize("text", [
    "ci@example.com", "t@example.invalid", "me@example.com", "@user.setter", "@pytest.mark.parametrize",
    "12345678+someone@users.noreply.github.com", "Claude <noreply@anthropic.com>", "a@b.test", "x@sub.example.org",
    "git@github.com:owner/repo.git", "pip install git+ssh://git@github.com/o/r", "ssh git@example.com",
    "DESKTOP-x (a word, not a name)", "see the desktop-first layout", "DESKTOP-ABC", "LAPTOP-FRIENDLY",
    "DESKTOP-CLOSED", "react@18.3.1", "actions/checkout@v4", '"a\\n@pytest.fixture"',
])
def test_allows_placeholder_addresses(text):
    assert not find_personal_data(text)


@pytest.mark.parametrize("path", [
    ".claude/settings.local.json", "sub/.claude/x.json", ".ccx/handoff.md", "x/.ccx/journal.md", ".codex/config.toml",
    ".ccx-worktrees/a/b.py", "_site/index.html", "two-way-test-log.txt", "logs/x-test-log.txt", "CLAUDE.local.md",
    "x.ccx-backup-20261030", "a/b.LOCAL.JSON", "run.local.ps1",
])
def test_local_state_shapes(path):
    assert LOCAL_STATE.search(path)


@pytest.mark.parametrize("path", [
    ".claude-plugin/plugin.json", ".codex-plugin/plugin.json", "tests/fakes/local_cli.py", "docs/local-page.md",
    "site/index.html", "ccx/ui_static/app.js", "hooks/claude-hooks.json",
])
def test_local_state_allows_project_files(path):
    assert not LOCAL_STATE.search(path)


@pytest.mark.parametrize("data, hit", [
    (f"C:\\Users\\{_N}\\x\n".encode("utf-16"), True),                    # UTF-16 with a BOM (PowerShell 5.1 Out-File)
    (b"\x89PNG\r\n\x1a\n\0\0\0\rIHDR" + f"tEXtComment\0path C:\\Users\\{_N}\\shots".encode() + b"\0" * 40, True),
    (b"\x89PNG\r\n\x1a\n\0\0\0\rIHDR" + bytes(range(256)) * 4, False),
])
def test_binary_and_utf16_files_are_scanned(data, hit):
    found = [h for line in _lines_of(data) for h in find_personal_data(line)]
    assert bool(found) is hit
