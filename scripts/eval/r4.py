"""Round 4 (docs/research/2026-10-26-r4-plan.md): where do cheap models fail, and does ccx pay off in a LONG lead session?

Round 3 hit the ceiling twice over: the sonnet lead read the code and wrote the inference into its brief, so the cheap
sub-agent got a clear task. Round 4 asks the two questions round 3 could not:

  calib  no lead: each cheap model gets the person's raw, vague request (the round-3 tasks and round 2's compound
         tasks) straight from `ccx run`, with and without another vendor's cheap review; sonnet does the same as the
         reference. Which tasks do cheap models get wrong, and does the review rescue them?
           luna      Codex gpt-6-luna low, review off
           luna_rev  Codex gpt-6-luna low, review on (the cheapest reviewer from another vendor)
           haiku     Claude haiku low, review off
           flash     DeepSeek (dsh) deepseek-flash low, review off
           sonnet    headless Claude Code sonnet medium, no ccx (what the lead would do itself)
  long   a lead session that already holds a long conversation (it read ~100k tokens of project notes first), forked
         once per unit (`claude -p --resume <seed> --fork-session`); then self / builtin / ccx as in round 3. Every
         request of the lead re-reads that history, so this is where handing work away should save the lead.

Every unit gets a fresh throwaway hub (CCX_HUB, as round 3: Codex held to luna low, Claude to haiku for routing, A/B
self-runs off, the DeepSeek cap lifted but spend counted, quota probe off); every ccx run carries --no-ab and an
eval-r4 label. The hidden test decides.

  python scripts/eval/r4.py calib --rounds 2 --jobs 4 --budget 4
  python scripts/eval/r4.py long --rounds 1 --budget 6
  python scripts/eval/r4.py summary
  python scripts/eval/r4.py export docs/research/data/2026-10-26-r4.json

Results: .ccx/eval/r4/calib.jsonl and long.jsonl, one row per unit; running again skips finished units.
"""
from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import r2  # noqa: E402
import r3  # noqa: E402
import tasks_r2  # noqa: E402
import tasks_r3  # noqa: E402
from common import ROOT, append_jsonl, archive_hub, boot_ci, lead_env, make_repo, map_stopping, parse_stream, read_jsonl, run_tree, score, sign_test  # noqa: E402

from ccx.runners import bin_argv  # noqa: E402

OUT = ROOT / ".ccx" / "eval" / "r4"
R3_IDS = [t["id"] for t in tasks_r3.HARD]
R2_IDS = [t["id"] for t in tasks_r2.COMPOUND]
CALIB_TASKS = R3_IDS + R2_IDS
LONG_TASKS = R3_IDS
NO_EXTRAS = ["--context", "off", "--no-escalate", "--no-fallback"]
CALIB_ARMS = {
    "luna": ["--to", "codex", "--model", "gpt-6-luna", "--effort", "low", "--review", "off", *NO_EXTRAS],
    "luna_rev": ["--to", "codex", "--model", "gpt-6-luna", "--effort", "low", "--review", "on", *NO_EXTRAS],
    "haiku": ["--to", "claude", "--model", "haiku", "--effort", "low", "--review", "off", *NO_EXTRAS],
    "flash": ["--to", "dsh", "--model", "deepseek-flash", "--effort", "low", "--review", "off", *NO_EXTRAS],
    "sonnet": None,
}
LONG_ARMS = r3.ARMS
SONNET_PROMPT = """You are working on this repository (a small Python package; tests run with `python -m pytest -q`).
The person asked:

{brief}

Do the work yourself. When the work is done and the tests pass, end with one line: DONE: <what changed>."""
NOTES = [p for p in sorted((ROOT / "docs" / "research").glob("*.md")) if not p.name.endswith(".zh.md")] + \
        [ROOT / "docs" / n for n in ("DESIGN.md", "DECISIONS.md")]
