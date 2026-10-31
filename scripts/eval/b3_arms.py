"""B3 "fewer runs" arms (docs/research/2026-10-30-b3-lean-switches-plan.md, "Fewer runs"): each of the three switches
merged off by default is run against today's behaviour on the same tasks, so the lead can decide whether to turn it on.

  m4  `ccx batch <plan>` (batch, the baseline) vs `ccx batch --merge <plan>` (merge). A plan is four small pieces of
      round 2's ten-module task (tasks_r2.PIECES, one module and its test file each, `minutes` 2) and one trap of
      tasks_r2.TRAPS2 (`minutes` 5), every piece with its `paths` and its own `--check`; Codex at a fixed model
      (gpt-6.1-sol medium, the T2 rung), `--from user`, review as shipped (auto). With five writers in one clean
      repository each arm's runs go to worktrees, as ccx does by default; each piece is scored in the folder its run
      left (its hidden test only).
  m3  `ccx run --parallel` with `[subagents] fork_turns = "all"` (the default) vs `"none"`: round 2's four three-file
      fixes (tasks_r2.COMPOUND) and two groups of four modules (tasks_r2.PIECES); Codex gpt-6.1-sol medium, review
      off, no escalation or fallback (a run moved to another agent has no spawn_agent and is dropped), the task's
      tests as --check. The children's first request inputs are read from their rollout files.
  m5  `[shared_context] dedupe = false` (keep) vs `true` (dedupe): the 2026-10-25 shared-context A/B tasks
      (shared_context_ab.TASKS, a fake lead session with what the person settled) plus one where the person reopened
      the question and the lead settled it again (t8-reopened, kept by dedupe by design); Codex gpt-6-luna low,
      `--context on`, review off, first try only (no rework round), scored as the 2026-10-25 A/B scored.

Every unit runs in a clean room of its own (scripts/eval/preflight.py: allow-listed environment, own TMP, git
identity, CCX_CONFIG, a fresh hub, the dedicated eval CODEX_HOME with CCX_CODEX_ISOLATE=1; a Job Object, leftovers
listed and killed after the unit). Both arms of an experiment get the same hub file except the one switch, written
explicitly for both (`false` / `"all"` too) and read back the way ccx reads it before the unit starts; after the
unit the switch is checked in what ccx recorded (m4: the batch output's `merged`; m3: run.json
`parallel_fork_turns`; m5: run.json `shared_context.deduped`) and a unit whose switch did not take is `switch_ok:
false` and left out of the rule. Sessions are not archived while the unit runs (`[sessions] archive = "off"`, both
arms: the children's rollouts are read afterwards), then archived with `ccx archive --apply`.

Per unit: right (pieces / the task's hidden test), ccx runs (all ledger rows: sub-agent runs, reviews, fix rounds,
spun-off pieces), reviews and their $, requests, `first_input` summed over the runs (m3: plus each child's first
request), total prompt tokens (fresh + cache writes + cache reads of every run; for m3 the ledger's usage already holds
the children's), $, wall.

The rule (registered before any unit ran, the plan doc's "Fewer runs" section), per experiment on the units both arms
finished with the switch recorded: Pass when (1) the arm's right count is not below the baseline's (m4: over all
pieces and over the trap pieces alone), (2) its ccx runs or its first_input sum is lower, (3) its total prompt
tokens are not higher (m5: reported only, since one more turn would outweigh what dedupe saves); m3 also fails when a pair has the arm wrong, the baseline right and the arm's run spawned
children (a child that lacked the context it was not given, not caught by its parent). Fewer than 80% of the
planned pairs (as the run recorded them in its rows), any unit whose switch did not take, or (m3) more than half
of the pairs spawning no child in either arm: Unknown. A unit that
failed (an error in its row) is missing, not a switch that did not take, and `run` again retries it.

  python scripts/eval/b3_arms.py run --exp m4 --tag b3m4 --codex-home <eval codex home> --budget 5 [--dry-run]
  python scripts/eval/b3_arms.py run --exp m3 --tag b3m3 --codex-home <eval codex home> --budget 4
  python scripts/eval/b3_arms.py run --exp m5 --tag b3m5 --codex-home <eval codex home> --budget 1.5
  python scripts/eval/b3_arms.py summary [--exp m4] [--tag b3m4]

Results: .ccx/eval/b3arms/results.jsonl (one row per unit; `run` again skips finished units of the tag).
Needs a logged-in `codex` in the eval home (and `claude` for m4's reviews); tests never call this with real ones.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import preflight as PF  # noqa: E402
import r2  # noqa: E402
import shared_context_ab as SC  # noqa: E402
from common import HIDDEN, ROOT, append_jsonl, archive_hub, make_repo, read_jsonl, score  # noqa: E402
from tasks_r2 import COMPOUND, PIECES, TRAPS2, piece_brief  # noqa: E402

from ccx import ledger  # noqa: E402
from ccx.config import Paths, load_config  # noqa: E402

OUT = ROOT / ".ccx" / "eval" / "b3arms"
RESULTS = OUT / "results.jsonl"
# experiment -> (baseline arm, switch arm); the baseline is today's shipped behaviour
EXPS = {"m4": ("batch", "merge"), "m3": ("all", "none"), "m5": ("keep", "dedupe")}
MODEL = {"m4": ("gpt-6.1-sol", "medium"), "m3": ("gpt-6.1-sol", "medium"), "m5": ("gpt-6-luna", "low")}
REPS = {"m4": 2, "m3": 1, "m5": 2}
ACCEPT = "python -m pytest -q"
# what one unit costs, for --dry-run and the budget line only (not a measurement): the 2026-10-31 pre-run (m4 mp1
# merge: $0.10, 2 runs) and the 2026-10-25 A/B's luna low runs; the others are guesses from round 2
EST_USD = {("m4", "batch"): 0.35, ("m4", "merge"): 0.12, ("m3", "all"): 0.25, ("m3", "none"): 0.22,
           ("m5", "keep"): 0.02, ("m5", "dedupe"): 0.02}
MIN_COVER = 0.8                   # below this share of the planned pairs the rule says Unknown

# ------------------------------------------------------------------ the tasks

_PIECE = {p["id"]: p for p in PIECES}
_TRAP = {t["id"]: t for t in TRAPS2}
# m4 plans: four pieces (each its own module) + one trap; ids are the plan's
M4_PLANS = {"mp1": (["m01", "m02", "m03", "m04"], "dupparse"), "mp2": (["m05", "m06", "m07", "m08"], "cache"),
            "mp3": (["m09", "m10", "m01", "m05"], "rounding"), "mp4": (["m02", "m04", "m06", "m08"], "exporter")}
PIECE_MINUTES, TRAP_MINUTES = 2, 5


def _pieces_task(tid: str, ids: list[str]) -> dict:
    ps = [_PIECE[i] for i in ids]
    return {"id": tid, "brief": piece_brief(ps), "files": {**{p["file"]: p["stub"] for p in ps}, "tests/__init__.py": ""},
            "visible": None, "hidden": "import pytest  # noqa: F401\n\n\n" + "\n\n".join(p["hidden"] for p in ps)}


M3_TASKS = {**{t["id"]: t for t in COMPOUND if t["id"] in ("bank", "board", "fleet", "courses")},
            "pg-a": _pieces_task("pg-a", ["m01", "m02", "m03", "m04"]),
            "pg-b": _pieces_task("pg-b", ["m05", "m06", "m07", "m08"])}

# m5: the 2026-10-25 tasks plus one where the person reopened the settled question and the lead settled it again in
# other words: dedupe drops the person's sentence (it is in "The person asked") and must keep the lead's
T8 = {**SC.T("t8-reopened", {"net.py": "def fetch_with_retries(fetch):\n    return fetch()\n"},
             "In net.py, add a module constant MAX_RETRIES set to the value we settled on, and make "
             "fetch_with_retries(fetch) call fetch() again on an exception, at most MAX_RETRIES retries, re-raising "
             "the last exception.",
             "Settled: MAX_RETRIES is 3.",
             "import pytest\nimport net\n\ndef test_retries():\n    assert net.MAX_RETRIES == 3, 'agreed: 3'\n"
             "    calls = []\n    def bad():\n        calls.append(1)\n        raise OSError('x')\n"
             "    with pytest.raises(OSError):\n        net.fetch_with_retries(bad)\n    assert len(calls) == 4\n"),
      "after": [("person", "Should we raise MAX_RETRIES to 5 instead?"),
                ("claude", "Decided: we keep MAX_RETRIES at 3, not 5. The API allows only a few retries a minute.")]}
M5_TASKS = {**{t["id"]: t for t in SC.TASKS}, T8["id"]: T8}
TASKS = {"m4": list(M4_PLANS), "m3": list(M3_TASKS), "m5": list(M5_TASKS)}


def m4_material(plan_id: str) -> tuple[dict, list[dict]]:
    """The start repository of a plan (all pieces' stubs, the trap's files and visible test) and its pieces:
    {id, kind, brief, check, minutes, paths, hidden}."""
    ids, trap_id = M4_PLANS[plan_id]
    trap = _TRAP[trap_id]
    files = {**{_PIECE[i]["file"]: _PIECE[i]["stub"] for i in ids}, "tests/__init__.py": "", **trap["files"]}
    pieces = [{"id": i, "kind": "piece", "brief": piece_brief([_PIECE[i]]), "check": f"{ACCEPT} tests/test_{i}.py",
               "minutes": PIECE_MINUTES, "paths": [_PIECE[i]["file"], f"tests/test_{i}.py"],
               "hidden": "import pytest  # noqa: F401\n\n\n" + _PIECE[i]["hidden"]} for i in ids]
    pieces.append({"id": trap_id, "kind": "trap", "brief": trap["brief"], "check": f"{ACCEPT} test_task.py",
                   "minutes": TRAP_MINUTES, "paths": sorted([*trap["files"], "test_task.py"]), "hidden": trap["hidden"]})
    return {"id": plan_id, "files": files, "visible": trap.get("visible")}, pieces


def m4_plan(pieces: list[dict], repo: Path, model: tuple[str, str]) -> dict:
    """The plan file both arms run (the arm only adds --merge). Ids start with eval- so the merged run's label is
    eval-merge:... and every row stays out of ccx's learning (ledger.is_eval)."""
    return {"tasks": [{"id": f"eval-{p['id']}", "brief": p["brief"], "to": "codex", "model": model[0],
                       "effort": model[1], "mode": "write", "check": p["check"], "cwd": str(repo),
                       "minutes": p["minutes"], "paths": p["paths"]} for p in pieces]}


