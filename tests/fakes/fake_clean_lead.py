"""Stand-in for a headless `claude -p` lead that would pick up everything a careless eval leaves within reach.

It resolves files the way Claude Code 2.1.309 does (as far as its docs say) and the way a curious model would:
  - the config dir: CLAUDE_CONFIG_DIR, else ~/.claude; its settings.json only when --setting-sources has "user"
  - hooks from the loaded settings run (a system/hook_started event) unless disableAllHooks
  - the user-level CLAUDE.md is loaded unless claudeMdExcludes (from --settings) matches it; this fake assumes the
    worst case, that --setting-sources alone does not drop it
  - auto-memory at <config>/projects/<slug>/memory unless CLAUDE_CODE_DISABLE_AUTO_MEMORY=1 or autoMemoryEnabled false
  - the ccx hub: CCX_HUB, else `hub` in CCX_CONFIG or ~/.ccx/config.toml; it reads <hub>/memory/MEMORY.md
  - the Codex home: CODEX_HOME, else ~/.codex; it reads AGENTS.md there
  - FAKE_READ: more paths (os.pathsep-separated) it tries to Read; a permissions.deny Read(//<path>/**) rule blocks
Every file it manages to read that contains "SENTINEL" is reported. The project's CLAUDE.md (and an @AGENTS.md
import) is always read, as the real CLI does. The result line is "OTHER: <sentinels>" or "PROJECT-ONLY <word>".
"""
import fnmatch
import json
import os
import re
import sys
import tomllib
import uuid
from pathlib import Path

argv = sys.argv[1:]
if argv[:1] == ["--version"]:
    print("2.1.309 (Claude Code, fake clean lead)")
    sys.exit(0)
sys.stdin.read()


def opt(name):
    return argv[argv.index(name) + 1] if name in argv else None


home = Path.home()
cfg = Path(os.environ.get("CLAUDE_CONFIG_DIR") or home / ".claude")
sources = (opt("--setting-sources") or "user,project,local").split(",")
settings = {}
if "user" in sources and (cfg / "settings.json").exists():
    settings.update(json.loads((cfg / "settings.json").read_text(encoding="utf-8")))
extra = opt("--settings")
if extra:
    settings.update(json.loads(extra if extra.lstrip().startswith("{") else Path(extra).read_text(encoding="utf-8")))

deny = (settings.get("permissions") or {}).get("deny") or []


def posix_form(p: str) -> str:
    """Claude Code's permissions docs: "On Windows, paths are normalized to POSIX form before matching.
    C:\\Users\\alice becomes /c/Users/alice"."""
    p = p.replace("\\", "/")
    m = re.match(r"^([A-Za-z]):(.*)$", p)
    return f"/{m.group(1).lower()}{m.group(2)}" if m else p


def denied(p: Path) -> bool:
    pp = posix_form(p.resolve().as_posix())
    for rule in deny:
        m = re.fullmatch(r"Read\((.*)\)", rule)
        if not m:
            continue
        pat = m.group(1)
        if pat.startswith("~/"):
            pat = posix_form(home.as_posix()) + pat[1:]
        elif pat.startswith("//"):
            pat = pat[1:]                  # //c/Users/... -> /c/Users/...; a //C:/... rule never matches
        else:
            continue
        if fnmatch.fnmatchcase(pp, pat) or fnmatch.fnmatchcase(pp, pat.rstrip("/*")):
            return True
    return False


seen = []


def read(p: Path, tool: bool = True) -> str:
    if not p.is_file() or (tool and denied(p)):
        return ""
    text = p.read_text(encoding="utf-8", errors="replace")
    if "SENTINEL" in text:
        seen.append(p.name + ":" + text.strip().split()[0])
    return text


events = []
if settings.get("hooks") and not settings.get("disableAllHooks"):
    events.append({"type": "system", "subtype": "hook_started", "hook_name": "SessionStart"})

excludes = settings.get("claudeMdExcludes") or []
user_md = cfg / "CLAUDE.md"
if not any(fnmatch.fnmatch(str(user_md), x) or fnmatch.fnmatch(user_md.as_posix(), x) for x in excludes):
    read(user_md, tool=False)

