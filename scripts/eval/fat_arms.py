"""Fat-context diagnostic arms (#546, trade-off map cell 4): the same long task done three ways by a lead whose
conversation is already about as fat as a real one. Opt-in; nothing here changes an existing arm.

  fatself    the lead does everything itself (no Agent tool, no ccx)
  fatnative  the lead hands the work to Claude Code's built-in sub-agent (Agent tool, r3.WORKER)
  fatccx     the lead hands it to Codex through ccx (the shipped default path, as ccxlong)

Before the first task of an episode the lead is fed a deterministic, task-independent filler turn so that its
context is about `--fat-tokens` (main tier 225k, heavy tier 360k; measured in #532, see docs/ROADMAP.md). The fill
turn is part of the same Claude session; its cost is recorded apart (`fill_usd`) and is not part of a task's `usd`.
Everything runs through p4_long_session.py (preflight, audit, accounting, between_units); this module holds the
arm definitions, the filler, the argv changes, the stream facts and the descriptive diagnostic summary.

No model is called by importing or testing this file. What is NOT verified here (Unknown until the #547 smoke test):
that `sonnet[1m]` is accepted by the installed Claude Code and plan, that the filler's real token count matches
`--fill-chars-per-token`, and that `result.usage` of a native-sub-agent turn includes the sub-agent's tokens (the
cost check fails closed if it does not: the row is cost-unknown, never wrong).
"""
from __future__ import annotations

import json
import random
import statistics

import preflight as PF

SELF, NATIVE, CCX = "fatself", "fatnative", "fatccx"
ARMS = (SELF, NATIVE, CCX)
BASE = {SELF: "self", CCX: "ccxlong"}           # the legacy prompt each arm reuses (NATIVE has its own)
TIERS = {"main": 225_000, "heavy": 360_000}
TIER_SOURCE = ("docs/ROADMAP.md (2026-11-25): real lead re-read median 225,389 (cache read); total input p75 358,902; "
               "#532")
LEAD_MODEL = "sonnet[1m]"                       # a 225k+ context does not fit the default 200k window
DEFAULT_CHARS_PER_TOKEN = 4.0
DEFAULT_TOLERANCE = 0.15                        # |measured - target| / target allowed for the fill
DEFAULT_FILL_BUDGET = 2.5                       # --max-budget-usd of the fill invocation, also reserved per episode
FILL_MARKER = "BACKGROUND-FILL"
FILLER_SEED = 546
LIMITATION = ("Synthetic task-independent filler stands in for accumulated tool output; whether it behaves like real "
              "context is Unknown. The fill cost is excluded from each task's usd and reported as fill_usd.")


def is_fat(arm) -> bool:
    return arm in ARMS


def any_fat(arms) -> bool:
    return any(is_fat(a) for a in arms)


def delegates(arm) -> bool:
    return arm in (NATIVE, CCX)


def base_arm(arm):
    """The legacy arm whose prompt text a fat arm reuses (identity for every other arm)."""
    return BASE.get(arm, arm)


# ------------------------------------------------------------------ the fill

_WORDS = ("alpha bravo cache channel cluster column config cursor daemon deploy digest driver engine entry fabric "
          "filter format gateway handle header index kernel ledger lookup manifest module offset packet parser "
          "plugin queue record reduce render resolve router sample schema scheduler segment server session "
          "signal socket stream string symbol thread token tracker update vector window worker").split()


def filler(tokens: int, chars_per_token: float = DEFAULT_CHARS_PER_TOKEN, seed: int = FILLER_SEED) -> str:
    """About `tokens` tokens of deterministic neutral text (numbered notes). Same arguments, same bytes. It names no
    repository, task, test or file of the evaluation, so nothing in it can leak or steer."""
    if tokens < 1 or chars_per_token <= 0:
        raise ValueError("tokens and chars_per_token must be positive")
    rng = random.Random(seed)
    target = int(tokens * chars_per_token)
    parts, size, n = [], 0, 0
    while size < target:
        n += 1
        line = f"note {n:06d}: " + " ".join(rng.choice(_WORDS) for _ in range(rng.randint(14, 26))) + ".\n"
        parts.append(line)
        size += len(line)
    return "".join(parts)[:target]


def fill_prompt(tokens: int, chars_per_token: float = DEFAULT_CHARS_PER_TOKEN) -> str:
    return (f"{FILL_MARKER}. Below are working notes from earlier in this session. They are unrelated to the next "
            "request. Do not use any tool and do not summarise them: read them and answer with exactly the word "
            "READY.\n\n" + filler(tokens, chars_per_token))