def m5_transcript(task: dict, now: float) -> list[dict]:
    """shared_context_ab's lead conversation, with the task's `after` turns (the reopened question) before the
    lead's last words."""
    evs = SC.lead_transcript(task, now)
    after = task.get("after") or []
    if not after:
        return evs
    out = list(evs[:-2])                 # up to the settled sentence (now - 60); the last two: ack, tool calls
    for k, (who, text) in enumerate(after):
        ts = SC._iso(now - 60 + 10 * (k + 1))
        out.append({"type": "user", "timestamp": ts, "message": {"content": text}} if who == "person" else
                   {"type": "assistant", "timestamp": ts, "message": {"content": [{"type": "text", "text": text}]}})
    return out + evs[-2:]


# ------------------------------------------------------------------ the hub: one switch, written for both arms

HUB_BASE = "# eval-b3arms throwaway hub\n[defaults]\nab_self_rate = 0.0\n[sessions]\narchive = \"off\"\n"
SWITCH = {"m4": ("merge", "default", {"batch": False, "merge": False}),       # --merge is the switch, not the hub
          "m3": ("subagents", "fork_turns", {"all": "all", "none": "none"}),
          "m5": ("shared_context", "dedupe", {"keep": False, "dedupe": True})}


def hub_toml(exp: str, arm: str) -> str:
    table, key, vals = SWITCH[exp]
    v = vals[arm]
    return HUB_BASE + f"[{table}]\n{key} = {json.dumps(v)}\n"