project = Path.cwd() / "CLAUDE.md"
word = ""
if project.exists():
    body = project.read_text(encoding="utf-8")
    if "@AGENTS.md" in body and (Path.cwd() / "AGENTS.md").exists():
        body += (Path.cwd() / "AGENTS.md").read_text(encoding="utf-8")
    m = re.search(r"add the word (\S+?)\.", body)
    word = m.group(1) if m else ""

# the real CLI lists the auto-memory folder of the working directory in its init event (every round-5 stream did);
# assume the worst, that it still does with auto-memory off
mem = cfg / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(Path.cwd())) / "memory"
memory_paths = {"auto": str(mem) + os.sep}
if os.environ.get("CLAUDE_CODE_DISABLE_AUTO_MEMORY") != "1" and settings.get("autoMemoryEnabled", True):
    read(mem / "MEMORY.md", tool=False)

hub = os.environ.get("CCX_HUB")
if not hub:
    conf = Path(os.environ.get("CCX_CONFIG") or home / ".ccx" / "config.toml")
    try:
        hub = tomllib.loads(conf.read_text(encoding="utf-8")).get("hub")
    except (OSError, tomllib.TOMLDecodeError):
        hub = None
if hub:
    read(Path(hub) / "memory" / "MEMORY.md")
read(Path(os.environ.get("CODEX_HOME") or home / ".codex") / "AGENTS.md")
for x in filter(None, os.environ.get("FAKE_READ", "").split(os.pathsep)):
    read(Path(x))

sid = str(uuid.uuid4())
init = {"type": "system", "subtype": "init", "session_id": sid, "model": "fake", "mcp_servers": [], "skills": [],
        "plugins": [{"name": "cc-plugin-agents-md", "path": "builtin", "source": "cc-plugin-agents-md@builtin"}],
        "agents": ["claude", "Explore", "general-purpose", "Plan", "statusline-setup"], "slash_commands": [],
        "output_style": "default", "claude_code_version": "2.1.309"}
init["memory_paths"] = memory_paths
if os.environ.get("FAKE_WEB_FETCH_AGENT") and os.environ.get("CLAUDE_CODE_DISABLE_WEB_FETCH") != "1":
    init["agents"].append("web-fetch")     # Claude Code 2.1.316 lists its built-in web-fetch agent unless switched off
if "--disable-slash-commands" not in argv and "Skill" in (opt("--tools") or "").split(","):
    # a skill lead: skills load, Claude Code's own bundled ones (FAKE_BUNDLED_SKILLS), the config dir's and the
    # project's (a lead without the Skill tool lists none here, as the older tests expect)
    found = [x for x in (os.environ.get("FAKE_BUNDLED_SKILLS", "simplify,update-config")).split(",") if x]
    for d in (cfg / "skills", Path.cwd() / ".claude" / "skills"):
        found += sorted(p.name for p in d.iterdir() if (p / "SKILL.md").exists()) if d.is_dir() else []
    init["skills"] = found
    init["slash_commands"] = ["/" + x for x in found]
answer = ("OTHER: " + ", ".join(seen)) if seen else f"PROJECT-ONLY {word}".strip()
# FAKE_SPLIT_ANSWER: the answer in a first message, then a Read and a last message that alone is the result (as
# haiku did on 2026-10-28)
last = "The Read was denied, so there is nothing to append." if os.environ.get("FAKE_SPLIT_ANSWER") else answer
split = [{"type": "assistant", "message": {"id": "m0", "content": [{"type": "text", "text": answer},
                                                                   {"type": "tool_use", "name": "Read", "input": {}}],
                                           "usage": {"input_tokens": 1, "output_tokens": 1}}}] if last != answer else []
for ev in [*events, init, *split,
           {"type": "assistant", "message": {"id": "m1", "content": [{"type": "text", "text": last}],
                                             "usage": {"input_tokens": 1, "output_tokens": 1}}},
           {"type": "result", "subtype": "success", "is_error": False, "result": last, "session_id": sid,
            "total_cost_usd": 0.0, "usage": {"input_tokens": 1, "output_tokens": 1}}]:
    print(json.dumps(ev), flush=True)
