"""Claude Code (Anthropic). checked against Claude Code 2.1.309 --help (2026-10-22/23):
  claude -p --output-format stream-json --verbose --model M --effort E --json-schema S --resume <id>;
  the first event (system/init) has session_id, the final type=result event has usage, total_cost_usd,
  structured_output."""
from __future__ import annotations

import json
import os
from pathlib import Path

from ..config import RESULT_SCHEMA, claude_home
from ..runners import AUTH_HINTS, Invocation, Outcome, _json_from_text, bin_argv, classify, match_hint, usage_dict
from .base import Adapter

def claude_schema() -> dict:
    """The result schema with only status and summary required. Claude Code rejects a structured output that misses a
    required key and the model sends it again: in rounds 4-5, 10 of 181 Claude runs re-sent it 51 times in all, mostly
    for `open_questions` (haiku dropped it four times running). ccx reads the other keys with defaults; Codex keeps the
    strict schema, which its --output-schema needs."""
    s = json.loads(RESULT_SCHEMA.read_text(encoding="utf-8"))
    s["required"] = [k for k in s.get("required", []) if k in ("status", "summary")]
    return s


def _extra_settings() -> dict:
    """Opt-in settings every Claude sub-agent gets on top of ccx's own: CCX_CLAUDE_SETTINGS names a JSON file (or
    is a JSON object). An evaluation uses it to switch off hooks and auto-memory and to deny reads of the person's
    real homes; unset (the default) it adds nothing. A file that cannot be read is an error, not a silent no-op:
    the caller asked for isolation and must not get a run without it."""
    raw = os.environ.get("CCX_CLAUDE_SETTINGS", "").strip()
    if not raw:
        return {}
    text = raw if raw.startswith("{") else Path(raw).expanduser().read_text(encoding="utf-8")
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("CCX_CLAUDE_SETTINGS must hold a JSON object")
    return data


# [subagent] clean: no user settings layer (~/.claude/settings.json, its hooks, `language`, `env`)
CLEAN_SETTING_SOURCES = "project,local"


def claude_invocation(*, model: str, effort: str, perm: list[str], cwd: Path, prompt: str,
                      run_dir: Path, resume_id: str | None = None, lean: bool = False,
                      cache_ttl: str | None = None, clean: bool = False) -> Invocation:
    """cache_ttl: "5m" or "1h" sets Claude Code's `promptCacheTtl` for this run's main conversation (only ccx's
    one-shot reviewer, when `[review] cache_ttl` is set; None = Claude Code's own choice). Checked 2026-10-26 against
    code.claude.com/docs/en/prompt-caching ("Choose the TTL yourself": `promptCacheTtl` takes 5m or 1h, applies to
    -p runs, needs Claude Code v2.1.242+; local version 2.1.309)."""
    schema = json.dumps(claude_schema())
    # stream-json (+ --verbose, required with -p): the session id arrives in the first event, so a crash
    # mid-run still leaves a resumable session on record
    argv = [*bin_argv("claude"), "-p", "--output-format", "stream-json", "--verbose", "--model", model,
            "--effort", effort, "--json-schema", schema, *perm]
    if lean and "--strict-mcp-config" not in argv:
        argv += ["--strict-mcp-config"]
    # opt-in (an evaluation's clean room): no skills or slash commands and no MCP servers, whatever the effort
    no_skills = os.environ.get("CCX_CLAUDE_NO_SKILLS") == "1"
    # clean ([subagent] clean = true, experimental, off until measured): no skills or slash commands for a normal run
    # too; MCP stays as the run asked (--mcp / [claude_subagent] mcp, claude_slim_flags decides --strict-mcp-config)
    if (lean or no_skills or clean) and "--disable-slash-commands" not in argv:
        argv += ["--disable-slash-commands"]
    if no_skills and "--strict-mcp-config" not in argv:
        argv += ["--strict-mcp-config"]
    sources = CLEAN_SETTING_SOURCES if clean else os.environ.get("CCX_CLAUDE_SETTING_SOURCES", "").strip()
    if sources and "--setting-sources" not in argv:
        # opt-in (an evaluation's clean room): which settings layers load, e.g. "project,local" leaves out the
        # user's ~/.claude/settings.json and its hooks (claude 2.1.309 --help: --setting-sources user,project,local)
        argv += ["--setting-sources", sources]
    if "--settings" not in argv:
        # ultracode (standing dynamic workflows) is session-scoped, set by the desktop app or --settings; a
        # sub-run must not inherit it or opt in through the keyword in a brief (checked against 2.1.309)
        settings = {**_extra_settings(), "ultracode": False, "workflowKeywordTriggerEnabled": False}
        if cache_ttl in ("5m", "1h"):
            settings["promptCacheTtl"] = cache_ttl
        argv += ["--settings", json.dumps(settings)]
    if resume_id:
        argv += ["--resume", resume_id]
    return Invocation(argv, prompt, cwd, None)