SEED_PROMPT = """Before we touch any code today: read EVERY file under notes/ in full (use the Read tool on each one; they
are this project's design notes and earlier measurements). Then give me a summary in about 15 bullets: the decisions
that were made, what the measurements showed, and what is still open. Do not edit anything."""
_lock = threading.Lock()


def by_id(task_id: str) -> dict:
    return tasks_r3.by_id(task_id) if task_id in R3_IDS else tasks_r2.by_id(task_id)


def spent(f: Path) -> float:
    return round(sum(r.get("usd") or 0 for r in read_jsonl(f)), 4)


# ------------------------------------------------------------------ calib

def calib_unit(u: dict, a, work: Path) -> dict:
    task = by_id(u["task"])
    key = f"c{u['round']}-{u['task']}-{u['arm']}"
    repo, hub = work / key, work / f"h-{key}"
    for d in (repo, hub):
        r2._rmtree(d)
    make_repo(task, repo)
    if u["arm"] == "sonnet":
        t0 = time.time()
        argv = [*bin_argv("claude"), "-p", "--output-format", "stream-json", "--verbose", "--model", "sonnet",
                "--effort", "medium", "--tools", "Read,Grep,Glob,Edit,Write,Bash", "--permission-mode", "acceptEdits",
                "--allowed-tools", "Read Grep Glob Edit Write Bash", "--strict-mcp-config",
                "--exclude-dynamic-system-prompt-sections", "--disable-slash-commands", "--max-budget-usd", "0.8",
                "--no-session-persistence"]
        try:
            r = run_tree(argv, input=SONNET_PROMPT.format(brief=task["brief"]), cwd=repo, env=lead_env(), timeout=a.timeout)
            out, rc = r.stdout, r.returncode
        except subprocess.TimeoutExpired as e:
            out = e.stdout.decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
            rc = -9
        res = parse_stream(out)
        sc = score(repo, task)
        return {**u, "ok": sc["ok"], "pytest": sc["pytest"], "rc": rc, "wall_s": round(time.time() - t0, 1),
                "usd": round(float(res.get("cost_usd") or 0), 6), "tokens": res.get("context_tokens"),
                "requests": res.get("requests")}
    hinfo = r3.make_hub(hub)
    argv = ["run", "--mode", "write", "--new", "--no-ab", "--force", "--label", u["label"], "--minutes", "15",
            "--check", "python -m pytest -q", *CALIB_ARMS[u["arm"]], task["brief"]]
    res, rc, wall, err = r2.ccx(argv, repo, hub, a.timeout)
    sc = score(repo, task)
    cost = r2.hub_cost(hub)
    rid = res.get("run_id")
    rec = r2.record(hub, rid)
    row = {**u, "ok": sc["ok"], "pytest": sc["pytest"], "rc": rc, "wall_s": wall, "usd": cost["usd"],
           "review_usd": cost["review_usd"], "tokens": cost["tokens"], "agents": cost["agents"],
           "model": res.get("model"), "status": res.get("status"), "ccx_ok": res.get("ok"),
           "check": res.get("check"), "review": res.get("review"), "fix_round": bool(cost["n_runs"] > 2),
           "verdicts": [v.get("verdict") for v in (rec.get("first_review"), rec.get("review")) if v],
           "hub": hinfo, "stderr": err if rc else ""}
    for x in cost["run_ids"]:
        r2.verify(hub, x, bool(sc["ok"]), sc["pytest"])
    return row


def calib_schedule(rounds: int, seed: int, tasks: list[str], arms: list[str]) -> list[dict]:
    out = []
    for rd in range(1, rounds + 1):
        rnd = random.Random(f"{seed}:r4c:{rd}")
        ts = list(tasks)
        rnd.shuffle(ts)
        for t in ts:
            arm_list = list(arms)
            rnd.shuffle(arm_list)
            out += [{"exp": "calib", "round": rd, "task": t, "arm": arm} for arm in arm_list]
    return out


