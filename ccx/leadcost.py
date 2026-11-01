"""What the lead re-reads every turn, part by part (proposal J1), and the turns where its prompt cache broke
(J2). Both read only the tools' own session files; no model calls.

J1. Every turn re-sends the same prefix: system prompt, tool definitions (MCP servers' included), instruction
files, the skill list, what the start hook printed. A cache read costs about a tenth of input, but it is paid on
every turn, so a 10k-token MCP server nobody uses here is ~10k tokens × every turn. Claude Code (desktop and recent
CLI) logs the request shape and the start-up attachments; Codex logs its base instructions, tools and AGENTS.md.
Sizes are estimated from the text and scaled to the first turn's measured token count; what can't be attributed
is shown as the rest.

J2. Cache reads are cheap; a turn that has to write the whole conversation into the cache again is not. Such a
turn is found by its cache writes (Claude) or uncached input (Codex) jumping, and the likely cause is named: idle
longer than the cache lives, a model switch, an effort change (Codex), the conversation compacted, an instruction
file edited, the tool list changed — else unknown. For Claude it counts only when the turn read at least 20k fewer
tokens than the cache held after the last turn (its cache reads + writes) and under 90% of it: a turn that merely adds a big tool result writes a
lot but reads the old prefix back, and is no break."""
from __future__ import annotations

import json
import re
from pathlib import Path

CLAUDE_TTL_MIN = 5          # prompt-cache lifetime when the log doesn't say: 5 min is Claude Code's default
                            # except the main conversation on a subscription within plan usage (1 h); an API
                            # key, usage credits and subagents get 5 min (code.claude.com/docs/en/prompt-caching,
                            # 2026-10-26, Claude Code 2.1.309). A logged ttl of 1h below switches to 60.
CODEX_TTL_MIN = 10          # OpenAI keeps cached prefixes for roughly 5–10 minutes of inactivity
BREAK_MIN = 20_000          # a re-written prefix smaller than this is not worth reporting
BIG_PART = 2_000            # parts above this get advice


def est_tokens(text: str) -> float:
    """Rough tokens: ~4 ASCII characters per token, ~1 token per other character (CJK)."""
    a = sum(1 for c in text if ord(c) < 128)
    return a / 4 + (len(text) - a)


def _price_read(p, agent: str, model: str, tokens: float) -> float:
    from . import learn
    return learn.price_usd(p, agent, model or "", {"cached_input_tokens": int(tokens)}) or 0.0


def _lines(path: Path) -> list[dict]:
    out = []
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    except OSError:
        pass
    return out


def _mcp_server(tool_name: str) -> str | None:
    if not tool_name.startswith("mcp__"):
        return None
    return tool_name.split("__")[1] if tool_name.count("__") >= 2 else tool_name


def _mcp_namespace(name: str) -> str | None:
    """Codex groups an MCP server's tools under a namespace `mcp__<server>` (older logs: `mcp<...>`)."""
    if name.startswith("mcp__"):
        return name[5:].strip("_") or name
    return name if name.startswith("mcp") else None


# Codex sends its developer message as several blocks, each opened by a tag or a heading; named here so a big
# one (the skill list, the Memory folder) shows as its own part instead of one lump.
_DEV_BLOCKS = (("<skills_instructions", "skills"), ("## Skills", "skills"), ("## Memory", "Memory"),
               ("<oai-mem-citation", "Memory"), ("<permissions", "permissions"),
               ("<collaboration_mode", "collaboration mode"), ("<multi_agent", "multi-agent"),
               ("<recommended_plugins", "app context"), ("<apps_instructions", "app context"),
               ("<app-context", "app context"), ("<app_context", "app context"),
               ("<environment_context", "environment"))
_TAG = re.compile(r"<([A-Za-z][\w-]*)")


def _developer_block(text: str) -> str:
    head = text.lstrip()[:200]
    for prefix, label in _DEV_BLOCKS:
        if head.startswith(prefix):
            return label
    m = _TAG.match(head)
    return m.group(1).replace("_", " ") if m else "other"


