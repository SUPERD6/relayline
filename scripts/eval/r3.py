"""Round 3 (docs/research/2026-10-25-r3-plan.md): the lead does it itself, or hands it to Claude Code's built-in
Agent sub-agent, or hands it to ccx — on harder, vaguer tasks (scripts/eval/tasks_r3.py) with hidden tests.

  arms (the lead is always a headless Claude Code, sonnet, the same brief; only the delegation route differs)
  self     the lead does the work itself
  builtin  the lead must hand the implementation to its built-in sub-agent (Agent tool, a `worker` on haiku)
  ccx      the lead must hand it to ccx: `ccx run --tradeoff save --review on --context auto` (a cheap model, a
           cheap reviewer from another vendor, the lead's recent work context attached)

Every unit gets a fresh repo and a fresh throwaway hub (CCX_HUB): Codex held to gpt-6-luna low, Claude held to haiku
(sonnet / opus / fable marked unavailable for routing), A/B self-runs off, the DeepSeek cap lifted (spend still
counted), the quota probe off. Every ccx run carries --no-ab and an eval-r3 label. The hidden test decides.

L8 measurement: for every sub-agent run (the built-in worker's messages in the lead's stream, the ccx builder's
events log) the share of its tokens that came from finding and reading files (`read_share`, see below).

  python scripts/eval/r3.py run --rounds 1 --tasks coupon --budget 8
  python scripts/eval/r3.py summary
  python scripts/eval/r3.py export docs/research/data/2026-10-25-r3.json

Results go to .ccx/eval/r3/results.jsonl, one row per unit; `run` again skips finished units. The budget counts
this file AND the L5 results (scripts/eval/l5_memory.py), so the two together stay under one cap.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import shlex
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import r2  # noqa: E402
import seven_ab as S  # noqa: E402
from common import ROOT, append_jsonl, archive_hub, boot_ci, lead_env, make_repo, parse_stream, read_jsonl, run_tree, score, sign_test  # noqa: E402
from tasks_r3 import HARD, by_id  # noqa: E402

from ccx import ledger  # noqa: E402
from ccx.config import Paths  # noqa: E402
from ccx.runners import bin_argv  # noqa: E402

OUT = ROOT / ".ccx" / "eval" / "r3"
L5_OUT = ROOT / ".ccx" / "eval" / "l5" / "results.jsonl"
ARMS = ("self", "builtin", "ccx")
TASKS = [t["id"] for t in HARD]
LEAD_MODEL, LEAD_EFFORT = "sonnet", "medium"
WORKER_MODEL = "haiku"
CLAUDE_HELD_BACK = ("sonnet", "opus", "fable")
CCX_CMD = f'python "{ROOT.as_posix()}/ccx.py"'
CCX_RUN = "run --tradeoff save --review on --context auto --mode write --new --no-ab --check \"python -m pytest -q\""
WORKER = {"worker": {"description": "Implements a code change in this repository and reports what it changed.",
                     "prompt": "You implement the change you are given in this repository, run the tests with "
                               "`python -m pytest -q`, and report back which files you changed and whether the "
                               "tests pass.",
                     "model": WORKER_MODEL, "tools": ["Read", "Grep", "Glob", "Edit", "Write", "Bash"]}}

LEAD_PROMPT = """You are the lead agent on this repository (a small Python package; tests run with `python -m pytest -q`).
The person asked:

{brief}

{how}