def cmd_calib(a) -> int:
    out = Path(a.out) if a.out else OUT / "calib.jsonl"
    work = Path(a.workdir or tempfile.mkdtemp(prefix="r4c-"))
    done = {(r["tag"], r["round"], r["task"], r["arm"]) for r in read_jsonl(out)}
    tasks = a.tasks.split(",") if a.tasks else CALIB_TASKS
    arms = a.arms.split(",") if a.arms else list(CALIB_ARMS)
    todo = []
    for u in calib_schedule(a.rounds, a.seed, tasks, arms):
        u = {**u, "tag": a.tag, "seed": a.seed, "label": f"eval-r4:{a.tag}:{u['round']}:{u['task']}:{u['arm']}"}
        if (a.tag, u["round"], u["task"], u["arm"]) not in done:
            todo.append(u)
    print(f"work dir: {work}  results: {out}  units: {len(todo)}", flush=True)
    if a.dry_run:
        for u in todo:
            print(f"[dry] {u['label']}")
        return 0
    stop = threading.Event()

    def one(u):
        if stop.is_set():
            return
        with _lock:
            if spent(out) >= a.budget:
                stop.set()
                print(f"budget ${a.budget} reached: stopping", flush=True)
                return
        try:
            row = calib_unit(u, a, work)
        except Exception as e:  # noqa: BLE001 — one broken unit is recorded, the batch goes on
            row = {**u, "ok": False, "error": f"{type(e).__name__}: {e}"[:400], "usd": 0.0, "wall_s": 0}
        row["ts"] = time.time()
        with _lock:
            append_jsonl(out, row)
            print(f"r{u['round']} {u['task']:12} {u['arm']:9} ok={row.get('ok')} ${row.get('usd', 0):.4f} "
                  f"{row.get('wall_s')}s total=${spent(out)}", flush=True)

    with ThreadPoolExecutor(max_workers=a.jobs) as ex:
        map_stopping(ex, one, todo)
    return 0


# ------------------------------------------------------------------ long

def lay_repo(task: dict, repo: Path) -> None:
    """The task's repo at a FIXED path (the seed session belongs to it), with the notes the seed read."""
    if repo.exists():
        for p in list(repo.iterdir()):
            r2._rmtree(p) if p.is_dir() else p.unlink()
    files = {**task["files"], **{f"notes/{p.name}": p.read_text(encoding="utf-8") for p in NOTES}}
    make_repo({**task, "files": files}, repo)


def seed_session(work: Path, a, arm: str = "self") -> dict:
    """A lead session that read the notes: every long unit forks one. The built-in arm gets its own seed started
    with its own flags (`--agents`, the Agent tool): those change the start of the prompt, so forking the plain seed
    missed the prompt cache entirely (the first pilot, §7), which a real long session with the Agent tool would not."""
    f = work / ("seed-builtin.json" if arm == "builtin" else "seed.json")
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    repo = work / "L"
    lay_repo(by_id(LONG_TASKS[0]), repo)
    sid = str(uuid.uuid4())
    if arm == "builtin":
        argv = [x for x in r3.lead_argv("builtin", 2) if x != "--no-session-persistence"] + ["--session-id", sid]
    else:
        argv = [*bin_argv("claude"), "-p", "--output-format", "stream-json", "--verbose", "--model", r3.LEAD_MODEL,
                "--effort", r3.LEAD_EFFORT, "--tools", "Read,Grep,Glob", "--allowed-tools", "Read Grep Glob",
                "--strict-mcp-config", "--exclude-dynamic-system-prompt-sections", "--disable-slash-commands",
                "--max-budget-usd", "2", "--session-id", sid]
    t0 = time.time()
    r = run_tree(argv, input=SEED_PROMPT, cwd=repo, env=lead_env(), timeout=a.timeout)
    res = parse_stream(r.stdout)
    info = {"session_id": sid, "usd": round(float(res.get("cost_usd") or 0), 6), "context_max": res.get("context_max"),
            "requests": res.get("requests"), "rc": r.returncode, "wall_s": round(time.time() - t0, 1),
            "notes": len(NOTES), "notes_chars": sum(len(p.read_text(encoding="utf-8")) for p in NOTES)}
    f.write_text(json.dumps(info), encoding="utf-8")
    return info