def _mcp_calls(agent: str, evs: list[dict]) -> dict[str, int]:
    """How often each MCP server was called in this session (Claude tool_use names; Codex function calls by name
    or namespace, and its mcp_tool_call events)."""
    calls: dict[str, int] = {}

    def add(srv):
        if srv:
            calls[srv] = calls.get(srv, 0) + 1
    if agent == "claude":
        seen = set()
        for e in evs:
            if e.get("type") != "assistant":
                continue
            for c in (e.get("message") or {}).get("content") or []:
                if isinstance(c, dict) and c.get("type") == "tool_use" and c.get("id") not in seen:
                    seen.add(c.get("id"))
                    add(_mcp_server(str(c.get("name", ""))))
        return calls
    ended: dict[str, int] = {}          # the same call can be logged both ways: take the larger count per server
    for e in evs:
        pl = e.get("payload") or {}
        if e.get("type") == "response_item" and pl.get("type") in ("function_call", "custom_tool_call"):
            add(_mcp_server(str(pl.get("name", ""))) or _mcp_namespace(str(pl.get("namespace") or "")))
        elif e.get("type") == "event_msg" and pl.get("type") == "mcp_tool_call_end":
            srv = str(((pl.get("invocation") or {}).get("server")) or "")
            if srv:
                ended[srv] = ended.get(srv, 0) + 1
    return {s: max(calls.get(s, 0), ended.get(s, 0)) for s in set(calls) | set(ended)}


# ---------------------------------------------------------------- J1
def _claude_parts(evs: list[dict]) -> tuple[list[dict], int | None, str]:
    parts: dict[str, float] = {}
    measured, model, shape_seen = None, "", False
    for e in evs:
        t = e.get("type")
        if t == "api-request-shape" and not shape_seen:
            shape_seen = True
            sh = e.get("shape") or {}
            parts["system prompt"] = sum(est_tokens(x.get("text", "")) for x in sh.get("system") or [])
            for tool in sh.get("tools") or []:
                srv = _mcp_server(str(tool.get("name", "")))
                key = f"MCP server {srv} (tool definitions)" if srv else "built-in tool definitions"
                parts[key] = parts.get(key, 0) + est_tokens(json.dumps(tool, ensure_ascii=False))
        elif t == "attachment" and measured is None:
            a = e.get("attachment") or {}
            at = a.get("type")
            if at == "instructions":
                for f in a.get("files") or []:
                    parts[f"instruction file {f.get('path')}"] = est_tokens(f.get("content") or "")
            elif at == "skill_listing":
                parts["skill list"] = parts.get("skill list", 0) + est_tokens(a.get("content") or "")
            elif at == "mcp_instructions_delta":
                parts["MCP server instructions"] = parts.get("MCP server instructions", 0) + \
                    est_tokens("\n".join(a.get("addedBlocks") or []))
            elif at == "agent_listing_delta":
                parts["sub-agent type list"] = est_tokens("\n".join(a.get("addedLines") or []))
            elif at == "deferred_tools_delta":
                parts["deferred tool names"] = est_tokens(" ".join(a.get("addedNames") or []))
            elif at == "hook_additional_context":
                parts["start hook output"] = parts.get("start hook output", 0) + \
                    est_tokens("\n".join(map(str, a.get("content") or [])))
        elif t == "assistant" and measured is None and not e.get("isSidechain"):
            u = (e.get("message") or {}).get("usage") or {}
            if u:
                measured = int(u.get("input_tokens", 0) or 0) + int(u.get("cache_creation_input_tokens", 0) or 0) \
                    + int(u.get("cache_read_input_tokens", 0) or 0)
                model = (e.get("message") or {}).get("model") or ""
    if not shape_seen:
        parts["system prompt + tool definitions (not in this log)"] = 0.0
    return [{"part": k, "est": v} for k, v in parts.items()], measured, model


