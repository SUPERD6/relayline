"""A handoff written from the outgoing lead's session file, for when it can't write one itself (quota out, crashed,
window closed). Code only — no model tokens. What the next lead needs, most important first: the goal, the agent's
own plan, the person's recent messages, where it stopped, what changed and what failed, the tree on disk, unfinished
tasks, and where the full transcript is.

Formats read (checked against real files, 2026-10-24):
  Codex 0.164 desktop rollouts — event_msg item_completed items: UserMessage, AgentMessage (phase final_answer),
    CommandExecution (command, exit_code, aggregated_output), FileChange (changes: {path: ...});
    task_complete.last_agent_message. Older/headless rollouts: response_item message (role user/assistant),
    function_call update_plan / apply_patch, event_msg user_message / agent_message.
  Claude Code projects/<folder>/<session>.jsonl — user / assistant records; tool_use Edit / Write / MultiEdit
    (file_path), TodoWrite (todos), the desktop app's plan tool (…update_plan, items), Bash + tool_result is_error.
Neither format always carries a plan; the git state is the ground truth and is always included."""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path

MAX_CHARS = 6000            # about one page (~1.5k tokens); --max-chars to change
_SECRET = re.compile(
    r"(sk-[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9]{20,}|gh[ousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|xox[abp]-[A-Za-z0-9-]{10,}"
    r"|(?i:bearer)\s+[A-Za-z0-9._-]{20,}|(?i:(?:password|passwd|secret|token|api[_-]?key)\s*[=:]\s*)\S{6,}"
    r"|\b[0-9a-f]{40,}\b)")
_INJECTED = ("# AGENTS.md instructions", "<environment_context>", "<user_instructions>", "<permissions",
             "<command-name>", "<local-command", "<system-reminder>", "Caveat:")


def redact(text: str) -> str:
    return _SECRET.sub("[redacted]", text or "")


_WRAPPED = re.compile(r"<([a-z][a-z0-9_-]*)\b[^>]*>.*?</\1>", re.S)   # app-injected blocks inside a user turn


def _user_text(t: str) -> str | None:
    t = _WRAPPED.sub("", t or "").strip()
    return None if not t or t.startswith(_INJECTED) else t


_TASK_BRIEF = re.compile(
    r"\[ccx (?:sub-task|shared work context)|"
    r"(?:^|\n)\s*(?:#{1,6}\s*)?(?:Task|任务)\s*(?:[:：]|\n|$)|"
    r"Background \(from the session that started this one\)|"
    r"你是[^\n。]{0,100}(?:主统筹|接替|接任)", re.I)


def _preference_text(t: str) -> str | None:
    """A user-role envelope can contain an agent's assignment, not the person's words.

    ccx/prompts.py emits `[ccx sub-task]`; lead handoffs use a Background/Task
    heading. Role alone cannot establish authorship for these briefs. Claude's
    isMeta/isSidechain/isCompactSummary flags are handled by read_claude; Codex's
    session_meta originator/source by read_codex. Unmarked ordinary user text has
    no finer author field in the formats we read; do not invent one.
    """
    text = _user_text(t)
    return text if text and not _TASK_BRIEF.search(text) else None


def _append_user(d: dict, raw: str, delegated: bool = False) -> bool:
    text = _user_text(raw)
    if text:
        # Without spawn metadata, a first-turn task brief still identifies an
        # agent-started session. Return the state for every Codex message format.
        if not d["users"] and _TASK_BRIEF.search(text):
            delegated = True
        d["users"].append(text)  # preserve the handoff reader's existing field
        human = _preference_text(raw)
        # A spawned/headless helper's user turns can all come from its lead.
        # There is no verified human-author signal for later turns either.
        if human and not delegated:
            d["preference_users"].append(human)
    return delegated