def resolved(hub: Path, exp: str) -> dict:
    """The switch and the archive setting as ccx itself reads them from the hub."""
    from ccx import context_share, merge, subagents
    cfg = load_config(Paths(hub))
    sw = {"m4": lambda: merge.settings(cfg)["default"], "m3": lambda: subagents.fork_turns(cfg),
          "m5": lambda: context_share.setting(cfg, "dedupe", False) is True}[exp]()
    return {"switch": sw, "archive": (cfg.get("sessions") or {}).get("archive")}


def make_hub(hub: Path, exp: str, arm: str) -> dict:
    r2._rmtree(hub)
    (hub / "ccx").mkdir(parents=True)
    (hub / "ccx" / "tiers.toml").write_text(hub_toml(exp, arm), encoding="utf-8")
    got = resolved(hub, exp)
    want = SWITCH[exp][2][arm]
    if got != {"switch": want, "archive": "off"}:
        raise RuntimeError(f"the unit hub resolves {got}, not switch={want!r} archive='off'")
    return {"tiers_toml": hub_toml(exp, arm), **got}


# ------------------------------------------------------------------ what a unit spent and did

def hub_rows(hub: Path) -> list[dict]:
    return [r for r in ledger.rows(Paths(hub)) if not r.get("type")]


def prompt_tokens(row: dict) -> int:
    u = row.get("usage") or {}
    return int(u.get("input", 0) or 0) + int(u.get("cached", 0) or 0)


def run_stats(hub: Path) -> dict:
    rows = hub_rows(hub)
    rev = [r for r in rows if str(r.get("label") or "").startswith("review:")]
    return {"runs": len(rows), "reviews": len(rev), "review_usd": round(sum(r.get("ae_usd") or 0 for r in rev), 6),
            "usd": round(sum(r.get("ae_usd") or 0 for r in rows), 6),
            "requests": sum(int(r.get("requests") or 0) for r in rows),
            "first_input": sum(int(r.get("first_input") or 0) for r in rows),
            "first_input_missing": sum(r.get("first_input") is None for r in rows),
            "prompt_tokens": sum(prompt_tokens(r) for r in rows), "run_ids": [r["run_id"] for r in rows],
            "agents": sorted({str(r.get("provider") or r.get("to")) for r in rows})}


def rollout_lines(codex_home: Path | None, sid: str) -> list[dict]:
    """The events of one Codex session's rollout (live or archived)."""
    if not codex_home or not sid:
        return []
    for sub in ("sessions", "archived_sessions"):
        for f in (codex_home / sub).rglob(f"rollout-*{sid}.jsonl") if (codex_home / sub).is_dir() else []:
            out = []
            for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
            return out
    return []


def rollout_inputs(codex_home: Path | None, sid: str) -> list[int]:
    """Every request's input of one Codex session, in order: its own token_usage_records only. A forked session's
    file starts with copies of older history (ccx/usage.py), which are older than its session_meta and dropped."""
    from ccx.usage import _ts
    evs = rollout_lines(codex_home, sid)
    meta = next((e for e in evs if e.get("type") == "session_meta"), {})
    since = _ts((meta.get("payload") or {}).get("timestamp") or meta.get("timestamp"))
    out: list[tuple[float, int]] = []
    for e in evs:
        u = (e.get("payload") or {}).get("usage") or {}
        t = _ts(e.get("timestamp"))
        if e.get("type") == "token_usage_record" and u and t is not None and (since is None or t >= since):
            out.append((t, int(u.get("input_tokens", 0) or 0)))
    return [n for _, n in sorted(out, key=lambda x: x[0])]