def _codex_parts(evs: list[dict]) -> tuple[list[dict], int | None, str]:
    parts: dict[str, float] = {}
    measured, model = None, ""
    for e in evs:
        pl = e.get("payload") or {}
        t = e.get("type")
        if t == "session_meta":
            parts["system prompt (base instructions)"] = est_tokens(str(pl.get("base_instructions") or ""))
        elif t == "turn_context" and not model:
            model = pl.get("model") or ""
        elif t == "response_item" and pl.get("type") == "additional_tools" and measured is None:
            for ns in pl.get("tools") or []:
                name = ns.get("name") or "functions"
                for tool in ns.get("tools") or [ns]:
                    srv = _mcp_server(str(tool.get("name", ""))) or _mcp_namespace(name)
                    key = f"MCP server {srv} (tool definitions)" if srv else "built-in tool definitions"
                    parts[key] = parts.get(key, 0) + est_tokens(json.dumps(tool, ensure_ascii=False))
        elif t == "response_item" and pl.get("type") == "message" and pl.get("role") == "developer" \
                and measured is None:
            for c in pl.get("content") or []:          # one block per content item, each named by its tag
                if isinstance(c, dict) and c.get("text"):
                    key = f"developer message: {_developer_block(c['text'])}"
                    parts[key] = parts.get(key, 0) + est_tokens(c["text"])
        elif t == "world_state" and measured is None:
            am = ((pl.get("state") or {}).get("agents_md")) or {}
            if am.get("text"):
                parts[f"instruction file AGENTS.md ({am.get('directory')})"] = est_tokens(am["text"])
        elif t == "event_msg" and pl.get("type") == "token_count" and measured is None:
            last = ((pl.get("info") or {}).get("last_token_usage")) or {}
            if last.get("input_tokens"):
                measured = int(last["input_tokens"])
    return [{"part": k, "est": v} for k, v in parts.items()], measured, model


def breakdown(p, agent: str, path: Path) -> dict:
    from . import ledger
    from .config import load_config
    cfg = load_config(p)
    mode = ledger.billing_config(cfg)["mode"]
    subscription = mode == "subscription"
    evs = _lines(path)
    parts, measured, model = (_claude_parts if agent == "claude" else _codex_parts)(evs)
    est = sum(x["est"] for x in parts)
    scale = measured / est if measured and est > measured else 1.0
    for x in parts:
        x["tokens"] = int(round(x["est"] * scale))
        del x["est"]
    if measured:
        rest = measured - sum(x["tokens"] for x in parts)
        if rest > 0:
            parts.append({"part": "the first message and everything else", "tokens": rest})
    parts.sort(key=lambda x: -x["tokens"])
    total = measured or sum(x["tokens"] for x in parts)
    calls = _mcp_calls(agent, evs)
    for x in parts:
        x["share"] = round(x["tokens"] / total, 3) if total else None
        usd = {"usd_per_100_turns": round(100 * _price_read(p, agent, model, x["tokens"]), 3)}
        units = ledger.quota_units(cfg, agent, model, {"cached_input_tokens": x["tokens"]})
        quota = {"quota_units": units, "quota_units_per_100_turns": round(100 * units, 6)}
        x.update({**quota, **usd} if subscription else {**usd, **quota})
        m = MCP_PART.match(x["part"])
        if m:
            x["calls"] = calls.get(m.group(1), 0)
    return {"agent": agent, "session_file": str(path), "model": model, "first_turn_tokens": measured,
            "estimated": True, "parts": parts, "advice": _advice(parts, subscription), "billing": {"mode": mode}}


MCP_PART = re.compile(r"MCP server (.+) \(tool definitions\)$")


def _advice(parts: list[dict], subscription: bool = False) -> list[str]:
    out = []
    for x in parts:
        if x["tokens"] < BIG_PART:
            continue
        cost = f"~{x['tokens']:,} tokens every turn (≈ ${x['usd_per_100_turns']:.2f} per 100 turns)"
        if subscription:
            cost = (f"~{x['tokens']:,} tokens every turn (≈ {x['quota_units_per_100_turns']:,} quota units "
                    f"per 100 turns; API-equivalent ${x['usd_per_100_turns']:.2f})")
        if x["part"] == "MCP server instructions":
            # The servers' own usage notes, not one server: only worth acting on when some server is unused.
            unused = [m.group(1) for y in parts if (m := MCP_PART.match(y["part"])) and y.get("calls") == 0]
            if unused:
                out.append(f"MCP server instructions: {cost}. Servers never called in this session: "
                           f"{', '.join(unused)}; turning those off here also drops their instructions.")
        elif MCP_PART.match(x["part"]):
            if x.get("calls"):          # called in this session: it is in use, turning it off is no advice
                continue
            never = " and was never called in this session" if "calls" in x else ""
            out.append(f"{x['part']}: {cost}{never}. If this project doesn't use it, turn that server off here.")
        elif x["part"] == "developer message: skills":
            out.append(f"Codex skill list (developer message): {cost}. Link only the skills you use "
                       f"(layout.skills_include).")
        elif x["part"].startswith("instruction file"):
            out.append(f"{x['part']}: {cost}. Keep it to what every turn needs; move the rest to files read "
                       f"on demand.")
        elif x["part"] == "skill list":
            out.append(f"skill list: {cost}. Link only the skills you use (layout.skills_include).")
        elif x["part"] == "start hook output":
            out.append(f"start hook output: {cost}. A shorter start-up note is cheaper on every turn.")
    return out