When the work is done and the tests pass, end with one line: DONE: <what changed>."""
HOW = {
    "self": "Do the work yourself.",
    "builtin": "Do not edit files yourself: hand the implementation to your sub-agent. Call the Agent tool with "
               "subagent_type `worker` and a brief that contains everything it needs. When it reports back, check "
               "the result (read the diff, run the tests); if something is wrong or missing, send it back to the "
               "worker (another Agent call) saying what to fix.",
    "ccx": "Do not edit files yourself: hand the implementation to a sub-agent through ccx. Run\n"
           "  {ccx} {run} --label {label} \"<a brief that contains everything it needs>\"\n"
           "It prints one JSON object (run_id, ok, summary, check, review, ...). When it reports back, check the "
           "result (read the diff, run the tests); if something is wrong or missing, send it back with\n"
           "  {ccx} resume <run_id> \"<what to fix>\"",
}

# ------------------------------------------------------------------ L8: how much of a run went to finding files

READ_TOOLS = {"Read", "Grep", "Glob", "LS", "NotebookRead"}
READ_CMDS = {"cat", "head", "tail", "ls", "find", "grep", "rg", "wc", "tree", "type", "more", "less", "dir", "file",
             "get-content", "gc", "get-childitem", "gci", "select-string", "sls", "nl", "stat", "realpath", "pwd"}
GIT_READ = {"ls-files", "grep", "show", "log", "diff", "status", "blame"}


def _split_outside_quotes(s: str) -> list[str]:
    """Split a command line at ; | && || that are not inside quotes."""
    out, cur, q, i = [], [], None, 0
    while i < len(s):
        ch = s[i]
        if q:
            q = None if ch == q else q
        elif ch in "\"'":
            q = ch
        elif ch in ";|&":
            out.append("".join(cur))
            cur = []
            i += 2 if s[i:i + 2] in ("&&", "||") else 1
            continue
        cur.append(ch)
        i += 1
    out.append("".join(cur))
    return out


def is_read_cmd(cmd) -> bool:
    """Is this shell command only finding or reading files? (each part of a pipeline / && chain must be)"""
    if isinstance(cmd, list):
        cmd = cmd[-1] if cmd else ""
    # Codex hands its commands to a shell: '"...\\powershell.exe" -Command "..."', 'bash -lc "..."'
    m = re.match(r"""^\s*"?[^"\s]*?(?:powershell|pwsh|bash|sh|cmd)(?:\.exe)?"?\s+(?:-NoProfile\s+)?"""
                 r"""(?:-Command|-lc|-c|/c)\s+(["']?)(.*)\1\s*$""", str(cmd), re.S | re.I)
    if m:
        cmd = m.group(2)
    parts = [p.strip() for p in _split_outside_quotes(str(cmd)) if p.strip()]
    if not parts:
        return False
    for p in parts:
        try:
            w = shlex.split(p, posix=True)
        except ValueError:
            w = p.split()
        w = [x for x in w if not re.match(r"^[A-Za-z_]+=", x)] or [""]
        prog = Path(w[0]).name.lower().removesuffix(".exe")
        if prog in ("cd", "echo", "true"):
            continue
        if prog == "sed":
            if any(x.startswith("-i") for x in w[1:]):
                return False
            continue
        if prog == "awk":
            continue
        if prog == "git":
            sub = next((x for x in w[1:] if not x.startswith("-")), "")
            if sub in GIT_READ:
                continue
            return False
        if prog not in READ_CMDS:
            return False
    return True


def _toks(text) -> int:
    if isinstance(text, list):
        text = "".join(str(c.get("text", "")) if isinstance(c, dict) else str(c) for c in text)
    return len(str(text or "")) // 4


def read_share_claude(stdout: str, sub: bool | None) -> dict:
    """Claude stream-json (and DeepSeek through Claude Code): sub=None the main conversation only, sub=True only the
    built-in sub-agents' messages (parent_tool_use_id set). Every request re-reads its whole context, so a file read
    early is paid for again in every later request: share = sum over requests of (read-result tokens already in the
    context, capped at that request's context) / sum of (context + output) tokens. Tool-result sizes are estimated
    as characters / 4; request contexts come from each request's own usage."""
    kinds: dict[str, str] = {}
    seen: set[str] = set()
    cum = {"read": 0, "other": 0}
    acc_read = acc_other = acc_total = 0
    calls = {"read": 0, "other": 0}
    requests = 0
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        mine = (ev.get("parent_tool_use_id") is not None) if sub else ev.get("parent_tool_use_id") is None
        if not mine or ev.get("type") not in ("assistant", "user"):
            continue
        m = ev.get("message") or {}
        if ev["type"] == "assistant":
            mid = m.get("id")
            if mid and mid not in seen:
                seen.add(mid)
                u = m.get("usage") or {}
                ctx = sum(int(u.get(k, 0) or 0) for k in ("input_tokens", "cache_read_input_tokens",
                                                          "cache_creation_input_tokens"))
                requests += 1
                acc_read += min(cum["read"], ctx)
                acc_other += min(cum["other"], max(0, ctx - cum["read"]))
                acc_total += ctx + int(u.get("output_tokens", 0) or 0)
            for c in m.get("content") or []:
                if isinstance(c, dict) and c.get("type") == "tool_use":
                    name = c.get("name")
                    read = name in READ_TOOLS or (name == "Bash" and is_read_cmd((c.get("input") or {}).get("command")))
                    kinds[c.get("id")] = "read" if read else "other"
                    calls["read" if read else "other"] += 1
        else:
            for c in m.get("content") or [] if isinstance(m.get("content"), list) else []:
                if isinstance(c, dict) and c.get("type") == "tool_result":
                    cum[kinds.get(c.get("tool_use_id"), "other")] += _toks(c.get("content"))
    return {"requests": requests, "tokens": acc_total, "read_tokens": acc_read, "other_tool_tokens": acc_other,
            "read_share": round(acc_read / acc_total, 4) if acc_total else None,
            "read_calls": calls["read"], "other_calls": calls["other"]}