def parse_claude(stdout: str, stderr: str, rc: int, _last: Path | None = None) -> Outcome:
    out = Outcome(ok=False)
    data = None
    s = stdout.strip()
    events = []
    for line in s.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    if not events and s:
        try:
            events = [json.loads(s)]
        except json.JSONDecodeError:
            pass
    for ev in events:
        if ev.get("session_id") and not out.session_id:
            out.session_id = ev["session_id"]
        if ev.get("type") == "rate_limit_event":
            info = ev.get("rate_limit_info") or ev
            if str(info.get("status", "")).lower() in ("rejected", "exceeded", "blocked"):
                out.kind = "quota"
            out.retry_after = info.get("resetsAt") or info.get("resets_at") or out.retry_after
    results = [e for e in events if e.get("type") == "result" or "structured_output" in e]
    data = results[-1] if results else (events[-1] if events else None)
    if isinstance(data, dict):
        out.session_id = data.get("session_id")
        u = data.get("usage") or {}
        cc = u.get("cache_creation") or {}
        fresh, write = u.get("input_tokens", 0) or 0, u.get("cache_creation_input_tokens", 0) or 0
        cached, outp = u.get("cache_read_input_tokens", 0) or 0, u.get("output_tokens", 0) or 0
        w1h = cc.get("ephemeral_1h_input_tokens", 0) or 0
        mu = data.get("modelUsage") or {}
        if mu:
            # `usage` is the last request of the main conversation only; `modelUsage` is the whole session, its
            # own sub-agents (Agent tool) included (checked 2026-10-24, Claude Code 2.1.309: usage 11.6k cache
            # writes, modelUsage 19.9k with one sub-agent; total_cost_usd matches modelUsage)
            tot = lambda k: sum(int((v or {}).get(k, 0) or 0) for v in mu.values())  # noqa: E731
            if tot("cacheCreationInputTokens") + tot("cacheReadInputTokens") + tot("inputTokens") \
                    >= fresh + write + cached:
                extra_w = max(0, tot("cacheCreationInputTokens") - write)
                fresh, cached, outp = tot("inputTokens"), tot("cacheReadInputTokens"), tot("outputTokens")
                w1h += extra_w if w1h == write else 0       # Claude Code writes the 1-hour cache throughout
                write += extra_w
        out.usage = usage_dict(fresh=fresh, write=write, write_1h=w1h, cached=cached, out=outp)
        out.cost_usd = data.get("total_cost_usd")
        if isinstance(data.get("permission_denials"), list):    # tool calls the allow-list refused in this run
            out.permission_denials = len(data["permission_denials"])
        out.result = data.get("structured_output") or _json_from_text(str(data.get("result", "")))
        out.raw_text = str(data.get("result", ""))
        if data.get("is_error"):
            # errors[] carries the real cause, e.g. "No conversation found with session ID: ..." on a resume
            # (hub run 20261024-213453-6292 showed only error_during_execution)
            errs = data.get("errors") or []
            errs = "; ".join(str(e) for e in (errs if isinstance(errs, list) else [errs]) if e)
            out.error = "; ".join(x for x in (out.raw_text or data.get("subtype"), errs) if x) or None
    joined = stderr + " " + (out.error or "")
    out.auth_problem = match_hint(joined, AUTH_HINTS) is not None and out.result is None
    out.ok = rc == 0 and out.result is not None and not (isinstance(data, dict) and data.get("is_error"))
    if not out.ok and not out.error:
        out.error = stderr.strip()[-800:] or f"exit code {rc}"
    if not out.ok and out.kind == "ok":
        out.kind = classify(joined)
    if out.ok:
        out.kind = "ok"
    return out


ADAPTER = Adapter(
    name="claude", vendor="anthropic", support="official", tested_version="2.1.309",
    build=claude_invocation, parse=parse_claude,
    login_argv=("auth", "status"), home=claude_home,
    session_files="<CLAUDE_CONFIG_DIR>/projects/<folder slug>/<session>.jsonl; its own sub-agents in "
                  "<session>/subagents/agent-*.jsonl",
    lead_events="ccx.usage:claude_events",
    context_file="CLAUDE.md", start_hook="settings.json hooks SessionStart (+ UserPromptSubmit for `ccx lead --hint`)",
    permissions="--permission-mode / --allowedTools (config [permissions.claude])",
    can_lead=True, can_work=True, can_resume=True, builtin_subagents=True, quota_readable=True,
    live_cost=True, turn_hook=True,          # its sub-agents' spend: <session>/subagents/*.jsonl, live (F12)
)