def long_unit(u: dict, a, work: Path, seed: dict) -> dict:
    task = by_id(u["task"])
    repo, hub = work / "L", work / f"h-l{u['round']}-{u['task']}-{u['arm']}"
    r2._rmtree(hub)
    lay_repo(task, repo)
    hinfo = r3.make_hub(hub)
    env = {**lead_env(), "CCX_HUB": str(hub), "CCX_NO_QUOTA_PROBE": "1", "BASH_DEFAULT_TIMEOUT_MS": "600000",
           "BASH_MAX_TIMEOUT_MS": "900000"}
    argv = [x for x in r3.lead_argv(u["arm"], a.lead_budget) if x != "--no-session-persistence"]
    argv += ["--resume", seed["session_id"], "--fork-session"]
    prompt = "New task, on this same repository (the notes are background only).\n\n" + \
        r3.lead_prompt(task, u["arm"], u["label"])
    t0 = time.time()
    try:
        r = run_tree(argv, input=prompt, cwd=repo, env=env, timeout=a.timeout)
        out, rc = r.stdout, r.returncode
    except subprocess.TimeoutExpired as e:
        out = e.stdout.decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        rc = -9
    wall = round(time.time() - t0, 1)
    (work / f"l{u['round']}-{u['task']}-{u['arm']}.stream.jsonl").write_text(out, encoding="utf-8")
    sc = score(repo, task)
    fin = r3.last_result(out)
    lm = r3.lead_metrics(out)
    cost = r2.hub_cost(hub)
    by_model = r3.model_split(fin.get("modelUsage") or {})
    lead_usd = float(fin.get("total_cost_usd") or 0)
    row = {**u, "ok": sc["ok"], "pytest": sc["pytest"], "rc": rc, "wall_s": wall, "lead_usd": round(lead_usd, 6),
           "by_model_usd": by_model, "ccx_usd": cost["usd"], "ccx_review_usd": cost["review_usd"],
           "ccx_agents": cost["agents"], "usd": round(lead_usd + cost["usd"], 6), "hub": hinfo, **lm}
    row["sub_usd"] = round(sum(v for m, v in by_model.items() if r3.WORKER_MODEL in m), 6) if u["arm"] == "builtin" \
        else cost["usd"]
    row["lead_only_usd"] = round(row["usd"] - row["sub_usd"], 6)
    row["delegated"] = bool(lm["agent_calls"]) if u["arm"] == "builtin" else bool(lm["ccx_runs"]) \
        if u["arm"] == "ccx" else None
    row["rework"] = max(0, lm["agent_calls"] - 1) if u["arm"] == "builtin" else \
        (lm["ccx_resumes"] + max(0, lm["ccx_runs"] - 1)) if u["arm"] == "ccx" else 0
    if u["arm"] == "ccx":
        row["context_attached"] = sum((hub / "ccx" / "runs" / str(rid) / "shared-context.md").exists()
                                      for rid in cost["run_ids"])
        row["archived_sessions"] = archive_hub(hub)
    for rid in cost["run_ids"]:
        r2.verify(hub, rid, bool(sc["ok"]), sc["pytest"])
    return row