def read_share_codex(stdout: str) -> dict:
    """Codex `exec --json`: no per-request usage, only the turn's total. Each tool output is assumed to be re-read
    by every later model call (about one call per tool item, plus the last answer): share = sum of output tokens x
    later calls / the turn's input tokens (cached included), capped at 1. An approximation; reported as such."""
    items, total_in, total_out = [], 0, 0
    for line in stdout.splitlines():
        try:
            ev = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if ev.get("type") == "item.completed":
            it = ev.get("item") or {}
            if it.get("type") == "command_execution":
                items.append(("read" if is_read_cmd(it.get("command")) else "other", _toks(it.get("aggregated_output"))))
            elif it.get("type") in ("file_change", "mcp_tool_call", "web_search"):
                items.append(("other", 0))
        elif ev.get("type") == "turn.completed":
            u = ev.get("usage") or {}
            total_in += int(u.get("input_tokens", 0) or 0)
            total_out += int(u.get("output_tokens", 0) or 0)
    n = len(items) + 1
    read = sum(t * (n - 1 - i) for i, (k, t) in enumerate(items) if k == "read")
    other = sum(t * (n - 1 - i) for i, (k, t) in enumerate(items) if k == "other")
    tot = total_in + total_out
    return {"requests": n, "tokens": tot, "read_tokens": min(read, total_in), "other_tool_tokens": other,
            "read_share": round(min(1.0, read / tot), 4) if tot else None,
            "read_calls": sum(k == "read" for k, _ in items), "other_calls": sum(k == "other" for k, _ in items),
            "approx": True}


def ccx_builder_share(hub: Path) -> list[dict]:
    """read_share of every builder run in this hub (reviews left out: they read a diff they are given)."""
    out = []
    for r in ledger.rows(Paths(hub)):
        if r.get("type") or str(r.get("label") or "").startswith("review:"):
            continue
        d = hub / "ccx" / "runs" / str(r.get("run_id"))
        logs = sorted(d.glob("events.*.log"))
        if not logs:
            continue
        text = "\n".join(f.read_text(encoding="utf-8", errors="replace") for f in logs)
        fmt = "codex" if '"thread.started"' in text or '"turn.completed"' in text else "claude"
        res = read_share_codex(text) if fmt == "codex" else read_share_claude(text, None)
        out.append({"run_id": r.get("run_id"), "agent": r.get("provider") or r.get("to"), "model": r.get("model"),
                    "fmt": fmt, **res})
    return out


# ------------------------------------------------------------------ the lead

def make_hub(d: Path) -> dict:
    info = r2.make_hub(d)
    code = ("from ccx import learn\nfrom ccx.config import paths\n"
            f"for m in {CLAUDE_HELD_BACK!r}:\n    learn.mark_unavailable(paths(), 'claude', m)\n")
    r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=r2.env_for(d), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode:
        raise RuntimeError(f"holding back Claude models failed: {r.stderr[-300:]}")
    return info


def lead_argv(arm: str, budget: float, model: str | None = None, effort: str | None = None,
              agents: dict | None = None) -> list[str]:
    """The lead's command line. `model` / `effort` default to LEAD_MODEL / LEAD_EFFORT (round 5's --lead-model /
    --lead-effort); `agents` replaces the builtin arm's WORKER definition (round 5's builtin2r)."""
    tools = "Read,Grep,Glob,Edit,Write,Bash" + (",Agent" if arm == "builtin" else "")
    argv = [*bin_argv("claude"), "-p", "--output-format", "stream-json", "--verbose", "--model", model or LEAD_MODEL,
            "--effort", effort or LEAD_EFFORT, "--tools", tools, "--permission-mode", "acceptEdits",
            "--allowed-tools", tools.replace(",", " "), "--strict-mcp-config",
            "--exclude-dynamic-system-prompt-sections", "--disable-slash-commands", "--max-budget-usd", str(budget)]
    if arm == "builtin":
        argv += ["--agents", json.dumps(agents or WORKER)]
    if arm != "ccx":              # ccx --context reads the lead's session file, so only that lead keeps one
        argv.append("--no-session-persistence")
    return argv


