"""Lead-side usage: what the orchestrating agent itself spent, read from each tool's own session logs.

Sub-agent usage is exact (ccx records it per run). The lead's usage is not visible to ccx, so it is read
from the transcripts both tools already keep:

  Claude Code  <CLAUDE_CONFIG_DIR or ~/.claude>/projects/*/<session>.jsonl
               lines type=assistant: message.id, message.model, message.usage (Anthropic buckets),
               timestamp, sessionId. One message may span several lines -> de-duplicated by message.id.
  Codex        <CODEX_HOME or ~/.codex>/sessions/YYYY/MM/DD/rollout-*.jsonl
               session_meta (payload.id), turn_context (payload.model),
               event_msg payload.type=token_count: info.last_token_usage (per request; cached is a subset
               of input), rate_limits.primary/secondary.used_percent (quota windows).
               Format checked against codex-cli docs/source, not yet against a live file: verify (v0.3).

Sessions that ccx itself started as sub-agents are excluded (their usage is already in the ledger).
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path

from .config import claude_home, codex_home, load_config
from .runners import usage_dict


def _ts(s: str | None) -> float | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _scan_path(d: Path) -> str:
    r"""Windows: a folder near the 260-character limit is listed with the \\?\ prefix (scandir adds "\*" to it,
    and Path.rglob raised WinError 3 on such a folder that plainly exists); elsewhere the path as it is."""
    s = str(d)
    if os.name != "nt" or s.startswith("\\\\") or len(s) < 240:
        return s
    return "\\\\?\\" + os.path.abspath(s)


def walk(root: Path, pattern: str, skipped: list | None = None):
    """Files under root whose name matches pattern, like root.rglob(pattern), but a folder that cannot be listed —
    removed while walking (a temporary scratchpad's sessions), or too long a path — is skipped and noted in
    `skipped` as (folder, reason) instead of ending the whole walk with FileNotFoundError."""
    import fnmatch
    root = Path(root)
    stack = [root]
    while stack:
        d = stack.pop()
        try:
            with os.scandir(_scan_path(d)) as it:
                entries = list(it)
        except OSError as e:
            if skipped is not None and d != root:
                skipped.append((d, "files gone" if isinstance(e, FileNotFoundError) else
                                f"files unreadable ({type(e).__name__})"))
            continue
        subdirs = []
        for e in entries:
            try:
                is_dir = e.is_dir(follow_symlinks=False)
            except OSError:
                continue
            if is_dir:
                subdirs.append(Path(e.path))
            elif fnmatch.fnmatch(e.name, pattern):
                yield Path(_scan_path(Path(e.path)))   # a short folder can still hold a file past the limit
        stack.extend(reversed(subdirs))   # folders in listing order, as rglob gave them (callers keep the last)


def _recent(files, since: float, skipped: list | None = None):
    """Files changed since `since`; one that cannot be read is noted in `skipped` (see walk)."""
    for f in files:
        try:
            if f.stat().st_mtime >= since:
                yield f
        except OSError as e:
            if skipped is not None:
                skipped.append((f, "files gone" if isinstance(e, FileNotFoundError) else
                                f"files unreadable ({type(e).__name__})"))
            continue


def _helper_parent(f: Path) -> str | None:
    """The main session a built-in helper's file belongs to: projects/<folder>/<session>/subagents/agent-*.jsonl,
    and a workflow's agents one level deeper, <session>/subagents/workflows/wf_*/agent-*.jsonl."""
    for d in f.parents:
        if d.name == "subagents":
            return d.parent.name
        if d.name == "projects":
            break
    return None


def _claude_file(f: Path, since: float, exclude: set[str], msgs: dict[str, dict],
                 skipped: list | None = None) -> None:
    try:
        lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as e:
        if skipped is not None:
            skipped.append((f, "files gone" if isinstance(e, FileNotFoundError) else
                            f"files unreadable ({type(e).__name__})"))
        return
    parent = _helper_parent(f)
    for line in lines:
        if '"assistant"' not in line or '"usage"' not in line:
            continue
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        if e.get("type") != "assistant":
            continue
        sid = e.get("sessionId") or f.stem
        if sid in exclude:          # a ccx sub-run (incl. its own built-in helpers): already in the ledger
            continue
        builtin = bool(e.get("isSidechain")) or parent is not None
        m = e.get("message") or {}
        u = m.get("usage") or {}
        t = _ts(e.get("timestamp"))
        if not u or t is None or t < since:
            continue
        cc = u.get("cache_creation") or {}
        key = m.get("id") or e.get("uuid")
        msgs[key] = {"ts": t, "agent": "claude", "role": "builtin" if builtin else "lead",
                     "session": f.stem if builtin else sid,
                     **({"parent": parent} if builtin and parent else {}),
                     **({"workflow": f.parent.name} if parent and f.parent.name.startswith("wf_") else {}),
                     "model": m.get("model") or e.get("requestedModel") or "?",
                     "usage": usage_dict(fresh=u.get("input_tokens", 0) or 0,
                                         write=u.get("cache_creation_input_tokens", 0) or 0,
                                         write_1h=cc.get("ephemeral_1h_input_tokens", 0) or 0,
                                         cached=u.get("cache_read_input_tokens", 0) or 0,
                                         out=u.get("output_tokens", 0) or 0)}


def claude_events(since: float, exclude: set[str], home: Path | None = None,
                  skipped: list | None = None) -> list[dict]:
    """Every Claude turn since `since`; folders that cannot be listed are noted in `skipped` (see walk)."""
    root = (home or claude_home()) / "projects"
    if not root.exists():
        return []
    msgs: dict[str, dict] = {}
    # main sessions: projects/<folder>/<session>.jsonl; Claude Code's own (built-in) sub-agents:
    # projects/<folder>/<session>/subagents/agent-*.jsonl with isSidechain = true, and a workflow's
    # agents under <session>/subagents/workflows/wf_*/
    for f in _recent(walk(root, "*.jsonl", skipped), since, skipped):
        _claude_file(f, since, exclude, msgs, skipped)
    return list(msgs.values())


def claude_session_events(session: str, home: Path | None = None) -> list[dict]:
    """One Claude conversation and everything it ran itself (built-in helpers, workflow agents), read from only
    that conversation's files."""
    root = (home or claude_home()) / "projects"
    msgs: dict[str, dict] = {}
    for f in session_files(session, home):
        _claude_file(f, 0.0, set(), msgs)
    return list(msgs.values())


def session_files(session: str, home: Path | None = None, skipped: list | None = None) -> list[Path]:
    """A Claude conversation's own file and its helpers' and workflow agents' files, in whichever project folder;
    a folder that cannot be listed is noted in `skipped` (see walk)."""
    root = (home or claude_home()) / "projects"
    out: list[Path] = []
    try:
        with os.scandir(_scan_path(root)) as it:
            entries = list(it)
    except OSError:
        return out
    folders = []
    for e in entries:
        try:
            if e.is_dir():                 # follows a symlinked project folder, as glob("*/...") did
                folders.append(Path(e.path))
        except OSError as err:             # one bad entry does not hide the others
            if skipped is not None:
                skipped.append((Path(e.path), "files gone" if isinstance(err, FileNotFoundError) else
                                f"files unreadable ({type(err).__name__})"))
    for d in folders:
        f = d / f"{session}.jsonl"
        if os.path.isfile(_scan_path(f)):
            out.append(Path(_scan_path(f)))       # opens past the Windows path limit too
        sub = d / session / "subagents"
        if os.path.isdir(_scan_path(sub)):
            out += walk(sub, "*.jsonl", skipped)
    return out


def codex_parent(meta: dict) -> str | None:
    """The thread that spawned this Codex session as a sub-agent (multi_agent), else None."""
    src = meta.get("source")
    if isinstance(src, dict):
        return ((src.get("subagent") or {}).get("thread_spawn") or {}).get("parent_thread_id")
    return None


def codex_children(parent: str, since: float, home: Path | None = None) -> dict[str, dict]:
    """Running usage totals of the sessions `parent` spawned with its own multi_agent tool:
    {child_id: {"input", "cached", "output"}}. Their tokens are not in the parent's reported usage."""
    root = (home or codex_home()) / "sessions"
    out = {}
    for f in _recent(walk(root, "rollout-*.jsonl"), since):
        try:
            with f.open(encoding="utf-8", errors="replace") as fh:
                first = json.loads(fh.readline() or "{}")
                if codex_parent(first.get("payload") or {}) != parent:
                    continue
                child, tot = (first.get("payload") or {}).get("id") or f.stem, None
                for line in fh:
                    if '"token_count"' not in line:
                        continue
                    info = ((json.loads(line).get("payload") or {}).get("info") or {})
                    tot = info.get("total_token_usage") or tot
        except (OSError, json.JSONDecodeError):
            continue
        if tot:
            out[child] = {"input": int(tot.get("input_tokens", 0) or 0),
                          "cached": int(tot.get("cached_input_tokens", 0) or 0),
                          "output": int(tot.get("output_tokens", 0) or 0)}
    return out


def codex_events(since: float, exclude: set[str], home: Path | None = None,
                 skipped: list | None = None) -> tuple[list[dict], list[dict]]:
    """-> (usage events, quota samples); folders that cannot be listed are noted in `skipped` (see walk)."""
    root = (home or codex_home()) / "sessions"
    if not root.exists():
        return [], []
    out, quota = [], []
    # Usage = growth of total_token_usage within each session file. Summing last_token_usage double counts:
    # Codex repeats token_count lines (e.g. rate-limit refreshes), and resumed/forked sessions copy earlier
    # history into the new file — those copied lines are older than the file's own session_meta and only set
    # the baseline.
    for f in _recent(walk(root, "rollout-*.jsonl", skipped), since, skipped):
        sid, model, start, prev, last_seen, parent = f.stem, "?", None, None, None, None
        try:
            lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            pl = e.get("payload") or {}
            typ = e.get("type")
            t = _ts(e.get("timestamp"))
            if typ == "session_meta":
                sid = pl.get("id") or sid
                start = _ts(pl.get("timestamp")) or t
                parent = codex_parent(pl)
            elif typ == "turn_context":
                model = pl.get("model") or model
            elif typ == "event_msg" and pl.get("type") == "token_count":
                info = pl.get("info") or {}
                tot = info.get("total_token_usage")
                rl = pl.get("rate_limits") or {}
                if t is not None and t >= since:
                    for win in ("primary", "secondary"):
                        w = rl.get(win) or {}
                        if w.get("used_percent") is not None:
                            quota.append({"ts": t, "agent": "codex", "window": win,
                                          "window_minutes": w.get("window_minutes"),
                                          "used_percent": w.get("used_percent"),
                                          "resets_at": w.get("resets_at")})
                keys = ("input_tokens", "cached_input_tokens", "output_tokens")
                if not tot:                       # older logs: per-request numbers only; skip exact repeats
                    last = info.get("last_token_usage") or {}
                    if not last:
                        continue
                    lt = tuple(int(last.get(k, 0) or 0) for k in keys)
                    tot = {k: (prev or {}).get(k, 0) + v for k, v in zip(keys, lt)} if lt != last_seen else prev
                    last_seen = lt
                    if tot is None:
                        continue
                cur = {k: int(tot.get(k, 0) or 0) for k in keys}
                base, prev = prev, cur
                copied = start is not None and t is not None and t < start
                if base is None and copied:
                    continue                      # inherited history: baseline only
                d = {k: cur[k] - (base or {}).get(k, 0) for k in cur}
                if any(v < 0 for v in d.values()) or not any(d.values()):
                    continue                      # repeat line, or counter reset: nothing new
                if t is None or t < since or sid in exclude or parent in exclude:
                    continue                      # a ccx sub-session's own children are counted with its run
                out.append({"ts": t, "agent": "codex", "role": "builtin" if parent else "lead", "session": sid,
                            **({"parent": parent} if parent else {}),
                            "model": model,
                            "usage": usage_dict(fresh=max(0, d["input_tokens"] - d["cached_input_tokens"]),
                                                cached=d["cached_input_tokens"], out=d["output_tokens"])})
    return out, quota


def codex_threads(hours: float = 48, limit: int = 15, home: Path | None = None) -> list[dict]:
    """Recent Codex conversations started by a person (desktop app, TUI), newest first, read from the session
    files. `codex agents` would list live ones, but it is an interactive browser (codex-cli 0.164)."""
    root = (home or codex_home()) / "sessions"
    rows = []
    for f in _recent(walk(root, "rollout-*.jsonl"), time.time() - hours * 3600):
        try:
            with f.open(encoding="utf-8", errors="replace") as fh:
                meta = (json.loads(fh.readline()) or {}).get("payload") or {}
        except (OSError, json.JSONDecodeError):
            continue
        if meta.get("originator") == "codex_exec":          # headless runs, e.g. ccx's own sub-agents
            continue
        rows.append({"thread": meta.get("id") or f.stem[-36:], "cwd": meta.get("cwd"),
                     "app": meta.get("originator"), "last_active": time.strftime(
                         "%Y-%m-%d %H:%M", time.localtime(f.stat().st_mtime)), "_m": f.stat().st_mtime})
    rows.sort(key=lambda r: r["_m"], reverse=True)
    return [{k: v for k, v in r.items() if k != "_m"} for r in rows[:limit]]


BUSY_AFTER_USER_S = 90


def thread_activity(thread: str, home: Path | None = None, now: float | None = None) -> dict:
    """Is a person working in this Codex conversation right now? Busy while a turn runs (task_started without
    task_complete after it) or for 90 s after the person's last message. Read from the session file's tail."""
    now = now or time.time()
    root = (home or codex_home()) / "sessions"
    files = sorted(walk(root, f"*{thread}*.jsonl"), key=lambda f: f.stat().st_mtime)
    if not files:
        return {"busy": False, "why": "no session file found"}
    f = files[-1]
    try:
        with f.open("rb") as fh:
            fh.seek(max(0, f.stat().st_size - 400_000))
            lines = fh.read().decode("utf-8", errors="replace").splitlines()
    except OSError:
        return {"busy": False, "why": "unreadable"}
    started = completed = user = None
    for line in lines:
        if '"event_msg"' not in line:
            continue
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        typ, t = (e.get("payload") or {}).get("type"), _ts(e.get("timestamp"))
        if t is None:
            continue
        if typ == "task_started":
            started = t
        elif typ == "task_complete":
            completed = t
        elif typ == "user_message":
            user = t
    if started and (not completed or completed < started):
        return {"busy": True, "why": "a turn is running"}
    if user and now - user < BUSY_AFTER_USER_S:
        return {"busy": True, "why": f"you wrote {int(now - user)} s ago"}
    return {"busy": False, "why": "idle"}


def lead_events(since: float, exclude: set[str], cfg: dict | None = None) -> tuple[list[dict], list[dict]]:
    from .ledger import billing_config, quota_units
    cfg = load_config() if cfg is None else cfg
    billing_config(cfg)
    ce = claude_events(since, exclude)
    xe, quota = codex_events(since, exclude)
    events = ce + xe
    for e in events:
        e["quota_units"] = quota_units(cfg, e["agent"], e["model"], e["usage"])
    return events, quota


def window_usage(agent: str, start: float, end: float | None, exclude: set[str], session: str | None = None) -> dict:
    """Sum of one agent's lead usage between two timestamps (used for A/B self-run samples); only that lead
    conversation when `session` is known."""
    end = end or time.time()
    evs = claude_events(start, exclude) if agent == "claude" else codex_events(start, exclude)[0]
    tot = usage_dict()
    from .ledger import billing_config, quota_units
    cfg = load_config()
    billing = billing_config(cfg)
    units = 0.0
    models: dict[str, int] = {}
    for e in evs:
        if start <= e["ts"] <= end and (not session or session in (e.get("session"), e.get("parent"))):
            for k, v in e["usage"].items():
                tot[k] += v
            models[e["model"]] = models.get(e["model"], 0) + 1
            units += quota_units(cfg, agent, e["model"], e["usage"])
    return {"usage": tot, "model": max(models, key=models.get) if models else None, "messages": sum(models.values()),
            "quota_units": round(units, 6), "billing": {"mode": billing["mode"]}}