def fill_in_range(measured, target: int, tolerance: float = DEFAULT_TOLERANCE):
    """True/False once the fill's real context size is known; None (Unknown) when it was not measured."""
    if not isinstance(measured, (int, float)) or isinstance(measured, bool) or target <= 0:
        return None
    return abs(measured - target) <= tolerance * target


# ------------------------------------------------------------------ the arms' own prompt and argv

def native_prompt(task: dict, tail: str = "") -> str:
    """The legacy p4 wording for a delegating arm, with the Agent tool in place of ccx. Accepting the worker's own
    report mirrors ccxlong's one-line receipt: the lead does not re-read the diff or rerun tests unless it failed."""
    return ("The repository has been reset to a different historical parent for this task. "
            "Earlier code changes are intentionally absent; conversation context is preserved. "
            "Implement only the request below. Do not fetch history or packages, commit, or inspect other "
            "sessions, grading files, or evaluation artifacts. Run relevant existing tests, using "
            "python -m pytest -q -o addopts= with PYTHONPATH=. . Do not change existing tests.\n\n"
            + task["brief"] + "\n\n"
            "Do not edit code yourself. Delegate the request verbatim to your built-in sub-agent: call the Agent "
            "tool once with subagent_type `worker` and the request as its brief, and tell the worker to run "
            "`python -m pytest -q -o addopts=` when it is done and to report done, partial or blocked, that "
            "command's result line, and the files it changed. If the worker reports done with passing tests, accept "
            "that report and finish: do not read files or the diff, and do not rerun tests. Only if it reports "
            "partial or blocked or failing tests may you send it back once (another Agent call) saying what to fix. "
            "Do not use ccx, another model or CLI, or run anything in the background."
            + tail + "\nFinish with one line DONE: <summary>.")


def with_native_tools(argv: list[str], worker: dict | None = None) -> list[str]:
    """Add the Agent tool and the `worker` agent definition (r3.WORKER, as every earlier built-in arm) to a lead
    command line built by r3.lead_argv("ccx", ...), which has no Agent tool and keeps session persistence (resume)."""
    out = list(argv)
    for flag, sep in (("--tools", ","), ("--allowed-tools", " ")):
        i = out.index(flag)
        names = out[i + 1].split(sep)
        if "Agent" not in names:
            out[i + 1] = sep.join([*names, "Agent"])
    if "--agents" not in out:
        import r3
        out += ["--agents", json.dumps(worker or r3.WORKER)]
    return out


def lead_argv(argv: list[str], arm: str, model: str = LEAD_MODEL) -> list[str]:
    """A fat arm's lead command line from the shipped p4 one: the 1M-context model, plus the Agent tool for fatnative."""
    out = list(argv)
    if "--model" in out:
        out[out.index("--model") + 1] = model
    return with_native_tools(out) if arm == NATIVE else out


# ------------------------------------------------------------------ what a stream shows

def stream_facts(stream: str) -> dict:
    """What the lead itself called (built-in sub-agents' own messages are left out): Agent tool calls and Bash
    commands that went through p4_receipt.py (ccx), each call once; and the built-in sub-agent's own requests."""
    agent_calls = ccx_calls = 0
    seen, workers = set(), set()
    for ev in PF._events(stream):
        if ev.get("type") != "assistant":
            continue
        msg = ev.get("message") or {}
        if ev.get("parent_tool_use_id") is not None:
            workers.add(msg.get("id") or len(workers))
            continue
        for i, c in enumerate(msg.get("content") or []):
            if not isinstance(c, dict) or c.get("type") != "tool_use":
                continue
            key = c.get("id") or (msg.get("id"), i)
            if key in seen:
                continue
            seen.add(key)
            if c.get("name") in ("Agent", "Task"):
                agent_calls += 1
            elif c.get("name") == "Bash" and "p4_receipt.py" in str((c.get("input") or {}).get("command") or ""):
                ccx_calls += 1
    return {"agent_calls": agent_calls, "ccx_calls": ccx_calls, "worker_requests": len(workers)}


def conformance(arm: str, facts: dict, ccx_runs: int = 0):
    """Did the lead do what its arm says? True/False; an arm that was not followed is an invalid row, kept."""
    agent, ccx = facts["agent_calls"], max(facts["ccx_calls"], ccx_runs)
    if arm == SELF:
        return agent == 0 and ccx == 0
    if arm == NATIVE:
        return agent >= 1 and ccx == 0
    if arm == CCX:
        return ccx >= 1 and agent == 0
    return None


# ------------------------------------------------------------------ dry-run settings and the summary

