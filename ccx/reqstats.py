"""Per-request numbers of one sub-agent attempt (B3 "fewer runs"): how many requests it made and how big each
request's input was. Display and accounting only; nothing here changes what a sub-agent does.

Why: a run's total input is mostly the same prefix (system prompt, tool definitions, instructions, the conversation
so far) re-sent on every request: Codex ~18-25k and Claude ~13-15k a request, about 5 requests a run, and every
re-check or fix round adds 3-5 more. So "how much did a change save" is answered by two numbers, not the total:
requests per run, and the input of one request (its prefix). m1h2 (2026-10-30) showed why: the total's median moved
-36% while the paired total was +8%, because the baseline had more fix rounds.

Sources, both written by the tools themselves (checked 2026-10-30 on Claude Code 2.1.309 and codex-cli 0.164.0):
- Claude: the stream-json stdout ccx keeps as runs/<id>/events.N.log. Each request is one `assistant` message
  whose `message.usage` has input_tokens + cache_creation_input_tokens + cache_read_input_tokens; a message spans
  several lines (one per content block), so it is counted once by message.id. The stream marks an Agent-tool
  helper's message with a non-null `parent_tool_use_id` (a transcript file uses `isSidechain`): those are the
  sub-agent's own helpers, not this conversation's requests, and are left out, as Codex children are (they write
  their own rollout files). So `requests` counts the run's own conversation only, while its token totals include
  children: two columns, two scopes, said on the page.
- Codex: `exec --json` prints only the turn's total, so the session's rollout file is read: codex-cli 0.164 writes
  a `token_usage_record` per request (payload.usage.input_tokens, cached part inside), with a timestamp, so one
  attempt's records are those since it began (recover._codex_attempt reads the same lines after a kill).
A run that cannot be read (older record, no session id, file gone, gemini / dsh) records nothing: no guess.

Which number to compare (review of 2026-10-30): the per-request inputs grow through a run (each request carries the
one before), so their median moves with the number of rounds, the very confounder m1h2 hit. The ruler is therefore
`first_input` (the first request of a fresh session: system prompt + tools + instructions + the task, what a leaner
start has to lower), `requests`, and the mean input per request; the median is kept per attempt for the record.
"""
from __future__ import annotations

import json
import statistics
from pathlib import Path

KEEP = 200       # per-request inputs kept in run.json per attempt (a long session has fewer than this)


def activity_event(event: dict, tools: dict | None = None) -> list[dict]:
    """Read Codex exec JSON/rollout and Claude stream-json as display-only activity.

    No request/token accounting is changed. Missing event times and command exits stay unknown; tool output is
    untrusted text, never opened or executed. `tools` pairs Claude/rollout results with their calls across lines.
    """
    tools = tools if tools is not None else {}
    ts = event.get("timestamp") or event.get("ts")
    out = []

    def add(kind, text, **extra):
        out.append({"ts": ts, "kind": kind, "text": str(text or "")[:8000], **extra})

    def call(name, args, ident):
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except ValueError:
                args = {"input": args}
        args = args if isinstance(args, dict) else {}
        low = str(name).lower()
        kind = "command" if any(x in low for x in ("bash", "exec_command", "shell")) else (
            "read" if any(x in low for x in ("read", "glob", "grep", "search", "view")) else (
                "change" if any(x in low for x in ("edit", "write", "patch")) else "tool"))
        text = (args.get("command") or args.get("cmd") or args.get("file_path") or args.get("path")
                or args.get("input") or json.dumps(args, ensure_ascii=False))
        tools[ident] = {"kind": kind, "text": str(text), "tool": name}
        add(kind, text, tool=name, phase="started", call_id=ident, exit_code=None)

    def result(ident, body, error=False):
        import re
        prev = tools.get(ident, {"kind": "tool", "text": ident})
        code = body.get("exit_code") if isinstance(body, dict) else None
        text = json.dumps(body, ensure_ascii=False) if not isinstance(body, str) else body
        if code is None:
            match = re.search(r'(?:exit[_ ]code|Process exited with code)\s*[:=]?\s*(-?\d+)', text, re.I)
            code = int(match.group(1)) if match else None
        add(prev["kind"], prev["text"], tool=prev.get("tool"), phase="completed", call_id=ident,
            exit_code=code, error=bool(error), output=text[-8000:])

    typ = event.get("type")
    if typ in ("item.started", "item.updated", "item.completed"):
        item = event.get("item") or {}
        kind = item.get("type")
        if kind == "command_execution":
            add("command", item.get("command"), phase=typ.split(".")[-1], call_id=item.get("id"),
                exit_code=item.get("exit_code"), output=str(item.get("aggregated_output") or "")[-8000:])
        elif kind == "file_change":
            for change in item.get("changes") or []:
                add("change", change.get("path"), phase=typ.split(".")[-1], action=change.get("kind"))
        elif kind in ("agent_message", "reasoning"):
            add("message" if kind == "agent_message" else "reasoning", item.get("text"))
        elif kind == "mcp_tool_call":
            add("tool", item.get("tool"), phase=typ.split(".")[-1], output=str(item.get("result") or "")[-8000:])
    elif typ == "response_item":
        payload = event.get("payload") or {}
        if payload.get("type") in ("function_call", "custom_tool_call"):
            call(payload.get("name"), payload.get("arguments", payload.get("input")), payload.get("call_id"))
        elif payload.get("type") in ("function_call_output", "custom_tool_call_output"):
            result(payload.get("call_id"), payload.get("output"))
        elif payload.get("type") == "message" and payload.get("role") == "assistant":
            for block in payload.get("content") or []:
                if block.get("text"):
                    add("message", block["text"])
    elif typ in ("assistant", "user"):
        content = (event.get("message") or {}).get("content") or []
        if isinstance(content, str):
            if typ == "assistant":
                add("message", content)
        else:
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_use":
                    call(block.get("name"), block.get("input"), block.get("id"))
                elif block.get("type") == "tool_result":
                    result(block.get("tool_use_id"), block.get("content"), block.get("is_error"))
                elif typ == "assistant" and block.get("type") == "text":
                    add("message", block.get("text"))
    return out