def lead_prompt(task: dict, arm: str, label: str) -> str:
    how = HOW[arm].format(ccx=CCX_CMD, run=CCX_RUN, label=label)
    return LEAD_PROMPT.format(brief=task["brief"], how=how)


def model_split(final_usage: dict) -> dict:
    """modelUsage of the result event: what each model cost (the lead is sonnet, the built-in worker haiku)."""
    return {m: round(float(v.get("costUSD") or 0), 6) for m, v in (final_usage or {}).items()}


def last_result(stdout: str) -> dict:
    res = {}
    for line in stdout.splitlines():
        if line.startswith("{") and '"type":"result"' in line.replace(" ", ""):
            try:
                res = json.loads(line)
            except json.JSONDecodeError:
                pass
    return res


def lead_metrics(stdout: str) -> dict:
    """The lead's own requests and tokens (built-in sub-agent messages left out), its tool calls and Bash
    commands, how many times it delegated."""
    msgs, tools, bash, agent_calls = {}, {}, [], 0
    for line in stdout.splitlines():
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("type") != "assistant" or ev.get("parent_tool_use_id") is not None:
            continue
        m = ev.get("message") or {}
        if m.get("id"):
            msgs[m["id"]] = m.get("usage") or {}
        for c in m.get("content") or []:
            if isinstance(c, dict) and c.get("type") == "tool_use":
                tools[c["name"]] = tools.get(c["name"], 0) + 1
                if c["name"] == "Bash":
                    bash.append(str((c.get("input") or {}).get("command", "")))
                if c["name"] in ("Agent", "Task"):
                    agent_calls += 1
    ctx = [sum(int(u.get(k, 0) or 0) for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
           for u in msgs.values()]
    out = sum(int(u.get("output_tokens", 0) or 0) for u in msgs.values())
    # counted on the whole command: a lead that builds a long brief first (BRIEF=$(cat <<EOF ...)) puts `ccx.py run`
    # past the 400 characters kept below (round 4 missed one delegation that way)
    ccx_runs = sum(len(re.findall(r"ccx\.py\"?\s+run\b", b)) for b in bash)
    ccx_resumes = sum(len(re.findall(r"ccx\.py\"?\s+resume\b", b)) for b in bash)
    bash = [b[:400] for b in bash]
    return {"lead_requests": len(msgs), "lead_context_tokens": sum(ctx), "lead_output_tokens": out,
            "lead_tokens": sum(ctx) + out, "lead_tools": tools, "lead_edits": tools.get("Edit", 0) + tools.get("Write", 0),
            "agent_calls": agent_calls, "ccx_runs": ccx_runs, "ccx_resumes": ccx_resumes, "bash": bash}


def run_unit(u: dict, a, work: Path) -> dict:
    task = by_id(u["task"])
    key = f"{u['round']}-{u['task']}-{u['arm']}"
    repo, hub = work / key, work / f"hub-{key}"
    for d in (repo, hub):
        r2._rmtree(d)
    make_repo(task, repo)
    hinfo = make_hub(hub)
    env = {**lead_env(), "CCX_HUB": str(hub), "CCX_NO_QUOTA_PROBE": "1", "BASH_DEFAULT_TIMEOUT_MS": "600000",
           "BASH_MAX_TIMEOUT_MS": "900000"}
    prompt = lead_prompt(task, u["arm"], u["label"])
    t0 = time.time()
    try:
        r = run_tree(lead_argv(u["arm"], a.lead_budget), input=prompt, cwd=repo, env=env, timeout=a.timeout)
        out, rc = r.stdout, r.returncode
    except subprocess.TimeoutExpired as e:
        out = e.stdout.decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        rc = -9
    wall = round(time.time() - t0, 1)
    (work / f"{key}.stream.jsonl").write_text(out, encoding="utf-8")
    sc = score(repo, task)
    base = parse_stream(out)
    fin = last_result(out)
    lm = lead_metrics(out)
    cost = r2.hub_cost(hub)
    by_model = model_split(fin.get("modelUsage") or {})
    lead_usd = float(fin.get("total_cost_usd") or 0)
    row = {**u, "ok": sc["ok"], "pytest": sc["pytest"], "rc": rc, "wall_s": wall, "subtype": base.get("subtype"),
           "is_error": base.get("is_error"), "answer": base.get("answer"), "lead_usd": round(lead_usd, 6),
           "by_model_usd": by_model, "ccx_usd": cost["usd"], "ccx_tokens": cost["tokens"],
           "ccx_review_usd": cost["review_usd"], "ccx_agents": cost["agents"], "ccx_rungs": cost["rungs"],
           "ccx_run_ids": cost["run_ids"], "usd": round(lead_usd + cost["usd"], 6), "hub": hinfo, **lm}
    # the lead's claude -p total includes its built-in sub-agents; split them out by model
    row["sub_usd"] = round(sum(v for m, v in by_model.items() if WORKER_MODEL in m), 6) if u["arm"] == "builtin" \
        else cost["usd"]
    row["lead_only_usd"] = round(row["usd"] - row["sub_usd"], 6)
    if u["arm"] == "builtin":
        row["l8"] = [{"agent": "claude", "model": WORKER_MODEL, **read_share_claude(out, True)}] if lm["agent_calls"] else []
    elif u["arm"] == "ccx":
        row["l8"] = ccx_builder_share(hub)
        recs = [r2.record(hub, rid) for rid in cost["run_ids"]]
        row["ccx_fix_rounds"] = sum(bool(x.get("review_of")) for x in recs)        # ccx's own review -> fix round
        row["ccx_review_verdicts"] = [v.get("verdict") for x in recs
                                      for v in (x.get("first_review"), x.get("review")) if v]
        row["context_attached"] = sum((hub / "ccx" / "runs" / str(rid) / "shared-context.md").exists()
                                      for rid in cost["run_ids"])
        row["archived_sessions"] = archive_hub(hub)
    row["l8_lead"] = read_share_claude(out, None)
    row["rework"] = max(0, lm["agent_calls"] - 1) if u["arm"] == "builtin" else \
        (lm["ccx_resumes"] + max(0, lm["ccx_runs"] - 1)) if u["arm"] == "ccx" else 0
    row["delegated"] = bool(lm["agent_calls"]) if u["arm"] == "builtin" else bool(lm["ccx_runs"]) if u["arm"] == "ccx" \
        else None
    for rid in cost["run_ids"]:
        r2.verify(hub, rid, bool(sc["ok"]), sc["pytest"])
    return row


# ------------------------------------------------------------------ schedule and run

def schedule(rounds: int, seed: int, tasks: list[str] | None = None) -> list[dict]:
    out = []
    for rd in range(1, rounds + 1):
        rnd = random.Random(f"{seed}:r3:{rd}")
        ts = list(tasks or TASKS)
        rnd.shuffle(ts)
        for t in ts:
            arms = list(ARMS)
            rnd.shuffle(arms)
            out += [{"exp": "r3", "round": rd, "task": t, "arm": arm} for arm in arms]
    return out


def unit_key(u: dict) -> str:
    return f"{u['tag']}:{u['round']}:{u['task']}:{u['arm']}"


def spent(rows: list[dict]) -> float:
    return round(sum(r.get("usd") or 0 for r in rows), 4)


def total_spent(out: Path) -> float:
    return round(spent(read_jsonl(out)) + spent(read_jsonl(L5_OUT)), 4)


def cmd_run(a) -> int:
    out = Path(a.out) if a.out else OUT / "results.jsonl"
    work = Path(a.workdir or tempfile.mkdtemp(prefix="ccx-r3-"))
    done = {unit_key(r) for r in read_jsonl(out)}
    print(f"work dir: {work}  results: {out}", flush=True)
    for u in schedule(a.rounds, a.seed, a.tasks.split(",") if a.tasks else None):
        u = {**u, "tag": a.tag, "seed": a.seed}
        u["label"] = f"eval-r3:{a.tag}:{u['round']}:{u['task']}:{u['arm']}"
        if unit_key(u) in done or (a.arms and u["arm"] not in a.arms.split(",")):
            continue
        total = total_spent(out)
        if total >= a.budget:
            print(f"budget ${a.budget} reached (${total:.3f}): stopping", flush=True)
            return 2
        if a.dry_run:
            print(f"[dry] {u['label']}")
            continue
        try:
            row = run_unit(u, a, work)
        except Exception as e:  # noqa: BLE001 — one broken unit is recorded, the batch goes on
            row = {**u, "ok": False, "error": f"{type(e).__name__}: {e}"[:400], "usd": 0.0, "wall_s": 0}
        row["ts"] = time.time()
        append_jsonl(out, row)
        l8 = [x.get("read_share") for x in row.get("l8") or []]
        print(f"r{u['round']} {u['task']:12} {u['arm']:8} ok={row.get('ok')} ${row.get('usd', 0):.4f} "
              f"(sub ${row.get('sub_usd', 0):.4f}) lead_tok={row.get('lead_tokens')} {row.get('wall_s')}s "
              f"deleg={row.get('delegated')} rework={row.get('rework')} l8={l8} total=${total_spent(out)}",
              flush=True)
    return 0


# ------------------------------------------------------------------ statistics

def holm(ps: dict[str, float | None]) -> dict[str, tuple[float | None, float | None]]:
    return S.holm(ps)


def cps(rows: list[dict]) -> float | None:
    k = sum(bool(r.get("ok")) for r in rows)
    return round(sum(r.get("usd") or 0 for r in rows) / k, 5) if k else None


def cps_ci(rows: list[dict], n: int = 4000, seed: int = 7) -> tuple[float, float] | None:
    """Bootstrap over tasks (the independent unit): resample tasks, pool their units, spend / successes."""
    by: dict[str, list[dict]] = {}
    for r in rows:
        by.setdefault(r["task"], []).append(r)
    ts = sorted(by)
    if len(ts) < 2:
        return None
    rnd = random.Random(seed)
    vals = []
    for _ in range(n):
        pick = [x for t in (rnd.choice(ts) for _ in ts) for x in by[t]]
        c = cps(pick)
        if c is not None:
            vals.append(c)
    vals.sort()
    return (vals[int(0.025 * len(vals))], vals[int(0.975 * len(vals)) - 1]) if vals else None


def paired(rows: list[dict], A: str, B: str) -> list[tuple[dict, dict]]:
    by: dict = {}
    for r in rows:
        if "error" not in r:
            by.setdefault((r["tag"], r["round"], r["task"]), {})[r["arm"]] = r
    return [(d[A], d[B]) for _, d in sorted(by.items()) if A in d and B in d]


def task_level(ps: list[tuple[dict, dict]], f) -> list[float]:
    """Per-task mean of the paired differences B - A (the rounds of one task are not independent)."""
    by: dict[str, list[float]] = {}
    for a, b in ps:
        by.setdefault(a["task"], []).append(f(b) - f(a))
    return [statistics.fmean(v) for v in by.values()]


METRICS = {"usd": lambda r: r.get("usd") or 0, "wall_s": lambda r: r.get("wall_s") or 0,
           "lead_tokens": lambda r: r.get("lead_tokens") or 0, "lead_only_usd": lambda r: r.get("lead_only_usd") or 0,
           "rework": lambda r: r.get("rework") or 0}


def compare(ps: list[tuple[dict, dict]], A: str, B: str) -> dict:
    b = sum(bool(x["ok"]) and not y["ok"] for x, y in ps)
    c = sum(bool(y["ok"]) and not x["ok"] for x, y in ps)
    ok_diff = task_level(ps, lambda r: float(bool(r["ok"])))
    res = {"arms": [A, B], "pairs": len(ps), "tasks": len({x["task"] for x, _ in ps}),
           "ok": {A: sum(bool(x["ok"]) for x, _ in ps), B: sum(bool(y["ok"]) for _, y in ps)},
           "discordant": {f"only_{A}": b, f"only_{B}": c}, "mcnemar_p": S.mcnemar_p(b, c),
           "ok_task_sign_p": sign_test(ok_diff), "metrics": {}}
    for k, f in METRICS.items():
        d = task_level(ps, f)
        res["metrics"][k] = {"median_A": statistics.median([f(x) for x, _ in ps]) if ps else None,
                             "median_B": statistics.median([f(y) for _, y in ps]) if ps else None,
                             "diff_median_task": statistics.median(d) if d else None, "diff_ci_task": boot_ci(d),
                             "sign_p_task": sign_test(d)}
    sa, sb = sum(x.get("usd") or 0 for x, _ in ps), sum(y.get("usd") or 0 for _, y in ps)
    res["spend_ratio"] = round(sb / sa, 3) if sa else None
    return res


def summarize(rows: list[dict]) -> dict:
    rows = [r for r in rows if "error" not in r]
    res: dict = {"units": len(rows), "spend_usd": spent(rows), "per_arm": {}, "per_task": {}}
    for arm in ARMS:
        rs = [r for r in rows if r["arm"] == arm]
        if not rs:
            continue
        k = sum(bool(r["ok"]) for r in rs)
        res["per_arm"][arm] = {
            "n": len(rs), "ok": k, "ok_wilson": S.wilson(k, len(rs)), "usd": spent(rs), "cps": cps(rs),
            "cps_ci_task": cps_ci(rs), "wall_median": statistics.median([r["wall_s"] for r in rs]),
            "lead_tokens_median": statistics.median([r.get("lead_tokens") or 0 for r in rs]),
            "lead_only_usd_median": statistics.median([r.get("lead_only_usd") or 0 for r in rs]),
            "sub_usd_median": statistics.median([r.get("sub_usd") or 0 for r in rs]),
            "rework": sum(r.get("rework") or 0 for r in rs), "units_with_rework": sum(bool(r.get("rework")) for r in rs),
            "delegated": sum(bool(r.get("delegated")) for r in rs) if arm != "self" else None,
            "lead_edited": sum(bool(r.get("lead_edits")) for r in rs),
            "ccx_agents": sorted({a for r in rs for a in r.get("ccx_agents") or []}),
            "ccx_rungs": {g: sum(g in (r.get("ccx_rungs") or []) for r in rs)
                          for g in sorted({g for r in rs for g in r.get("ccx_rungs") or []})},
            "fix_rounds": sum(r.get("ccx_fix_rounds") or 0 for r in rs),
            "timeouts": sum(r.get("rc") == -9 for r in rs)}
    for t in sorted({r["task"] for r in rows}):
        res["per_task"][t] = {arm: f"{sum(bool(r['ok']) for r in rows if r['task'] == t and r['arm'] == arm)}/"
                                   f"{sum(r['task'] == t and r['arm'] == arm for r in rows)}" for arm in ARMS}
    comps = [("builtin", "ccx"), ("self", "builtin"), ("self", "ccx")]
    for A, B in comps:
        ps = paired(rows, A, B)
        if ps:
            res[f"{A}->{B}"] = compare(ps, A, B)
    res["ok_holm"] = {k: {"p": p, "p_holm": q} for k, (p, q) in
                      holm({f"{A}->{B}": res[f"{A}->{B}"]["mcnemar_p"] for A, B in comps if f"{A}->{B}" in res}).items()}
    l8 = [dict(x, arm=r["arm"], task=r["task"]) for r in rows for x in r.get("l8") or [] if x.get("read_share") is not None]
    lead_l8 = [r["l8_lead"]["read_share"] for r in rows if r["arm"] == "self" and (r.get("l8_lead") or {}).get("read_share") is not None]
    res["l8"] = {"sub_runs": len(l8),
                 "read_share_median": statistics.median([x["read_share"] for x in l8]) if l8 else None,
                 "read_share_ci": boot_ci([x["read_share"] for x in l8]),
                 "over_half": sum(x["read_share"] > 0.5 for x in l8),
                 "by_arm": {arm: {"n": len(v), "median": statistics.median(v) if v else None,
                                  "max": max(v) if v else None}
                            for arm in ("builtin", "ccx") for v in [[x["read_share"] for x in l8 if x["arm"] == arm]]},
                 "pooled_share": round(sum(x["read_tokens"] for x in l8) / max(1, sum(x["tokens"] for x in l8)), 4),
                 "self_lead_median": statistics.median(lead_l8) if lead_l8 else None}
    return res


SCRUB = [(str(ROOT.as_posix()), "<repo>"), (str(ROOT), "<repo>"), (str(Path.home().as_posix()), "~"),
         (str(Path.home()), "~")]


def scrub(o):
    if isinstance(o, str):
        for a, b in SCRUB:
            o = o.replace(a, b)
        o = re.sub(r"[A-Za-z]:[\\/]+[^\s\"']*", "<path>", o)              # any other absolute Windows path
        o = re.sub(r"[A-Za-z]--Users-[^\s\"'/\\]*", "<project-slug>", o)  # Claude's projects/<folder slug>
        o = re.sub(Path.home().name, "<user>", o, flags=re.I)
        return o
    if isinstance(o, list):
        return [scrub(x) for x in o]
    if isinstance(o, dict):
        return {k: scrub(v) for k, v in o.items() if k not in ("hub", "ccx_run_ids", "seed")}
    return o


def cmd_summary(a) -> int:
    rows = read_jsonl(Path(a.file) if a.file else OUT / "results.jsonl")
    if a.tag:
        rows = [r for r in rows if r.get("tag") == a.tag]
    print(json.dumps(summarize(rows), ensure_ascii=False, indent=1))
    return 0


def cmd_export(a) -> int:
    rows = read_jsonl(Path(a.file) if a.file else OUT / "results.jsonl")
    if a.tag:
        rows = [r for r in rows if r.get("tag") == a.tag]
    keep = ("tag", "round", "task", "arm", "ok", "pytest", "rc", "wall_s", "usd", "lead_usd", "lead_only_usd",
            "sub_usd", "by_model_usd", "ccx_usd", "ccx_review_usd", "ccx_agents", "ccx_rungs", "lead_requests",
            "lead_tokens", "lead_output_tokens", "lead_tools", "lead_edits", "agent_calls", "ccx_runs", "ccx_resumes",
            "rework", "delegated", "ccx_fix_rounds", "ccx_review_verdicts", "context_attached", "l8", "l8_lead",
            "bash", "ok_first", "rescored", "error")
    data = {"summary": summarize(rows), "rows": [scrub({k: r[k] for k in keep if k in r}) for r in rows]}
    Path(a.dest).write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {a.dest}: {len(rows)} rows")
    return 0


def cmd_rescore(a) -> int:
    """Score every unit's repo (still in the work dir) again with the hidden tests as they are now; the first verdict
    stays in `ok_first`. Used once: env-config's hidden test lost an assertion that the code did not support (§7)."""
    out = Path(a.file) if a.file else OUT / "results.jsonl"
    rows, changed, missing = read_jsonl(out), 0, 0
    for r in rows:
        if a.tasks and r["task"] not in a.tasks.split(","):
            continue
        repo = Path(a.workdir) / f"{r['round']}-{r['task']}-{r['arm']}"
        if "error" in r or not repo.is_dir():
            missing += 1
            continue
        sc = score(repo, by_id(r["task"]))
        r.setdefault("ok_first", r["ok"])
        changed += bool(sc["ok"]) != bool(r["ok"])
        r.update(ok=sc["ok"], pytest=sc["pytest"], rescored=True)
    out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    print(f"rescored; {changed} verdicts changed, {missing} units without a repo")
    return 0


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--tag", default="r3")
    r.add_argument("--seed", type=int, default=27)
    r.add_argument("--rounds", type=int, default=2)
    r.add_argument("--tasks", default="")
    r.add_argument("--arms", default="")
    r.add_argument("--budget", type=float, default=8.0, help="stop before a new unit once r3 + L5 reach $")
    r.add_argument("--lead-budget", type=float, default=0.8, help="claude -p --max-budget-usd for one lead")
    r.add_argument("--out", default="")
    r.add_argument("--workdir", default="")
    r.add_argument("--timeout", type=int, default=1200)
    r.add_argument("--dry-run", action="store_true")
    r.set_defaults(fn=cmd_run)
    s = sub.add_parser("summary")
    s.add_argument("--file", default="")
    s.add_argument("--tag", default="")
    s.set_defaults(fn=cmd_summary)
    rs = sub.add_parser("rescore")
    rs.add_argument("--workdir", required=True)
    rs.add_argument("--tasks", default="")
    rs.add_argument("--file", default="")
    rs.set_defaults(fn=cmd_rescore)
    e = sub.add_parser("export")
    e.add_argument("dest")
    e.add_argument("--file", default="")
    e.add_argument("--tag", default="")
    e.set_defaults(fn=cmd_export)
    return ap


def main(argv=None) -> int:
    a = parser().parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