def read_codex(path: Path) -> dict:
    d = {"agent": "codex", "users": [], "final": "", "plan": [], "files": [], "failed": [], "texts": [],
         "session": None, "preference_users": []}
    delegated = False
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        pl = e.get("payload") or {}
        typ = pl.get("type")
        it = pl.get("item") or {}
        if e.get("type") == "session_meta" and not d["session"]:
            from .usage import codex_parent
            d["session"] = pl.get("id") or pl.get("session_id")
            # These are the existing ccx session-discovery/usage signals for a
            # headless run or native spawned helper, not a guessed author field.
            delegated = pl.get("originator") == "codex_exec" or bool(codex_parent(pl))
        if typ == "item_completed" and it.get("type") == "AgentMessage":
            d["texts"].append("".join(c.get("text", "") for c in it.get("content") or []))
        elif typ == "agent_message" and pl.get("message"):
            d["texts"].append(pl["message"])
        elif e.get("type") == "response_item" and typ == "message" and pl.get("role") == "assistant":
            d["texts"].append("".join(c.get("text", "") for c in pl.get("content") or []))
        if typ == "item_completed" and it.get("type") == "UserMessage":
            delegated = _append_user(d, "".join(c.get("text", "") for c in it.get("content") or []), delegated)
        elif typ == "item_completed" and it.get("type") == "AgentMessage" and it.get("phase") == "final_answer":
            d["final"] = "".join(c.get("text", "") for c in it.get("content") or [])
        elif typ == "item_completed" and it.get("type") == "FileChange":
            d["files"] += list((it.get("changes") or {}).keys())
        elif typ == "item_completed" and it.get("type") == "CommandExecution" and it.get("exit_code") not in (0, None):
            cmd = it.get("command") or []
            d["failed"].append({"cmd": cmd[-1] if isinstance(cmd, list) and cmd else str(cmd),
                                "exit": it.get("exit_code"), "out": (it.get("aggregated_output") or "")[-300:]})
        elif typ == "task_complete" and pl.get("last_agent_message"):
            d["final"] = pl["last_agent_message"]
        elif typ == "user_message":
            delegated = _append_user(d, pl.get("message") or "", delegated)
        elif typ == "agent_message" and pl.get("message"):
            d["final"] = pl["message"]
        elif e.get("type") == "response_item" and typ == "function_call":
            try:
                args = json.loads(pl.get("arguments") or "{}")
            except ValueError:
                args = {}
            if pl.get("name") == "update_plan" and isinstance(args.get("plan"), list):
                d["plan"] = [{"step": s.get("step"), "status": s.get("status")} for s in args["plan"]]
            elif pl.get("name") == "apply_patch":
                d["files"] += re.findall(r"\*\*\* (?:Update|Add|Delete) File: (.+)", str(args.get("input") or args))
    if not d["users"]:                        # very old format: user turns only as response_item messages
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                pl = (json.loads(line).get("payload") or {})
            except ValueError:
                continue
            if pl.get("type") == "message" and pl.get("role") == "user":
                delegated = _append_user(d, "".join(c.get("text", "") for c in pl.get("content") or []), delegated)
    return d