def claude_inputs(lines) -> list[int]:
    """One entry per request of the main conversation, in order: the request's whole input (prefix)."""
    seen: set = set()
    out: list[int] = []
    for line in lines:
        if '"assistant"' not in line or '"usage"' not in line:
            continue
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("type") != "assistant" or e.get("isSidechain") or e.get("parent_tool_use_id"):
            continue
        m = e.get("message") or {}
        u = m.get("usage")
        if not u or m.get("model") == "<synthetic>":
            continue
        mid = m.get("id")
        if mid is not None and mid in seen:
            continue
        seen.add(mid)
        out.append(int(u.get("input_tokens", 0) or 0) + int(u.get("cache_creation_input_tokens", 0) or 0)
                   + int(u.get("cache_read_input_tokens", 0) or 0))
    return out


def codex_inputs(sid: str | None, since: float, home: Path | None = None) -> list[int]:
    """One entry per request the Codex session made since `since` (the attempt's start), from its rollout file."""
    if not sid:
        return []
    from .config import codex_home
    from .usage import _ts, walk
    root = (home or codex_home()) / "sessions"
    out: list[tuple[float, int]] = []
    for f in walk(root, f"rollout-*{sid}.jsonl"):
        try:
            lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            if '"token_usage_record"' not in line:
                continue
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if e.get("type") != "token_usage_record":
                continue
            t = _ts(e.get("timestamp"))
            u = (e.get("payload") or {}).get("usage") or {}
            if t is None or t < since or not u:
                continue
            out.append((t, int(u.get("input_tokens", 0) or 0)))
    return [n for _, n in sorted(out, key=lambda x: x[0])]


def attempt_inputs(cli: str, stdout: str, sid: str | None, since: float, home: Path | None = None) -> list[int]:
    """The per-request inputs of one attempt on `cli` (claude: its stream; codex: its rollout); [] when unknown."""
    if cli == "claude":
        return claude_inputs(stdout.splitlines())
    if cli == "codex":
        return codex_inputs(sid, since, home)
    return []


def fields(inputs: list[int], fresh_session: bool = True) -> dict:
    """What an attempt records: requests, prefix_tokens (median input of one), input_per_request (mean), the inputs
    themselves (capped), and first_input when the attempt started its session (a resumed session's first request
    already carries history, so it is no start-up measure)."""
    if not inputs:
        return {}
    out = {"requests": len(inputs), "prefix_tokens": int(statistics.median(inputs)),
           "input_per_request": int(sum(inputs) / len(inputs)), "request_inputs": inputs[:KEEP]}
    if fresh_session:
        out["first_input"] = int(inputs[0])
    return out


def run_fields(attempts: list[dict]) -> dict:
    """The ledger row's numbers: requests (all attempts), prefix_tokens (mean input per request over every request,
    weighted by each attempt's count), first_input (the first attempt that started a session). {} when no attempt
    recorded them; a malformed attempt is skipped, never an error (ledger.append must not fail a run)."""
    reqs, total, first = 0, 0, None
    for a in attempts:
        try:
            n = int(a.get("requests") or 0)
            if n <= 0:
                continue
            per = a.get("input_per_request")
            if per is None:
                ins = [int(x) for x in a.get("request_inputs") or []]
                per = sum(ins) / len(ins) if ins else a.get("prefix_tokens")
            reqs += n
            total += n * int(per or 0)
            if first is None and a.get("first_input") is not None:
                first = int(a["first_input"])
        except (TypeError, ValueError):
            continue
    if not reqs:
        return {}
    return {"requests": reqs, "prefix_tokens": int(total / reqs) if total else None, "first_input": first}