# ---------------------------------------------------------------- J5
LADDER = {"claude": ["opus", "sonnet", "haiku"], "codex": ["gpt-6-astra", "gpt-6.1-sol", "gpt-6-luna"]}
RECENT_TURNS = 30
SHELL_WRITES = re.compile(r"sed -i|write_text|open\([^)]*['\"][wa]['\"]|Set-Content|Out-File|tee|>>|[^-=2]> ?[\w./~$\"']|git (commit|apply|am)")
DOC_EXT = (".md", ".txt", ".rst", ".adoc", ".json", ".toml", ".yml", ".yaml", ".csv", ".html")


def _rung_of(agent: str, model: str) -> str | None:
    m = (model or "").lower()
    for r in LADDER.get(agent, []):
        if r in m or r.replace(".", "-") in m:
            return r
    return None


def _claude_turns(evs: list[dict]) -> list[dict]:
    """Per assistant reply: usage, model and what it did (edited code / edited docs / read or ran / only talked)."""
    from .runners import usage_dict
    out: list[dict] = []
    by_id: dict[str, dict] = {}
    for e in evs:
        if e.get("type") != "assistant" or e.get("isSidechain"):
            continue
        m = e.get("message") or {}
        if not m.get("usage") or m.get("model") == "<synthetic>":
            continue
        t = by_id.get(m.get("id"))
        if t is None:                         # one reply is logged as several lines, one per content block
            u = m["usage"]
            t = {"usage": usage_dict(fresh=u.get("input_tokens", 0) or 0,
                                     write=u.get("cache_creation_input_tokens", 0) or 0,
                                     cached=u.get("cache_read_input_tokens", 0) or 0,
                                     out=u.get("output_tokens", 0) or 0),
                 "model": m.get("model") or "", "work": "talk"}
            by_id[m.get("id")] = t
            out.append(t)
        for c in m.get("content") or []:
            if not isinstance(c, dict) or c.get("type") != "tool_use":
                continue
            name, inp = c.get("name", ""), c.get("input") or {}
            path = str(inp.get("file_path") or inp.get("notebook_path") or "")
            if name in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
                t["work"] = "docs" if path.lower().endswith(DOC_EXT) and t["work"] != "code" else "code"
            elif name in ("Bash", "PowerShell") and SHELL_WRITES.search(str(inp.get("command") or "")):
                t["work"] = "code"            # files changed through the shell count as editing (can't tell docs apart)
            elif t["work"] == "talk":
                t["work"] = "read"
    return out