def read_claude(path: Path) -> dict:
    d = {"agent": "claude", "users": [], "final": "", "plan": [], "files": [], "failed": [], "texts": [],
         "session": path.stem, "preference_users": []}
    bash: dict[str, str] = {}
    delegated = False
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("isSidechain") or e.get("isMeta") or e.get("isCompactSummary"):
            continue
        msg = e.get("message") or {}
        content = msg.get("content")
        if e.get("type") == "user":
            # One user turn may contain several text blocks. Classify the whole
            # brief so a second block cannot turn its instructions into preferences.
            raw = content if isinstance(content, str) else "\n".join(
                c.get("text", "") for c in content or [] if c.get("type") == "text")
            text = _user_text(raw)
            if not d["users"] and text and _TASK_BRIEF.search(text):
                # A task brief as the first real user turn identifies an agent-
                # started session. Later user-role turns may also be from its
                # lead, so exclude preferences for the whole session.
                delegated = True
            human = _preference_text(raw)
            if human and not delegated:
                d["preference_users"].append(human)
            if isinstance(content, str):
                t = _user_text(content)
                if t:
                    d["users"].append(t)
            for c in content if isinstance(content, list) else []:
                if c.get("type") == "text":
                    t = _user_text(c.get("text", ""))
                    if t:
                        d["users"].append(t)
                elif c.get("type") == "tool_result" and c.get("is_error") and c.get("tool_use_id") in bash:
                    out = c.get("content")
                    out = out if isinstance(out, str) else json.dumps(out, ensure_ascii=False)
                    d["failed"].append({"cmd": bash[c["tool_use_id"]], "exit": "error", "out": out[-300:]})
        elif e.get("type") == "assistant":
            texts = [c.get("text", "") for c in content or [] if isinstance(c, dict) and c.get("type") == "text"]
            if any(t.strip() for t in texts):
                d["final"] = "\n".join(t for t in texts if t.strip())
                d["texts"].append(d["final"])
            for c in content or []:
                if not isinstance(c, dict) or c.get("type") != "tool_use":
                    continue
                name, inp = c.get("name") or "", c.get("input") or {}
                if name in ("Edit", "Write", "MultiEdit", "NotebookEdit") and inp.get("file_path"):
                    d["files"].append(inp["file_path"])
                elif name == "TodoWrite" and isinstance(inp.get("todos"), list):
                    d["plan"] = [{"step": t.get("content"), "status": t.get("status")} for t in inp["todos"]]
                elif name.endswith("update_plan"):
                    _plan_update(d["plan"], inp)
                elif name == "Bash":
                    bash[c.get("id")] = inp.get("command") or ""
    return d


def _plan_update(plan: list[dict], inp: dict) -> None:
    """The desktop app's plan tool: a whole list (`items`), or a change to the last one: `advance` (finish the
    step in progress, start the next pending one), `done` (1-based steps finished), `start` (step now in progress)."""
    if isinstance(inp.get("items"), list):
        plan[:] = [{"step": t.get("content"), "status": t.get("status")} for t in inp["items"]]
        return
    if inp.get("advance"):
        cur = next((s for s in plan if s["status"] == "in_progress"), None)
        if cur:
            cur["status"] = "completed"
        nxt = next((s for s in plan if s["status"] == "pending"), None)
        if nxt:
            nxt["status"] = "in_progress"
    for i in inp.get("done") or []:
        if isinstance(i, int) and 0 < i <= len(plan):
            plan[i - 1]["status"] = "completed"
    i = inp.get("start")
    if isinstance(i, int) and 0 < i <= len(plan):
        for s in plan:
            if s["status"] == "in_progress":
                s["status"] = "pending"
        plan[i - 1]["status"] = "in_progress"