def cmd_long(a) -> int:
    out = Path(a.out) if a.out else OUT / "long.jsonl"
    work = Path(a.workdir or (Path(tempfile.gettempdir()) / "r4l"))
    work.mkdir(parents=True, exist_ok=True)
    done = {(r["tag"], r["round"], r["task"], r["arm"]) for r in read_jsonl(out)}
    tasks = a.tasks.split(",") if a.tasks else LONG_TASKS
    arms = a.arms.split(",") if a.arms else list(LONG_ARMS)
    todo = []
    for rd in range(1, a.rounds + 1):
        rnd = random.Random(f"{a.seed}:r4l:{rd}")
        ts = list(tasks)
        rnd.shuffle(ts)
        for t in ts:
            arm_list = list(arms)
            rnd.shuffle(arm_list)
            for arm in arm_list:
                u = {"exp": "long", "round": rd, "task": t, "arm": arm, "tag": a.tag, "seed": a.seed,
                     "label": f"eval-r4:{a.tag}:L{rd}:{t}:{arm}"}
                if (a.tag, rd, t, arm) not in done:
                    todo.append(u)
    print(f"work dir: {work}  results: {out}  units: {len(todo)}", flush=True)
    if a.dry_run:
        for u in todo:
            print(f"[dry] {u['label']}")
        return 0
    seeds = {arm: seed_session(work, a, arm) for arm in sorted(set(arms), key=lambda x: x != "self")}
    seeds_usd = sum({s["session_id"]: s.get("usd", 0) for s in seeds.values()}.values()) + a.extra_spent
    print(f"seeds: {json.dumps(seeds)}", flush=True)
    for u in todo:
        seed = seeds[u["arm"]]
        total = spent(out) + seeds_usd
        if total >= a.budget:
            print(f"budget ${a.budget} reached (${total:.3f}): stopping", flush=True)
            return 2
        try:
            row = long_unit(u, a, work, seed)
        except Exception as e:  # noqa: BLE001
            row = {**u, "ok": False, "error": f"{type(e).__name__}: {e}"[:400], "usd": 0.0, "wall_s": 0}
        row["ts"] = time.time()
        append_jsonl(out, row)
        print(f"L{u['round']} {u['task']:12} {u['arm']:8} ok={row.get('ok')} ${row.get('usd', 0):.4f} "
              f"(lead ${row.get('lead_only_usd', 0):.4f}) lead_tok={row.get('lead_tokens')} {row.get('wall_s')}s "
              f"deleg={row.get('delegated')} total=${spent(out) + seeds_usd:.3f}", flush=True)
    return 0


# ------------------------------------------------------------------ summary

def _rate(rows):
    n = len(rows)
    return {"ok": sum(bool(r.get("ok")) for r in rows), "n": n, "usd": round(sum(r.get("usd") or 0 for r in rows), 4)}


def summarize_calib(rows: list[dict]) -> dict:
    rows = [r for r in rows if "error" not in r]
    arms = sorted({r["arm"] for r in rows})
    by_arm = {arm: _rate([r for r in rows if r["arm"] == arm]) for arm in arms}
    by_task = {}
    for t in sorted({r["task"] for r in rows}):
        by_task[t] = {arm: "%d/%d" % (sum(bool(r.get("ok")) for r in rows if r["task"] == t and r["arm"] == arm),
                                      sum(1 for r in rows if r["task"] == t and r["arm"] == arm)) for arm in arms}
    # does the review rescue luna? pairs = same task, same round
    idx = {(r["task"], r["round"], r["arm"]): r for r in rows}
    b = c = 0
    for (t, rd, arm), r in idx.items():
        if arm == "luna" and (t, rd, "luna_rev") in idx:
            x, y = bool(r.get("ok")), bool(idx[(t, rd, "luna_rev")].get("ok"))
            b += (not x) and y
            c += x and not y
    from math import comb
    n = b + c
    p = min(1.0, 2 * sum(comb(n, k) for k in range(0, min(b, c) + 1)) / 2 ** n) if n else None
    return {"by_arm": by_arm, "by_task": by_task, "luna_to_luna_rev_discordant": [b, c], "mcnemar_p": p,
            "errors": len([r for r in read_jsonl(OUT / "calib.jsonl") if "error" in r])}