def suggest(p, agent: str, path: Path, turns: int = RECENT_TURNS) -> dict:
    """A model for the lead itself (J5): what the recent turns did, what a turn costs on this model, what it
    would cost one rung down, and how many turns pay back the one cache rewrite a switch costs (J2)."""
    from .context import turn_tokens
    if agent != "claude":
        return {"agent": agent, "suggestion": None,
                "note": "only read from Claude Code logs so far (Codex logs don't say what each turn did)"}
    ts = _claude_turns(_lines(path))[-turns:]
    if not ts:
        return {"agent": agent, "suggestion": None, "note": "no turns in this session file"}
    model = ts[-1]["model"]
    cur = _rung_of(agent, model)
    mix: dict[str, int] = {}
    for t in ts:
        mix[t["work"]] = mix.get(t["work"], 0) + 1
    ctx = sorted(turn_tokens(t["usage"]) for t in ts)[len(ts) // 2]
    out_tok = sorted(int(t["usage"].get("output_tokens", 0) or 0) for t in ts)[len(ts) // 2]
    from . import learn
    per_turn = lambda m: learn.price_usd(p, agent, m, {"cached_input_tokens": ctx,  # noqa: E731
                                                       "output_tokens": out_tok}) or 0.0
    rows = []
    for r in LADDER[agent]:
        rows.append({"model": r, "usd_per_turn": round(per_turn(r), 4), "current": r == cur})
    code_share = mix.get("code", 0) / len(ts)
    res = {"agent": agent, "model": model, "recent_turns": len(ts), "work": mix, "context_tokens": ctx,
           "models": rows, "suggestion": None}
    ladder = LADDER[agent]
    if cur is None or cur == ladder[-1]:
        res["note"] = "already on the cheapest rung" if cur else f"unknown model {model!r}"
        return res
    down = ladder[ladder.index(cur) + 1]
    save = per_turn(cur) - per_turn(down)
    switch = (learn.price_usd(p, agent, down, {"cache_write_tokens": ctx}) or 0.0) \
        - (learn.price_usd(p, agent, down, {"cached_input_tokens": ctx}) or 0.0)
    payback = int(switch / save) + 1 if save > 0 else None
    res.update(saving_per_100_turns=round(100 * save, 2), switch_cost_usd=round(switch, 3), payback_turns=payback)
    if code_share <= 0.2:
        what = ", ".join(f"{k} {v}" for k, v in sorted(mix.items(), key=lambda x: -x[1]))
        res["suggestion"] = down
        res["why"] = (f"the last {len(ts)} turns were mostly not code ({what}); {down} costs "
                      f"${save * 100:.2f} less per 100 turns here, and the switch re-writes the cache once "
                      f"(${switch:.3f}, paid back after ~{payback} turns). Switch back for hard code or design.")
    else:
        res["why"] = (f"{code_share:.0%} of the last {len(ts)} turns edited code: stay on {cur}; for doc or "
                      f"mechanical stretches {down} would save ${save * 100:.2f} per 100 turns")
    return res


# ---------------------------------------------------------------- J2
def _claude_breaks(evs: list[dict]) -> tuple[list[dict], str]:
    breaks, prev, model, ttl = [], None, "", CLAUDE_TTL_MIN
    pending: list[str] = []
    shape = None
    seen, seen_tw = set(), set()
    for e in evs:
        t = e.get("type")
        if t == "api-request":
            for c in e.get("cacheControl") or []:
                v = (c.get("value") or {}).get("ttl")
                if v == "1h":
                    ttl = 60
            if shape and e.get("shapeHash") and e.get("shapeHash") != shape:
                pending.append("the tool list changed")
            shape = e.get("shapeHash") or shape
        elif t == "system" and (e.get("subtype") == "compact_boundary" or e.get("isCompactSummary")):
            pending.append("the conversation was compacted")
        elif t == "user" and e.get("isCompactSummary"):
            pending.append("the conversation was compacted")
        elif t == "attachment":
            a = e.get("attachment") or {}
            if a.get("type") == "edited_text_file" and str(a.get("filename") or a.get("path") or "").lower() \
                    .endswith(("claude.md", "agents.md")):
                pending.append("an instruction file was edited")
        elif t == "assistant" and not e.get("isSidechain"):
            m = e.get("message") or {}
            u = m.get("usage") or {}
            if not u or m.get("id") in seen or m.get("model") == "<synthetic>":   # an error the CLI wrote itself
                continue
            seen.add(m.get("id"))
            from .usage import _ts
            ts = _ts(e.get("timestamp"))
            w = int(u.get("cache_creation_input_tokens", 0) or 0)
            r = int(u.get("cache_read_input_tokens", 0) or 0)
            ctx = w + r       # what the cache held after this turn; uncached input was never in it, so not "lost"
            key = (e.get("timestamp"), w)
            if key[0] and key in seen_tw:     # the same reply logged again under another id (needs a timestamp)
                continue
            seen_tw.add(key)
            # A break is the cache losing what it held: this turn read clearly less than the cache held after the
            # last turn (its cache reads + writes). A turn that only adds a big tool result writes a lot too, but
            # reads the old prefix back.
            lost = prev[2] - r if prev else 0
            if prev and w >= BREAK_MIN and w > 0.3 * (w + r) and lost >= BREAK_MIN and r < 0.9 * prev[2]:
                why = []
                gap = (ts - prev[0]) / 60 if ts and prev[0] else 0
                if gap > ttl:
                    why.append(f"idle {gap:.0f} min (the cache lives {ttl} min)")
                if prev[1] and m.get("model") and m.get("model") != prev[1]:
                    why.append(f"model switched {prev[1]} → {m.get('model')}")
                why += [x for x in dict.fromkeys(pending) if x != "the tool list changed"] or \
                    [x for x in dict.fromkeys(pending)]
                breaks.append({"ts": e.get("timestamp"), "rewritten_tokens": w, "read_tokens": r,
                               "model": m.get("model"), "why": why or ["unknown"]})
            prev = (ts, m.get("model"), ctx)
            model = m.get("model") or model
            pending = []
    return breaks, model


def _codex_breaks(evs: list[dict]) -> tuple[list[dict], str]:
    breaks, prev_ts, model, prev_model, pending = [], None, "", "", []
    effort, prev_effort = "", ""
    from .usage import _ts
    for e in evs:
        pl = e.get("payload") or {}
        t = e.get("type")
        if t == "turn_context":
            model = pl.get("model") or model
            cm = pl.get("collaboration_mode") if isinstance(pl.get("collaboration_mode"), dict) else {}
            effort = str(pl.get("effort") or ((cm.get("settings") or {}).get("reasoning_effort")) or effort)
        elif t == "compacted":
            pending.append("the conversation was compacted")
        elif t == "event_msg" and pl.get("type") == "token_count":
            last = ((pl.get("info") or {}).get("last_token_usage")) or {}
            inp, cached = int(last.get("input_tokens", 0) or 0), int(last.get("cached_input_tokens", 0) or 0)
            if not inp:
                continue
            ts = _ts(e.get("timestamp"))
            fresh = inp - cached
            if prev_ts is not None and fresh >= BREAK_MIN and fresh > 0.5 * inp:
                why = []
                gap = (ts - prev_ts) / 60 if ts else 0
                if gap > CODEX_TTL_MIN:
                    why.append(f"idle {gap:.0f} min (cached prefixes last about {CODEX_TTL_MIN} min)")
                if prev_model and model != prev_model:
                    why.append(f"model switched {prev_model} → {model}")
                if prev_effort and effort != prev_effort:
                    why.append(f"effort changed {prev_effort} → {effort}")
                why += list(dict.fromkeys(pending))
                b = {"ts": e.get("timestamp"), "rewritten_tokens": fresh, "read_tokens": cached,
                     "model": model, "why": why or ["unknown"]}
                if why and all(w.startswith("effort changed") for w in why):
                    b["effort_only"] = True       # the same model at another effort: only the effort broke it
                breaks.append(b)
            prev_ts, prev_model, prev_effort, pending = ts, model, effort, []
    return breaks, model


def cause_key(why: str) -> str:
    """A break's cause without its numbers or from/to names, for counting causes."""
    if why.startswith("idle"):
        return "idle longer than the cache lives"
    key = why.split(" → ")[0]
    if key.startswith(("model switched", "effort changed")):
        key = " ".join(key.split()[:2])
    return key


def cache_breaks(p, agent: str, path: Path) -> dict:
    from . import learn
    evs = _lines(path)
    breaks, model = (_claude_breaks if agent == "claude" else _codex_breaks)(evs)
    extra = 0.0
    for b in breaks:
        m = b.get("model") or model
        if agent == "claude":
            full = learn.price_usd(p, agent, m, {"cache_write_tokens": b["rewritten_tokens"]}) or 0.0
        else:
            full = learn.price_usd(p, agent, m, {"input_tokens": b["rewritten_tokens"]}) or 0.0
        b["extra_usd"] = round(full - _price_read(p, agent, m, b["rewritten_tokens"]), 4)
        extra += b["extra_usd"]
    causes: dict[str, int] = {}
    for b in breaks:
        for w in b["why"]:
            key = cause_key(w)
            causes[key] = causes.get(key, 0) + 1
    return {"agent": agent, "session_file": str(path), "breaks": breaks, "extra_usd": round(extra, 4),
            "causes": causes,
            "note": ("a break re-writes the whole conversation into the cache; reads are ~0.1× input, writes "
                     "1.25–2× (Claude) or full input (Codex)")}