FORK_NONE_ARG = re.compile(r"fork_turns\W{0,4}none")


def spawn_calls(codex_home: Path | None, sid: str) -> dict:
    """The parent's spawn_agent calls in its rollout (a direct call, or code mode's `spawn_agent(` in an exec
    call) and how many of them passed fork_turns "none": whether the children really started without history."""
    n = none = 0
    for e in rollout_lines(codex_home, sid):
        pl = e.get("payload") or {}
        if pl.get("type") not in ("function_call", "custom_tool_call"):
            continue
        body = str(pl.get("arguments") or "") + str(pl.get("input") or "")
        k = 1 if pl.get("name") == "spawn_agent" else body.count("spawn_agent(")
        n += k
        none += min(k, len(FORK_NONE_ARG.findall(body)))
    return {"spawn_calls": n, "fork_none_calls": none}


def children_stats(hub: Path, run_ids: list[str], codex_home: Path | None) -> dict:
    """The Codex children the runs spawned (run.json codex_children) and, from their rollouts, each one's first
    request input, request count and total input."""
    kids = []
    for rid in run_ids:
        for cid in (r2.record(hub, rid).get("codex_children") or {}):
            ins = rollout_inputs(codex_home, cid)
            kids.append({"id": cid, "first_input": ins[0] if ins else None, "requests": len(ins), "prompt": sum(ins)})
    firsts = sorted(k["first_input"] for k in kids if k["first_input"] is not None)
    return {"n": len(kids), "first_inputs": firsts, "first_input": sum(firsts), "requests": sum(k["requests"] for k in kids),
            "prompt_tokens": sum(k["prompt"] for k in kids), "unread": sum(k["first_input"] is None for k in kids),
            "first_input_median": firsts[len(firsts) // 2] if firsts else None}


def hidden_ok(folder: Path, hidden: str) -> tuple[bool, str]:
    """The hidden test alone, in the folder a run left."""
    f = folder / HIDDEN
    f.write_text(hidden, encoding="utf-8")
    try:
        r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", HIDDEN], cwd=folder,
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    except subprocess.TimeoutExpired:
        return False, "timeout"
    finally:
        f.unlink(missing_ok=True)
    return r.returncode == 0, ((r.stdout.strip().splitlines() or [""])[-1])[:200]


def ccx_argv(*args: str) -> list[str]:
    return [sys.executable, str(ROOT / "ccx.py"), *args]


# ------------------------------------------------------------------ the units

def m4_unit(u: dict, a, iso: PF.Unit, env: dict, job: PF.Job) -> dict:
    mat, pieces = m4_material(u["task"])
    make_repo(mat, iso.repo)
    pf = iso.work / f"{iso.key}.plan.json"           # outside the checkout: it stays clean, so worktrees are made
    pf.write_text(json.dumps(m4_plan(pieces, iso.repo, MODEL["m4"]), indent=1), encoding="utf-8")
    argv = ccx_argv("batch", str(pf), "--from", "user", *(["--merge"] if u["arm"] == "merge" else []))
    t0 = time.time()
    out, err, rc, _left = PF.run(argv, cwd=iso.repo, env=env, timeout=a.timeout, job=job)
    wall = round(time.time() - t0, 1)
    res = r2.S._last_json(out)
    if rc not in (0, 2) or not res.get("results"):
        raise RuntimeError(f"ccx batch did not finish (rc {rc}): {err[-300:]}")
    by_label = {}
    for r in res.get("results") or []:
        lbl = r.get("label") or r2.record(iso.hub, r.get("run_id")).get("label")
        by_label[lbl] = r
    per = []
    for p in pieces:
        r = by_label.get(f"eval-{p['id']}")
        folder = Path(r["worktree"]) if r and r.get("worktree") and Path(r["worktree"]).is_dir() else iso.repo
        ok, tail = hidden_ok(folder, p["hidden"]) if r else (False, "no result")
        per.append({"id": p["id"], "kind": p["kind"], "ok": ok, "pytest": tail, "ccx_ok": (r or {}).get("ok"),
                    "run_id": (r or {}).get("run_id"), "merged_run": (r or {}).get("merged_run"),
                    "worktree": bool(r and r.get("worktree")), "spun_off": (r or {}).get("spun_off"),
                    "piece_fix": (r or {}).get("piece_fix"), "escalated": (r or {}).get("escalated")})
    merged = res.get("merged") or []
    st = run_stats(iso.hub)
    return {"rc": rc, "wall_s": wall, "stderr": err[-400:] if rc not in (0, 2) else "", "pieces": per,
            "right": sum(x["ok"] for x in per), "right_trap": sum(x["ok"] for x in per if x["kind"] == "trap"),
            "n_pieces": len(per), "merged": merged, "follow_ups": sum(bool(m.get("follow_up")) for m in merged),
            "spun_off": sum(len(m.get("spun_off") or []) for m in merged),
            "switch_seen": bool(merged), "switch_ok": bool(merged) == (u["arm"] == "merge"),
            **st}


def m3_unit(u: dict, a, iso: PF.Unit, env: dict, job: PF.Job) -> dict:
    task = M3_TASKS[u["task"]]
    make_repo(task, iso.repo)
    m, e = MODEL["m3"]
    argv = ccx_argv("run", "--mode", "write", "--new", "--no-ab", "--force", "--label", u["label"], "--to", "codex",
                    "--model", m, "--effort", e, "--review", "off", "--no-escalate", "--no-fallback", "--parallel",
                    "--check", ACCEPT, task["brief"])
    t0 = time.time()
    out, err, rc, _left = PF.run(argv, cwd=iso.repo, env=env, timeout=a.timeout, job=job)
    wall = round(time.time() - t0, 1)
    res = r2.S._last_json(out)
    ok, tail = hidden_ok(iso.repo, task["hidden"])
    st = run_stats(iso.hub)
    rec = r2.record(iso.hub, res.get("run_id"))
    from ccx import subagents
    sent = iso.hub / "ccx" / "runs" / str(res.get("run_id")) / "prompt.md"     # what the sub-agent was sent
    told = subagents.FORK_NONE.strip() in (sent.read_text(encoding="utf-8") if sent.exists() else "")
    if not res.get("run_id") or not sent.exists():
        raise RuntimeError(f"the run did not start (rc {rc}): {err[-300:]}")
    kids = children_stats(iso.hub, st["run_ids"], iso.codex_home)
    kids.update(spawn_calls(iso.codex_home, rec.get("session_id")))
    seen = rec.get("parallel_fork_turns")
    return {"rc": rc, "wall_s": wall, "stderr": err[-400:] if rc else "", "ok": ok, "pytest": tail,
            "right": int(ok), "ccx_ok": res.get("ok"), "status": res.get("status"), "run_id": res.get("run_id"),
            "children": kids, "fork_none_in_prompt": told if sent.exists() else None,
            "switch_seen": seen, "moved": bool(rec.get("parallel_fork_turns_moved")),
            "switch_ok": seen == u["arm"] and not rec.get("parallel_fork_turns_moved")
            and told == (u["arm"] == "none"),
            # the ledger's usage already holds the children's tokens (agents/codex.py adds them to each attempt):
            # prompt_tokens is the ledger's; first_input adds each child's first request, which the ledger has not
            **st, "first_input_runs": st["first_input"], "first_input": st["first_input"] + kids["first_input"]}


def m5_unit(u: dict, a, iso: PF.Unit, env: dict, job: PF.Job) -> dict:
    task = M5_TASKS[u["task"]]
    make_repo(task, iso.repo)
    sid = f"b3m5-{iso.key}".replace(".", "-")
    f = iso.claude_dir / "projects" / "lead" / f"{sid}.jsonl"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("".join(json.dumps(e) + "\n" for e in m5_transcript(task, time.time())), encoding="utf-8")
    env = {**env, "CCX_LEAD_SESSION": sid, "CCX_AB_RATE": "0"}
    m, e = MODEL["m5"]
    argv = ccx_argv("run", "--from", "claude", "--to", "codex", "--model", m, "--effort", e, "--mode", "write",
                    "--context", "on", "--new", "--no-ab", "--no-escalate", "--no-fallback", "--review", "off",
                    "--no-subagents", "--label", u["label"], "--cwd", str(iso.repo), task["brief"])
    t0 = time.time()
    out, err, rc, _left = PF.run(argv, cwd=iso.repo, env=env, timeout=a.timeout, job=job)
    wall = round(time.time() - t0, 1)
    res = r2.S._last_json(out)
    sc = score(iso.repo, task)
    rec = r2.record(iso.hub, res.get("run_id"))
    ctx = rec.get("shared_context") or {}
    keep = {k: ctx.get(k) for k in ("chars", "est_tokens", "items", "deduped", "deduped_chars") if k in ctx}
    attached = bool(ctx.get("source")) and bool(ctx.get("chars"))
    if not res.get("run_id") or not attached:
        raise RuntimeError(f"no run or no shared context attached (rc {rc}, {ctx.get('why')}): {err[-200:]}")
    return {"rc": rc, "wall_s": wall, "stderr": err[-400:] if rc else "", "ok": sc["ok"], "pytest": sc["pytest"],
            "right": int(sc["ok"]), "ccx_ok": res.get("ok"), "status": res.get("status"), "run_id": res.get("run_id"),
            "shared_context": keep, "context_attached": attached, "switch_seen": "deduped" in ctx,
            "switch_ok": attached and ("deduped" in ctx) == (u["arm"] == "dedupe"), **run_stats(iso.hub)}


UNIT = {"m4": m4_unit, "m3": m3_unit, "m5": m5_unit}


def unit_key(u: dict) -> str:
    return f"{u['exp']}-{u['rep']}-{u['task']}-{u['arm']}"


def iso_of(u: dict, a, work: Path) -> PF.Unit:
    # the folders are named without the arm: the cwd is in the sub-agent's prompt, so both arms see the same one
    # (the two units of a pair run one after another and each removes its folders)
    key = f"{u['exp']}-{u['rep']}-{u['task']}"
    # m5's fake lead session lives in the unit's own Claude home (no Claude process runs in m5); m4 may start a
    # Claude reviewer, which keeps the person's login under the flags isolation, as round 5's default
    return PF.Unit(key=key, work=work, repo=work / key, hub=work / f"h-{key}", label=u["label"],
                   claude="config-dir" if u["exp"] == "m5" else "flags",
                   codex_home=Path(PF.codex_home_arg(a.codex_home)) if a.codex_home else None, dsh="unit")


def unit_env(iso: PF.Unit) -> dict:
    return PF.prepare(iso)


def run_unit(u: dict, a, work: Path) -> dict:
    """One unit in its clean room; an error is a field of the row, never a lost row."""
    iso = iso_of(u, a, work)
    row: dict = {**u, "model": "/".join(MODEL[u["exp"]])}
    before, job = PF.snapshot(), PF.Job()
    env = None
    try:
        r2._rmtree(iso.repo)
        row["hub"] = make_hub(iso.hub, u["exp"], u["arm"])
        env = unit_env(iso)
        row.update(UNIT[u["exp"]](u, a, iso, env, job))
    except Exception as x:  # noqa: BLE001
        row.update(error=f"{type(x).__name__}: {x}"[:400], switch_ok=False)
        try:                     # what a failed unit spent still counts against the budget
            row.update({k: v for k, v in run_stats(iso.hub).items() if k not in row})
        except Exception:  # noqa: BLE001
            pass
    finally:
        try:
            row["archived_sessions"] = archive_hub(iso.hub, env) if env else 0
        except Exception:  # noqa: BLE001
            row["archived_sessions"] = None
        try:
            row["leftovers"] = PF.after_unit(iso, before, job, keep_repo=False)
        except Exception as x:  # noqa: BLE001
            row["leftovers"] = {"error": str(x)[:200]}
        for d in (iso.repo, iso.hub, iso.worktrees):
            r2._rmtree(d)
        (work / f"{iso.key}.plan.json").unlink(missing_ok=True)
        r2._rmtree(iso.x)
    row["ts"] = datetime.now(timezone.utc).isoformat()
    return row


# ------------------------------------------------------------------ the schedule

def schedule(exps: list[str], reps: dict, tasks: dict) -> list[dict]:
    """Every experiment's units, rep by rep and task by task; the two arms of a pair run back to back, the
    baseline first on even task positions (rep 1) and the switch first on odd ones, flipped every rep."""
    out = []
    for exp in exps:
        base, arm = EXPS[exp]
        for rep in range(1, reps[exp] + 1):
            for i, t in enumerate(tasks[exp]):
                pair = (base, arm) if (i + rep) % 2 else (arm, base)
                out += [{"exp": exp, "task": t, "rep": rep, "arm": x} for x in pair]
    return out


def done_key(r: dict) -> tuple:
    return r.get("tag"), r.get("exp"), r.get("task"), r.get("rep"), r.get("arm")


def spent(rows: list[dict], tag: str) -> float:
    return round(sum(r.get("usd") or 0 for r in rows if r.get("tag") == tag), 4)


def estimate(todo: list[dict]) -> float:
    return round(sum(EST_USD[(u["exp"], u["arm"])] for u in todo), 2)


def commit() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace").stdout.strip()


def preflight(a, work: Path) -> list[str]:
    """What must hold before the first unit: no other heavy work, the eval Codex home (unelevated sandbox on
    Windows, logged in), and one tiny real Codex command in it (the canary)."""
    probs = []
    busy = PF.busy(PF.snapshot(), ours=[str(work)])
    if busy:
        probs.append("busy: " + "; ".join(busy[:3]))
    p, info = PF.check_codex_home(Path(PF.codex_home_arg(a.codex_home)) if a.codex_home else None, True,
                                  PF.real_paths(), write=True)
    probs += [str(x[0] if isinstance(x, tuple) else x) for x in p]
    if not probs and not a.no_canary:
        can = PF.codex_canary(work, {"claude": "flags", "codex_home": Path(PF.codex_home_arg(a.codex_home)),
                                     "dsh": "unit"})
        if not can.get("ok"):
            probs.append(f"codex canary failed: {str(can.get('info'))[:300]}")
    return probs


def cmd_run(a) -> int:
    exps = [x.strip() for x in a.exp.split(",") if x.strip()]
    bad = [x for x in exps if x not in EXPS]
    if bad:
        raise SystemExit(f"unknown experiment(s) {bad}: {', '.join(EXPS)}")
    reps = {x: a.reps or REPS[x] for x in exps}
    want = [t for t in a.tasks.split(",") if t] if a.tasks else None
    tasks = {x: [t for t in TASKS[x] if not want or t in want] for x in exps}
    res = Path(a.out) if a.out else RESULTS
    rows = read_jsonl(res)
    have = {done_key(r) for r in rows if not r.get("error")}
    planned = {x: len(tasks[x]) * reps[x] for x in exps}           # pairs the rule expects, per experiment
    todo = [{**u, "tag": a.tag, "label": f"eval-b3arms:{a.tag}:{unit_key(u)}", "planned_pairs": planned[u["exp"]]}
            for u in schedule(exps, reps, tasks)]
    arms = {x for x in a.arms.split(",") if x} if a.arms else None
    todo = [u for u in todo if done_key(u) not in have and (not arms or u["arm"] in arms)][: a.limit or None]
    est = estimate(todo)
    print(f"{len(todo)} unit(s) to run, estimated ${est} (budget ${a.budget}, tag {a.tag} spent "
          f"${spent(rows, a.tag)}); models " + ", ".join(f"{x} {'/'.join(MODEL[x])}" for x in exps), flush=True)
    if a.dry_run:
        for u in todo:
            print(f"[dry] {unit_key(u):34} est ${EST_USD[(u['exp'], u['arm'])]:.2f}")
        return 0
    if not a.codex_home:
        raise SystemExit("--codex-home <the eval Codex home> is required (the Codex runs must not load your own)")
    work = Path(a.workdir or Path(tempfile.gettempdir()) / f"b3arms-{a.tag}")
    work.mkdir(parents=True, exist_ok=True)
    probs = preflight(a, work)
    if probs:
        print("preflight: " + " | ".join(probs), flush=True)
        if not a.force_unclean:
            return 2
    fp = {"commit": commit(), "versions": PF.cli_versions(("codex", "claude")), "preflight": probs or "pass",
          "canary": not a.no_canary}
    for u in todo:
        done = {done_key(r) for r in read_jsonl(res) if not r.get("error")}
        partner = (u["tag"], u["exp"], u["task"], u["rep"], next(x for x in EXPS[u["exp"]] if x != u["arm"]))
        # the budget is checked before a pair starts, never between its two units
        if partner not in done and spent(read_jsonl(res), a.tag) + a.extra_spent >= a.budget:
            print(f"budget reached (${a.budget}): stopping before {unit_key(u)}", flush=True)
            break
        row = run_unit(u, a, work)
        row["fingerprint"] = fp
        append_jsonl(res, row)
        print(f"{unit_key(u):34} right={row.get('right')}/{row.get('n_pieces', 1)} runs={row.get('runs')} "
              f"first_input={row.get('first_input')} prompt={row.get('prompt_tokens')} ${row.get('usd')} "
              f"{row.get('wall_s')}s switch_ok={row.get('switch_ok')}" + (f" ERROR {row['error']}" if row.get("error")
                                                                          else ""), flush=True)
    print(f"spent: tag {a.tag} ${spent(read_jsonl(res), a.tag)}", flush=True)
    return 0


# ------------------------------------------------------------------ the summary and the registered rule

def _pairs(rows: list[dict], exp: str) -> tuple[list[tuple[dict, dict]], list[dict], int]:
    """(pairs of finished units with the switch recorded, units left out and why, pairs planned)."""
    base, arm = EXPS[exp]
    cells: dict = {}
    for r in rows:
        if r.get("exp") == exp:
            cells.setdefault((r.get("tag"), r.get("task"), r.get("rep")), {})[r.get("arm")] = r
    pairs, out = [], []
    for k, c in sorted(cells.items(), key=lambda kv: str(kv[0])):
        bad = [(x, c.get(x)) for x in (base, arm) if not c.get(x) or c[x].get("error") or not c[x].get("switch_ok")]
        if bad:
            out += [{"unit": list(k), "arm": x, "why": "missing" if not r else (r.get("error") or "switch did not take")}
                    for x, r in bad]
        else:
            pairs.append((c[base], c[arm]))
    return pairs, out, len(cells)


def _sum(rs: list[dict], k: str) -> float:
    return round(sum(r.get(k) or 0 for r in rs), 4)


def rule(rows: list[dict], exp: str, planned: int | None = None) -> dict:
    base, arm = EXPS[exp]
    pairs, left_out, cells = _pairs(rows, exp)
    if not planned:              # what each tag's run planned (recorded in its rows), else what the rows show
        by_tag: dict = {}
        for r in rows:
            if r.get("exp") == exp and r.get("planned_pairs"):
                by_tag[r.get("tag")] = max(by_tag.get(r.get("tag"), 0), int(r["planned_pairs"]))
        planned = max(sum(by_tag.values()), cells)
    A, B = [p[0] for p in pairs], [p[1] for p in pairs]
    side = {}
    for name, rs in ((base, A), (arm, B)):
        side[name] = {k: _sum(rs, k) for k in ("right", "runs", "reviews", "requests", "first_input", "prompt_tokens",
                                                "usd", "review_usd", "wall_s")}
        if exp == "m4":
            side[name].update(right_trap=_sum(rs, "right_trap"), n_pieces=_sum(rs, "n_pieces"),
                              follow_ups=_sum(rs, "follow_ups"), spun_off=_sum(rs, "spun_off"))
        if exp == "m3":
            kids = [x for r in rs for x in (r.get("children") or {}).get("first_inputs") or []]
            side[name].update(children=sum((r.get("children") or {}).get("n", 0) for r in rs),
                              child_first_input_median=sorted(kids)[len(kids) // 2] if kids else None)
        if exp == "m5":
            side[name].update(est_tokens=sum((r.get("shared_context") or {}).get("est_tokens") or 0 for r in rs),
                              deduped_chars=sum((r.get("shared_context") or {}).get("deduped_chars") or 0 for r in rs))
    a, b = side[base], side[arm]
    checks = {"right_not_lower": b["right"] >= a["right"],
              "runs_or_first_input_lower": b["runs"] < a["runs"] or b["first_input"] < a["first_input"]}
    if exp == "m5":
        # m5 saves tens of tokens a request, while one more request adds a ~20k prefix and every later request
        # carries the earlier turns: a total or a mean would be decided by the number of turns. Its saving is judged
        # by the first_input sum (condition 2, the prompt's own content); the totals are reported only (registered
        # so before any m5 unit ran)
        for x in (a, b):
            x["prompt_per_request"] = round(x["prompt_tokens"] / x["requests"], 1) if x["requests"] else None
    else:
        checks["prompt_not_higher"] = b["prompt_tokens"] <= a["prompt_tokens"]
    if exp == "m4":
        checks["trap_right_not_lower"] = b["right_trap"] >= a["right_trap"]
    if exp == "m3":
        lost = [[p[0].get("task"), p[0].get("rep")] for p in pairs
                if p[0].get("right") and not p[1].get("right") and (p[1].get("children") or {}).get("n")]
        checks["no_child_context_loss"] = not lost
    why = []
    if not pairs or len(pairs) < MIN_COVER * planned:
        why.append(f"{len(pairs)} of {planned} planned pairs finished (< {int(MIN_COVER * 100)}%)")
    if any(x["why"] == "switch did not take" for x in left_out):
        why.append("a unit's switch did not take")
    if exp == "m3":              # fork_turns only acts when the run spawns: pairs where neither did compare nothing
        idle = sum(not (p[0].get("children") or {}).get("n") and not (p[1].get("children") or {}).get("n")
                   for p in pairs)
        if pairs and idle * 2 > len(pairs):
            why.append(f"{idle} of {len(pairs)} pairs spawned no child in either arm")
    verdict = "Unknown" if why else ("Pass" if all(checks.values()) else "Fail")
    out = {"exp": exp, "baseline": base, "arm": arm, "pairs": len(pairs), "planned_pairs": planned,
           "verdict": verdict, "checks": checks, base: a, arm: b, "left_out": left_out}
    if why:
        out["unknown_because"] = why
    if exp == "m4":
        out["note"] = ("a piece spun off from a merged run climbs again from the low rung: one more chance than the "
                       "baseline's piece had")
    if exp == "m3":
        out["child_context_losses"] = lost
        out["pairs_without_children"] = idle
        out["arm_fork_none_of_spawns"] = [sum((p[1].get("children") or {}).get("fork_none_calls") or 0 for p in pairs),
                                          sum((p[1].get("children") or {}).get("spawn_calls") or 0 for p in pairs)]
    return out


def cmd_summary(a) -> int:
    rows = read_jsonl(Path(a.out) if a.out else RESULTS)
    if a.tag:
        rows = [r for r in rows if r.get("tag") == a.tag]
    exps = [x for x in (a.exp.split(",") if a.exp else EXPS) if any(r.get("exp") == x for r in rows)]
    print(json.dumps({x: rule(rows, x) for x in exps}, indent=1, ensure_ascii=False))
    return 0


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--exp", default="m4,m3,m5", help="comma-separated: m4, m3, m5")
    r.add_argument("--tag", default="b3arms")
    r.add_argument("--reps", type=int, default=0, help=f"repeats of every task x arm (default {REPS})")
    r.add_argument("--tasks", default="", help="comma-separated task / plan ids (default: all of the experiment)")
    r.add_argument("--limit", type=int, default=0, help="run at most this many units (0: all; an even number, so no pair is cut)")
    r.add_argument("--arms", default="", help="only these arms (a pre-run, under a tag of its own: the rule needs both arms of a pair run back to back)")
    r.add_argument("--budget", type=float, default=5.0, help="stop before a new unit once this tag's rows reach $")
    r.add_argument("--extra-spent", type=float, default=0.0)
    r.add_argument("--codex-home", default="", help="the dedicated eval CODEX_HOME (required to run)")
    r.add_argument("--timeout", type=int, default=1800)
    r.add_argument("--workdir", default="")
    r.add_argument("--out", default="")
    r.add_argument("--no-canary", action="store_true")
    r.add_argument("--force-unclean", action="store_true", help="run even when the preflight finds a problem")
    r.add_argument("--dry-run", action="store_true")
    r.set_defaults(fn=cmd_run)
    s = sub.add_parser("summary")
    s.add_argument("--exp", default="")
    s.add_argument("--tag", default="")
    s.add_argument("--out", default="")
    s.set_defaults(fn=cmd_summary)
    return ap


def main(argv=None) -> int:
    a = parser().parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