def summarize_long(rows: list[dict]) -> dict:
    rows = [r for r in rows if "error" not in r]
    out = {}
    for arm in LONG_ARMS:
        rs = [r for r in rows if r["arm"] == arm]
        if not rs:
            continue
        med = lambda k: sorted(r.get(k) or 0 for r in rs)[len(rs) // 2]  # noqa: E731
        out[arm] = {**_rate(rs), "cps": round(sum(r.get("usd") or 0 for r in rs) / max(1, sum(bool(r.get("ok"))
                    for r in rs)), 4), "lead_only_usd_med": med("lead_only_usd"), "lead_tokens_med": med("lead_tokens"),
                    "wall_med": med("wall_s"), "delegated": sum(bool(r.get("delegated")) for r in rs)}
    pairs = {}
    for A, B in (("self", "ccx"), ("builtin", "ccx"), ("self", "builtin")):
        diffs = {"usd": [], "lead_tokens": [], "wall_s": []}
        for t in {r["task"] for r in rows}:
            ra = [r for r in rows if r["task"] == t and r["arm"] == A]
            rb = [r for r in rows if r["task"] == t and r["arm"] == B]
            if ra and rb:
                for k in diffs:
                    diffs[k].append(sum(r.get(k) or 0 for r in rb) / len(rb) - sum(r.get(k) or 0 for r in ra) / len(ra))
        pairs[f"{A}->{B}"] = {k: {"median": round(sorted(v)[len(v) // 2], 5) if v else None,
                                  "ci": boot_ci(v) if len(v) > 2 else None, "sign_p": sign_test(v)}
                              for k, v in diffs.items()}
    return {"arms": out, "paired": pairs}


def cmd_summary(a) -> int:
    print(json.dumps({"calib": summarize_calib(read_jsonl(OUT / "calib.jsonl")),
                      "long": summarize_long(read_jsonl(OUT / "long.jsonl"))}, ensure_ascii=False, indent=1))
    return 0


def cmd_export(a) -> int:
    keep = ("tag", "exp", "round", "task", "arm", "ok", "pytest", "rc", "wall_s", "usd", "review_usd", "tokens",
            "agents", "model", "status", "check", "fix_round", "verdicts", "lead_usd", "lead_only_usd", "sub_usd",
            "by_model_usd", "ccx_usd", "lead_requests", "lead_tokens", "lead_output_tokens", "lead_tools",
            "agent_calls", "ccx_runs", "ccx_resumes", "rework", "delegated", "context_attached", "error")
    calib, long = read_jsonl(OUT / "calib.jsonl"), read_jsonl(OUT / "long.jsonl")
    seed = {}
    for d in [Path(a.long_workdir)] if a.long_workdir else []:
        f = d / "seed.json"
        if f.exists():
            seed = {k: v for k, v in json.loads(f.read_text(encoding="utf-8")).items() if k != "session_id"}
    data = {"summary": {"calib": summarize_calib(calib), "long": summarize_long(long), "seed": seed},
            "rows": [r3.scrub({k: r[k] for k in keep if k in r}) for r in calib + long]}
    Path(a.dest).write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {a.dest}: {len(calib)} calib + {len(long)} long rows")
    return 0


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn, budget in (("calib", cmd_calib, 4.0), ("long", cmd_long, 6.0)):
        r = sub.add_parser(name)
        r.add_argument("--tag", default="r4")
        r.add_argument("--seed", type=int, default=41)
        r.add_argument("--rounds", type=int, default=2 if name == "calib" else 1)
        r.add_argument("--tasks", default="")
        r.add_argument("--arms", default="")
        r.add_argument("--budget", type=float, default=budget, help="stop before a new unit once this file reaches $")
        r.add_argument("--lead-budget", type=float, default=1.5, help="claude -p --max-budget-usd for one lead")
        r.add_argument("--jobs", type=int, default=4)
        r.add_argument("--extra-spent", type=float, default=0.0,
                       help="long: spend outside the results file that counts toward --budget (dropped pilot units)")
        r.add_argument("--out", default="")
        r.add_argument("--workdir", default="")
        r.add_argument("--timeout", type=int, default=1200)
        r.add_argument("--dry-run", action="store_true")
        r.set_defaults(fn=fn)
    s = sub.add_parser("summary")
    s.set_defaults(fn=cmd_summary)
    e = sub.add_parser("export")
    e.add_argument("dest")
    e.add_argument("--long-workdir", default="")
    e.set_defaults(fn=cmd_export)
    return ap


def main(argv=None) -> int:
    a = parser().parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