def _codex_sessions(home: Path) -> list[Path]:
    from .usage import walk
    return sorted(walk(home / "sessions", "rollout-*.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True)


CLAUDE_SLUG_MAX = 200     # Claude Code cuts a longer folder name to 200 characters plus "-<hash>" (seen on 2.1.309)


def long_path(p: Path, below: int = 0) -> Path:
    r"""Windows: a file `below` characters under p that passes the 260-character limit only opens with the \\?\
    prefix; shorter paths are left as they are."""
    s = str(p)
    if os.name != "nt" or s.startswith("\\\\") or len(str(p.resolve())) + below < 250:
        return p
    return Path("\\\\?\\" + str(p.resolve()))


def claude_project_dirs(root: Path, home: Path | None = None) -> list[Path]:
    """The folders Claude Code keeps root's sessions in: <projects>/<root, every non-alphanumeric a '-'>; a name
    longer than 200 characters is cut to 200 plus "-<hash>", so those are found by the first 200 (two projects that
    share them both match)."""
    from .config import claude_home
    slug = re.sub(r"[^A-Za-z0-9]", "-", str(Path(root).resolve()))
    base = long_path((home or claude_home()) / "projects", min(len(slug), CLAUDE_SLUG_MAX + 8) + 50)
    if len(slug) <= CLAUDE_SLUG_MAX:
        return [base / slug] if (base / slug).exists() else []
    head = slug[:CLAUDE_SLUG_MAX] + "-"
    try:
        return [d for d in base.iterdir() if d.is_dir() and (d.name == slug or d.name.startswith(head))]
    except OSError:
        return []


def claude_session_file(session: str, home: Path | None = None) -> Path | None:
    """A Claude session's file by its id, in whichever project folder it is."""
    from .config import claude_home
    base = (home or claude_home()) / "projects"
    hits = list(base.glob(f"*/{session}.jsonl"))
    if not hits and long_path(base, 260) != base:      # a session in a long-named folder: only seen with the prefix
        hits = list(long_path(base, 260).glob(f"*/{session}.jsonl"))
    return hits[0] if hits else None


def _resolved(cwd) -> str:
    """A recorded folder as `here` is written: Windows may record a short 8.3 name (C:\\Users\\RUNNER~1\\...)."""
    if not cwd:
        return ""
    try:
        return str(Path(cwd).resolve()).lower().rstrip("\\/")
    except OSError:
        return str(cwd).lower().rstrip("\\/")


def find_session(agent: str, root: Path, exclude: set[str], session: str | None = None,
                 codex_home: Path | None = None, claude_home: Path | None = None) -> Path | None:
    """The newest main session of `agent` in this project folder (not a ccx sub-run, not a sub-agent)."""
    from .config import claude_home as ch, codex_home as xh
    from .usage import codex_parent
    here = str(root.resolve()).lower().rstrip("\\/")
    if agent == "codex":
        for f in _codex_sessions(codex_home or xh()):
            if session and session not in f.name:
                continue
            try:
                with f.open(encoding="utf-8", errors="replace") as fh:
                    meta = (json.loads(fh.readline()) or {}).get("payload") or {}
            except (OSError, ValueError):
                continue
            sid = meta.get("id") or meta.get("session_id")
            if session or (_resolved(meta.get("cwd")) == here
                           and meta.get("originator") != "codex_exec" and not codex_parent(meta)
                           and sid not in exclude):
                return f
        return None
    cands = sorted((f for d in claude_project_dirs(root, claude_home or ch()) for f in d.glob("*.jsonl")),
                   key=lambda f: f.stat().st_mtime, reverse=True)
    for f in cands:
        if (session and f.stem == session) or (not session and f.stem not in exclude):
            return f
    return None


def _git(root: Path, *args: str) -> str:
    try:
        r = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=20,
                           stdin=subprocess.DEVNULL, encoding="utf-8", errors="replace")
        return r.stdout.rstrip().lstrip("\n") if r.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _first_sentence(t: str) -> str:
    t = " ".join(t.split())
    m = re.match(r"(.+?[.!?。！？])(\s|$)", t)
    return (m.group(1) if m else t)[:160]


_NUMBERED = re.compile(r"^\s*(\d{1,2})[.)、．]\s+(\S.*)$")


def plan_from_text(texts: list[str]) -> list[str]:
    """No plan tool was used: the numbered list (2+ items) in the agent's latest message that has one."""
    for t in reversed(texts or []):
        steps = [m.group(2).strip() for m in map(_NUMBERED.match, (t or "").splitlines()) if m]
        if len(steps) >= 2:
            return [x[:200] for x in steps[:15]]
    return []


def _plan_text(d: dict) -> str:
    if d["plan"]:
        return "\n".join(f"- [{'x' if p.get('status') == 'completed' else ' '}] {p.get('step')} ({p.get('status')})"
                         for p in d["plan"])
    steps = plan_from_text(d.get("texts") or [])
    if steps:
        return ("(no plan tool was used: the numbered list from its latest message that had one; which steps are "
                "done is not tracked)\n" + "\n".join(f"{i}. {x}" for i, x in enumerate(steps, 1)))
    return "(no plan list found in the transcript: judge from the sections below)"


def build(d: dict, root: Path, path: Path, unfinished: str = "", max_chars: int = MAX_CHARS, runs: str = "") -> str:
    users = d["users"]
    goal = users[0] if users else "(no user message found)"
    recent = users[-3:] if len(users) > 1 else []
    earlier = users[1:-3] if len(users) > 4 else []
    files = list(dict.fromkeys(d["files"]))
    status = _git(root, "status", "--short")
    stat = _git(root, "diff", "--stat")
    parts = [
        f"_Auto-assembled from the {d['agent']} session file by `ccx handoff --from-transcript` "
        f"({time.strftime('%Y-%m-%d %H:%M')}); the agent did not write it. Check before trusting: the files exist, "
        f"the tests named here pass, `git status` matches._",
        "## Goal (the person's first message)\n" + goal[:1200],
        "## Plan, as the agent last left it\n" + _plan_text(d),
        "## The person's recent messages\n" + ("\n".join(f"- {u[:600]}" for u in recent) or "(none)")
        + ("\n\nEarlier, first sentences only:\n" + "\n".join(f"- {_first_sentence(u)}" for u in earlier[-8:])
           if earlier else ""),
        "## Where it stopped (the agent's last conclusion)\n" + ((d["final"] or "(none)")[-1500:]),
        "## Files it changed\n" + ("\n".join(f"- {f}" for f in files[-25:]) or "(none recorded)")
        + ("\n\nLast failed commands:\n" + "\n".join(f"- `{x['cmd'][:160]}` (exit {x['exit']}): {x['out'][-160:]}"
                                                     for x in d["failed"][-3:]) if d["failed"] else ""),
        "## On disk now\n```\n" + (status or "(clean or not a git repository)") + "\n```"
        + (f"\n```\n{stat}\n```" if stat else ""),
    ]
    if runs:
        parts.append("## ccx runs from this conversation (newest last)\n" + runs)
    if unfinished:
        parts.append("## Unfinished tasks\n" + unfinished)
    parts.append(f"## Full transcript\n`{path}` — open it for details; it is not copied here.")
    text = redact("\n\n".join(parts))
    if len(text) > max_chars:                    # trim the long free-text parts first, keep the structure
        cut = len(text) - max_chars
        text = text.replace(goal[:1200], goal[:max(200, 1200 - cut)], 1)
        if len(text) > max_chars:
            tail = "\n\n… (trimmed to one page; see the full transcript)"
            text = text[:max_chars - len(tail)] + tail
    return text


def empty(d: dict) -> bool:
    """Code found nothing it recognises (a format it doesn't know): time for the model fallback."""
    return not (d["users"] or d["final"] or d["files"] or d["plan"])


MODEL_BRIEF = """Write a handoff for the next lead from a session file ccx's code could not read (unknown format).
File: {path} ({agent}, {size} KB). Read its last part first, then earlier parts only as needed; do not change it.
Write the handoff, at most one page, to {out} (create that one file, touch nothing else), with these sections:
## Goal  ## Plan (steps and status)  ## The person's recent messages  ## Where it stopped
## Files it changed and failed commands  ## Open questions
Facts from the file only; say Unknown where it doesn't tell. Never copy keys, tokens or passwords."""


def from_model(text: str, by: str, root: Path, path: Path, unfinished: str = "", max_chars: int = MAX_CHARS) -> str:
    status = _git(root, "status", "--short")
    parts = [f"_Written by {by} from the session file (`ccx handoff --from-transcript`, model fallback: the code "
             f"could not read its format; {time.strftime('%Y-%m-%d %H:%M')}). Check before trusting._",
             text.strip()[:max_chars * 3 // 4],
             "## On disk now\n```\n" + (status or "(clean or not a git repository)") + "\n```"]
    if unfinished:
        parts.append("## Unfinished tasks\n" + unfinished)
    parts.append(f"## Full transcript\n`{path}`")
    out = redact("\n\n".join(parts))
    return out if len(out) <= max_chars else out[:max_chars - 20] + "\n\n… (trimmed)"