def plan(a, arms) -> dict:
    """What a dry run prints for the fat arms: the actual setup of each, so the report copies it from here."""
    import r3
    tokens = fat_tokens(a)
    settings = {
        SELF: {"delegates_to": None, "tools": "Read,Grep,Glob,Edit,Write,Bash", "prompt": "p4 legacy self"},
        NATIVE: {"delegates_to": "Claude Code built-in sub-agent `worker` (Agent tool)",
                 "tools": "Read,Grep,Glob,Edit,Write,Bash,Agent", "agents": r3.WORKER,
                 "prompt": "fat_arms.native_prompt (p4 legacy wording, Agent tool for ccx)"},
        CCX: {"delegates_to": "codex through ccx (shipped defaults: --context auto, review, routing)",
              "tools": "Read,Grep,Glob,Edit,Write,Bash", "prompt": "p4 legacy ccxlong"}}
    return {
        "arms": {arm: {**settings[arm], "lead_model": getattr(a, "fat_lead_model", LEAD_MODEL), "lead_effort": "medium"}
                 for arm in arms if arm in settings},
        "fill": {"tier": getattr(a, "fat_tier", "main"), "target_tokens": tokens, "tiers": dict(TIERS),
                 "tier_source": TIER_SOURCE, "chars_per_token": getattr(a, "fill_chars_per_token", DEFAULT_CHARS_PER_TOKEN),
                 "chars_per_token_basis": "assumption, Unknown until a smoke run reads the measured fill context",
                 "tolerance": getattr(a, "fill_tolerance", DEFAULT_TOLERANCE),
                 "fill_budget_usd": getattr(a, "fill_budget", DEFAULT_FILL_BUDGET),
                 "per": "episode (once, before its first task); the group stops if a fill is out of range",
                 "content": f"deterministic filler, seed {FILLER_SEED}, task-independent",
                 "cost": "recorded as fill_usd, not part of a task's usd; charged to the run budget"},
        "limitation": LIMITATION,
        "unverified": ["sonnet[1m] availability", "real tokens per char of the filler",
                       "whether result.usage includes native sub-agent tokens (cost check fails closed)"]}


def fat_tokens(a) -> int:
    explicit = getattr(a, "fat_tokens", None)
    return int(explicit) if explicit else TIERS[getattr(a, "fat_tier", "main")]


def _money(x):
    return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) and x == x and x >= 0 else None


def comparison(rows: list[dict]) -> dict:
    """Descriptive only: no verdict rule is preregistered in this change (that is #547). Per fat arm: attempted /
    right, known spend (Claude side = the lead-vendor spend, total, fill apart), wall median, fill and conformance
    counts; plus the pairwise ratios of each arm to fatself where both are known."""
    fat = [r for r in rows if is_fat(r.get("arm"))]
    arms = {}
    for arm in ARMS:
        rs = [r for r in fat if r["arm"] == arm]
        if not rs:
            continue
        wall = [r["wall_s"] for r in rs if r.get("wall_s") is not None]
        fills = [r for r in rs if "fill_usd" in r]
        arms[arm] = {
            "attempted": len(rs), "right": sum(r.get("ok") is True for r in rs),
            "cost_unknown": sum(not r.get("cost_complete") for r in rs),
            "total_known_usd": round(sum(_money(r.get("usd")) or _money(r.get("known_usd")) or 0 for r in rs), 6),
            "claude_side_usd": round(sum(_money(r.get("claude_side_usd")) or 0 for r in rs), 6),
            "codex_side_usd": round(sum(_money(r.get("codex_side_usd")) or 0 for r in rs), 6),
            "wall_median_s": statistics.median(wall) if wall else None,
            "fill": {"episodes": len(fills), "usd_known": round(sum(_money(r.get("fill_usd")) or 0 for r in fills), 6),
                     "usd_unknown": sum(_money(r.get("fill_usd")) is None for r in fills),
                     "out_of_range": sum(r.get("fill_ok") is False for r in fills),
                     "measured_tokens": [r.get("fill_measured_tokens") for r in fills]},
            "arm_followed": sum(r.get("arm_conformance") is True for r in rs),
            "arm_not_followed": sum(r.get("arm_conformance") is False for r in rs),
            "context_first_median": statistics.median([r["context_first"] for r in rs
                                                       if r.get("context_first") is not None] or [0]) or None}

    def ratio(num, den):
        return round(num / den, 4) if num is not None and den else None

    base = arms.get(SELF)
    ratios = {arm: {"claude_side": ratio(v["claude_side_usd"], base["claude_side_usd"]),
                    "total": ratio(v["total_known_usd"], base["total_known_usd"]),
                    "wall_median": ratio(v["wall_median_s"], base["wall_median_s"])}
              for arm, v in arms.items() if base and arm != SELF}
    return {"arms": arms, "ratios_to_fatself": ratios,
            "verdict": "Unknown", "verdict_note": "diagnostic only; the decision rule is preregistered in #547",
            "limitation": LIMITATION}
