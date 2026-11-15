"""Seven cores, round 2 (docs/research/2026-10-26-seven-cores-r2-plan.md): does dividing the work beat one model,
and is it cheaper? Every unit runs in its own throwaway hub (CCX_HUB) with Codex held to gpt-6-luna, A/B self-runs
off, the DeepSeek cap lifted (spend still counted) and Claude's quota probe off; every ccx run carries --no-ab and an
eval-r2 label. A hidden acceptance test the agents never see decides right or wrong and is recorded with ccx verify.

  groups (in priority order)
  way      4-A  `ccx way` smoke: risk visible and critical, 3 each; plan items, acceptance verdict, PICK parsed
  screen        one cheap single run (luna low) per trap task, twice: which tasks the cheap model gets wrong
  review   4-C  luna low with --review off / on / auto (the new defaults: cheapest reviewer, item by item, weak
                evidence reviewed automatically)
  coop     4-B  single (luna low alone) / way (claude plans, codex builds, the planner accepts) / draft (claude
                drafts the plan, codex luna low checks the draft, then codex builds)
  par      scale + 4-H  ten independent modules: one run (p1), 3 and 10 runs in parallel worktrees (ccx batch),
                one run told to use its own sub-agents (native); the same pair on claude haiku (c_off / c_on)
  route    (b') fixed claude sonnet / auto routing from a copy of the person's routing state (warm) / from nothing
                (cold)
  tiers    4-D  `ccx route` (no model call) at 5 / 15 / 30 minutes, warm and cold
  learn         the route tasks twice in ONE hub that keeps learning (phase1, phase2); the frozen arm is route:warm
  func     F11 (Claude sub-agents over a tiny --budget) and 4-I (a queue with dependencies killed mid-way, q resume)

  python scripts/eval/r2.py run --groups way --budget 6
  python scripts/eval/r2.py summary [--groups coop]
  python scripts/eval/r2.py spend

Results go to .ccx/eval/r2/results.jsonl, one row per unit as soon as it ends; `run` again skips finished units.
Needs logged-in `claude` and `codex` CLIs and DEEPSEEK_API_KEY for routed runs; tests never call this with real ones.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import seven_ab as S  # noqa: E402
from common import HIDDEN, ROOT, append_jsonl, ccx_verify, git, lead_env, make_repo, read_jsonl, run_tree, score  # noqa: E402
from tasks_r2 import COMPOUND, PAR10, PIECES, QUEUE, TRAPS, TRAPS2, by_id, piece_brief  # noqa: E402

from ccx import ledger  # noqa: E402
from ccx.config import Paths  # noqa: E402
from ccx.ways import BUILD, PLAN  # noqa: E402

OUT = ROOT / ".ccx" / "eval" / "r2"
ACCEPT = "python -m pytest -q"
LUNA = ["--to", "codex", "--model", "gpt-6-luna", "--effort", "low"]
CODEX_HELD_BACK = ("gpt-6.1-sol", "gpt-6-astra")      # routing may still pick gpt-6-luna:high; reported if it does
HUB_TOML = """# eval-r2 throwaway hub
[defaults]
ab_self_rate = 0.0
max_parallel = 10
[tiers.T2]
codex = { model = "gpt-6-luna", effort = "low" }
[tiers.T3]
codex = { model = "gpt-6-luna", effort = "low" }
[tiers.T4]
codex = { model = "gpt-6-luna", effort = "low" }
[providers.deepseek]
daily_usd = 1000.0
[providers.deepseek-codex]
daily_usd = 1000.0
[pay_per_token.dsh]
daily_usd = 1000.0
"""
SMALL = ["slugify", "duration", "intervals", "cli-json"]
TRAP_IDS = [t["id"] for t in TRAPS]           # first screen: 19/20 right, too easy (kept as review controls)
TRAP2_IDS = [t["id"] for t in TRAPS2]
COMP_IDS = [t["id"] for t in COMPOUND][1:]    # inventory is already in TRAPS2
EASY = ["merge", "version", "ini"]
ROUTE_TASKS = SMALL + ["csvstats", "lru"] + TRAP2_IDS[:6]     # 12: inventory, dupparse, cache, rounding, exporter, tags
MINUTES = {**{t: 5 for t in SMALL}, **{t: 15 for t in ["csvstats", "lru", *TRAP_IDS, *TRAP2_IDS, *COMP_IDS]}}
DRAFT_REVIEW = """[eval draft review] A lead wrote the plan below before handing the task to a builder. Check the plan
against EVERY requirement in the task: is one missing, misread or contradicted? Do not edit anything.

## Task
{task}

## The lead's plan
{plan}

## Answer
summary: `ok` or one sentence. open_questions: `[must] ...` for each requirement the plan misses or gets wrong,
`[note] ...` for anything else worth telling the builder (at most 5 items in all). Status done."""

GROUPS = {
    "way": {"arms": ("visible", "critical"), "tasks": ["inventory", "cart", "merge"], "rounds": 1},
    "screen": {"arms": ("single",), "tasks": TRAP_IDS, "rounds": 2},
    "screen2": {"arms": ("single",), "tasks": TRAP2_IDS, "rounds": 2},
    "screen3": {"arms": ("single",), "tasks": COMP_IDS, "rounds": 2},
    "review": {"arms": ("off", "on", "auto"), "tasks": TRAP2_IDS + EASY, "rounds": 3},
    "coop": {"arms": ("single", "way", "draft"), "tasks": TRAP2_IDS, "rounds": 2},
    "par": {"arms": ("p1", "p3", "p10", "native", "c_off", "c_on"), "tasks": ["par10"], "rounds": 2},
    "route": {"arms": ("fixed", "warm", "cold"), "tasks": ROUTE_TASKS, "rounds": 1},
    "learn": {"arms": ("phase1", "phase2"), "tasks": ROUTE_TASKS, "rounds": 1},
    "func": {"arms": ("f11", "queue"), "tasks": ["par10"], "rounds": 1},
}


# ------------------------------------------------------------------ hubs and ccx

def sha(f: Path) -> str | None:
    return hashlib.sha256(f.read_bytes()).hexdigest() if f.exists() else None


def default_state() -> Path:
    """The person's routing state (their default hub, ignoring any CCX_HUB of this shell). Only ever copied."""
    old = os.environ.pop("CCX_HUB", None)
    try:
        from ccx.config import hub_dir
        return hub_dir() / "ccx" / "routing-state.json"
    finally:
        if old is not None:
            os.environ["CCX_HUB"] = old


def env_for(hub: Path) -> dict:
    return {**lead_env(), "CCX_HUB": str(hub), "CCX_NO_QUOTA_PROBE": "1"}


def make_hub(d: Path, state: Path | None = None) -> dict:
    """A throwaway hub: overrides, optionally a copy of a routing state, Codex models other than luna held back."""
    if d.exists():
        shutil.rmtree(d)
    (d / "ccx").mkdir(parents=True)
    (d / "ccx" / "tiers.toml").write_text(HUB_TOML, encoding="utf-8")
    info: dict = {"warm": bool(state)}
    st = d / "ccx" / "routing-state.json"
    if state:
        shutil.copy2(state, st)
        info["state_sha256"] = sha(st)
    code = ("from ccx import learn\nfrom ccx.config import paths\n"
            f"for m in {CODEX_HELD_BACK!r}:\n    learn.mark_unavailable(paths(), 'codex', m)\n")
    r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env_for(d), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode:
        raise RuntimeError(f"holding back Codex models failed: {r.stderr[-300:]}")
    info["state_sha256_marked"] = sha(st)
    return info


def ccx(args: list[str], cwd: Path, hub: Path, timeout: int) -> tuple[dict, int, float, str]:
    t0 = time.time()
    try:
        r = run_tree([sys.executable, str(ROOT / "ccx.py"), *args], cwd=cwd, env=env_for(hub), timeout=timeout)
        out, rc, err = r.stdout, r.returncode, r.stderr
    except subprocess.TimeoutExpired:
        out, rc, err = "", -9, "timeout"
    return S._last_json(out), rc, round(time.time() - t0, 1), (err or "")[-400:]


def _tok(u: dict | None) -> int:
    u = u or {}
    return int(u.get("input", 0) or 0) + int(u.get("cached", 0) or 0) + int(u.get("output", 0) or 0)


def hub_cost(hub: Path, labels: set[str] | None = None) -> dict:
    """What the runs in this hub spent (or only the runs under these labels and their reviews)."""
    rows = [r for r in ledger.rows(Paths(hub)) if not r.get("type")]
    if labels is not None:
        ids = {r["run_id"] for r in rows if r.get("label") in labels}
        rows = [r for r in rows if r.get("run_id") in ids or str(r.get("label") or "").split(":", 1)[-1] in ids]
    return {"usd": round(sum(r.get("ae_usd") or 0 for r in rows), 6), "tokens": sum(_tok(r.get("usage")) for r in rows),
            "run_ids": [r["run_id"] for r in rows], "n_runs": len(rows),
            "rungs": [g for r in rows for g in (r.get("rungs") or [])],
            "agents": sorted({str(r.get("provider") or r.get("to")) for r in rows}),
            "review_usd": round(sum(r.get("ae_usd") or 0 for r in rows
                                    if str(r.get("label") or "").startswith("review:")), 6)}


def record(hub: Path, run_id: str | None) -> dict:
    f = hub / "ccx" / "runs" / str(run_id) / "run.json"
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def children(hub: Path, run_ids: list[str]) -> int:
    """How many of its own sub-agents the runs started (Codex child sessions, Claude subagents/*.jsonl)."""
    from ccx import subagents
    from ccx.usage import codex_children
    n = 0
    for rid in run_ids:
        rec = record(hub, rid)
        sid = rec.get("session_id")
        if not sid:
            continue
        try:
            if rec.get("to") == "codex":
                n += len(codex_children(sid, 0))
            elif rec.get("to") == "claude":
                n += len(subagents.claude_children(sid, Path(rec.get("cwd") or ".")))
        except Exception:  # noqa: BLE001 — a count we cannot read is reported as unknown by the caller
            return -1
    return n


def verify(hub: Path, run_id: str | None, ok: bool, note: str) -> str:
    return ccx_verify(run_id, ok, f"eval-r2 hidden acceptance: {note}", hub=hub) if run_id else ""


# ------------------------------------------------------------------ units

def _rmtree(d: Path) -> None:
    """Remove a leftover folder of an interrupted unit (git's object files are read-only on Windows)."""
    def onerror(fn, path, _exc):
        os.chmod(path, 0o700)
        fn(path)
    if d.exists():
        shutil.rmtree(d, onerror=onerror)


def _paths(u: dict, work: Path, clean: bool = True) -> tuple[Path, Path]:
    key = f"{u['exp']}-{u['round']}-{u['task']}-{u['arm']}"
    for d in (work / key, work / f"hub-{key}") if clean else ():
        _rmtree(d)
    return work / key, work / f"hub-{key}"


def direct(u: dict, a, work: Path, pick: list[str], brief: str | None = None, state: Path | None = None,
           check: str | None = ACCEPT, extra: list[str] | None = None) -> dict:
    """One `ccx run` on a fresh repo in a fresh hub."""
    task = by_id(u["task"])
    repo, hub = _paths(u, work)
    make_repo(task, repo)
    hinfo = make_hub(hub, state)
    argv = ["run", "--mode", "write", "--new", "--no-ab", "--force", "--label", u["label"],
            "--minutes", str(MINUTES.get(u["task"], 15)), *(["--check", check] if check else []), *pick,
            *(extra or []), brief or task["brief"]]
    res, rc, wall, err = ccx(argv, repo, hub, a.timeout)
    sc = score(repo, task) if task.get("hidden") else {"ok": None, "pytest": ""}
    rid = res.get("run_id")
    rec = record(hub, rid)
    row = {**u, "wall_s": wall, "rc": rc, "ok": sc["ok"], "pytest": sc["pytest"], "ccx_ok": res.get("ok"),
           "status": res.get("status"), "kind": res.get("kind"), "model": res.get("model"), "agent": res.get("agent"),
           "escalated": res.get("escalated"), "check": res.get("check"), "review": res.get("review"),
           "route_p": (rec.get("route") or {}).get("p"), "route_rung": (rec.get("route") or {}).get("rung"),
           "hub": hinfo, "stderr": err if rc else "", **hub_cost(hub)}
    row["verify"] = verify(hub, rid, bool(sc["ok"]), sc["pytest"]) if sc["ok"] is not None else ""
    return row


def way_unit(u: dict, a, work: Path, risk: str) -> dict:
    task = by_id(u["task"])
    repo, hub = _paths(u, work)
    make_repo(task, repo)
    hinfo = make_hub(hub)
    bf = work / f"{repo.name}.brief.md"
    bf.write_text(task["brief"], encoding="utf-8")
    argv = ["way", "--risk", risk, "--with", "codex,claude", "--check", ACCEPT, "--from", "user", "--label",
            u["label"], "--brief-file", str(bf), *(["--yes"] if risk == "critical" else [])]
    out, rc, wall, err = ccx(argv, repo, hub, a.timeout * 3)
    items = [str(x) for x in ((out.get("plan") or {}).get("items") or [])]
    row = {**u, "wall_s": wall, "rc": rc, "state": out.get("state"), "way": out.get("way"), "roles": out.get("roles"),
           "steps": [{k: s.get(k) for k in ("step", "agent", "ok", "status", "usd")} for s in out.get("steps") or []],
           "plan_steps": sum(x.lower().startswith("[step]") for x in items),
           "plan_accepts": sum(x.lower().startswith("[accept]") for x in items),
           "plan_other": sum(not x.lower().startswith(("[step]", "[accept]")) for x in items),
           "acceptance": {k: (out.get("acceptance") or {}).get(k) for k in ("verdict", "round", "issues")},
           "pick": out.get("pick"), "hub": hinfo, "stderr": err if rc else "", **hub_cost(hub)}
    if risk == "critical":
        oks = {}
        for slot, v in (out.get("versions") or {}).items():
            wt = Path(v.get("worktree") or "")
            oks[slot] = score(wt, task)["ok"] if wt.is_dir() else None
        slot = (out.get("pick") or {}).get("slot")
        row.update(version_ok=oks, ok=bool(slot and oks.get(slot)),
                   pick_right=None if len({x for x in oks.values() if x is not None}) < 2 else bool(slot and oks.get(slot)))
        for slot, v in (out.get("versions") or {}).items():
            verify(hub, v.get("run_id"), bool(oks.get(slot)), f"version {slot}")
    else:
        sc = score(repo, task)
        row.update(ok=sc["ok"], pytest=sc["pytest"])
        verify(hub, out.get("run_id"), sc["ok"], sc["pytest"])
    row["rework"] = sum(s["step"] == "fix" for s in row["steps"])
    return row


def draft_unit(u: dict, a, work: Path) -> dict:
    """The lead drafts the plan (claude sonnet, read-only), codex luna low checks the draft, codex luna low builds."""
    task = by_id(u["task"])
    repo, hub = _paths(u, work)
    make_repo(task, repo)
    hinfo = make_hub(hub)
    m = str(MINUTES.get(u["task"], 15))
    base = ["run", "--new", "--no-ab", "--force", "--review", "off", "--no-escalate", "--no-fallback", "--minutes", m]
    wid = u["label"].replace(":", "-")
    plan, _, w1, _ = ccx([*base, "--mode", "read", "--to", "claude", "--model", "sonnet", "--effort", "medium",
                          "--label", f"{u['label']}:draft", PLAN.format(wid=wid, task=task["brief"])], repo, hub,
                         a.timeout)
    items = [str(x) for x in plan.get("open_questions") or []]
    plan_text = (plan.get("summary") or "") + "\n" + "\n".join(f"- {x}" for x in items)
    rev, _, w2, _ = ccx([*base, "--mode", "read", *LUNA, "--label", f"{u['label']}:draftreview",
                         DRAFT_REVIEW.format(task=task["brief"], plan=plan_text)], repo, hub, a.timeout)
    notes = [str(x) for x in rev.get("open_questions") or []]
    brief = BUILD.format(task=task["brief"], planner="claude", plan=plan_text)
    if notes:
        brief += "\n\n## A second agent checked this plan against the task\n" + "\n".join(f"- {x}" for x in notes)
    res, rc, w3, err = ccx([*base[:4], "--review", "off", "--no-escalate", "--minutes", m, "--mode", "write",
                            "--check", ACCEPT, *LUNA, "--label", u["label"], brief], repo, hub, a.timeout)
    sc = score(repo, task)
    verify(hub, res.get("run_id"), sc["ok"], sc["pytest"])
    return {**u, "wall_s": round(w1 + w2 + w3, 1), "rc": rc, "ok": sc["ok"], "pytest": sc["pytest"],
            "ccx_ok": res.get("ok"), "check": res.get("check"), "plan_ok": plan.get("status") == "done",
            "plan_items": len(items), "draft_review": {"summary": str(rev.get("summary") or "")[:300],
                                                       "must": sum(x.lower().startswith("[must]") for x in notes),
                                                       "notes": len(notes)},
            "escalated": res.get("escalated"), "hub": hinfo, "stderr": err if rc else "", "rework": 0,
            **hub_cost(hub)}


def score_pieces(repo: Path) -> dict:
    f = repo / HIDDEN
    f.write_text(PAR10["hidden"], encoding="utf-8")
    try:
        r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-rA", "-p", "no:cacheprovider", HIDDEN], cwd=repo,
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    finally:
        f.unlink(missing_ok=True)
    passed = set(re.findall(r"PASSED \S+::test_(m\d\d)", r.stdout))
    return {"pieces_ok": sorted(passed), "n_ok": len(passed),
            "tests_written": sum((repo / "tests" / f"test_{p['id']}.py").exists() for p in PIECES)}


def batch_unit(u: dict, a, work: Path, n: int) -> dict:
    """The ten pieces as n runs side by side (ccx batch: one worktree each), then merged back one by one."""
    repo, hub = _paths(u, work)
    make_repo(PAR10, repo)
    hinfo = make_hub(hub)
    groups = [PIECES[i::n] for i in range(n)]
    plan = {"tasks": [{"id": f"{u['label']}:{k}", "brief": piece_brief(g), "to": "codex", "model": "gpt-6-luna",
                       "effort": "low", "mode": "write", "check": ACCEPT, "cwd": str(repo), "minutes": 5}
                      for k, g in enumerate(groups)]}
    pf = work / f"{repo.name}.plan.json"
    pf.write_text(json.dumps(plan), encoding="utf-8")
    out, rc, wall, err = ccx(["batch", str(pf), "--from", "user"], repo, hub, a.timeout * 2)
    conflicts, merged = 0, 0
    t0 = time.time()
    for res in out.get("results") or []:
        wt = res.get("worktree")
        if not wt or not Path(wt).is_dir():
            continue
        git(Path(wt), "add", "-A")
        git(Path(wt), "commit", "-q", "-m", f"piece {res.get('run_id')}")
        m = subprocess.run(["git", "-c", "user.name=eval", "-c", "user.email=eval@example.invalid", "merge",
                            "--no-edit", f"ccx/{res.get('run_id')}"], cwd=repo, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        if m.returncode:
            conflicts += 1
            git(repo, "merge", "--abort")
        else:
            merged += 1
    sp = score_pieces(repo)
    for res in out.get("results") or []:
        verify(hub, res.get("run_id"), bool(res.get("ok")) and not conflicts, "batch piece (see pieces_ok)")
    return {**u, "wall_s": wall, "merge_s": round(time.time() - t0, 1), "rc": rc, "n_runs_planned": n,
            "ok": sp["n_ok"] == 10, **sp, "conflicts": conflicts, "merged": merged,
            "ccx_ok": [r.get("ok") for r in out.get("results") or []],
            "escalated": [r.get("escalated") for r in out.get("results") or [] if r.get("escalated")],
            "do_yourself": out.get("do_yourself"), "hub": hinfo, "stderr": err if rc else "", **hub_cost(hub)}


def single_par(u: dict, a, work: Path, pick: list[str], flags: list[str]) -> dict:
    row = direct(u, a, work, pick, brief=PAR10["brief"], extra=flags)
    repo, hub = _paths(u, work, clean=False)
    sp = score_pieces(repo)
    row.update(**sp, ok=sp["n_ok"] == 10, conflicts=0, children=children(hub, row["run_ids"]))
    return row


def queue_unit(u: dict, a, work: Path) -> dict:
    """4-I: four queue items (b needs a, c needs b), `ccx q run` killed once one item is done, then `ccx q resume`."""
    repo, hub = _paths(u, work)
    make_repo(QUEUE, repo)
    hinfo = make_hub(hub)
    pf = work / "queue-plan.json"
    pf.write_text(json.dumps({"tasks": [{**it, "title": it["id"], "to": "claude", "minutes": 5} for it in QUEUE["items"]]}),
                  encoding="utf-8")
    added, _, _, _ = ccx(["q", "--cwd", str(repo), "add", "--plan", str(pf)], repo, hub, 120)
    env = env_for(hub)
    t0 = time.time()
    proc = subprocess.Popen([sys.executable, str(ROOT / "ccx.py"), "q", "--cwd", str(repo), "run", "--max", "2",
                             "--from", "user"], cwd=repo, env=env, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    killed_at, states = None, {}
    while proc.poll() is None and time.time() - t0 < a.timeout:
        time.sleep(3)
        ls, _, _, _ = ccx(["q", "--cwd", str(repo), "ls", "--long"], repo, hub, 60)
        items = ls.get("items") if isinstance(ls, dict) else ls
        states = {str(i.get("title")): i.get("status") for i in (items or []) if isinstance(i, dict)}
        if any(s == "done" for s in states.values()) and any(s != "done" for s in states.values()):
            killed_at = round(time.time() - t0, 1)
            if os.name == "nt":
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
            else:
                proc.kill()
            break
    proc.wait(timeout=60)
    before = dict(states)
    res, rc, wall, err = ccx(["q", "--cwd", str(repo), "resume", "--from", "user"], repo, hub, a.timeout)
    ls, _, _, _ = ccx(["q", "--cwd", str(repo), "ls", "--long"], repo, hub, 60)
    items = ls.get("items") if isinstance(ls, dict) else ls
    sc = score(repo, QUEUE)
    cost = hub_cost(hub)
    per_item: dict = {}
    for r in ledger.rows(Paths(hub)):
        if not r.get("type"):
            per_item[str(r.get("label"))] = per_item.get(str(r.get("label")), 0) + 1
    return {**u, "added": bool(added), "killed_at_s": killed_at, "states_at_kill": before,
            "states_after": {str(i.get("title")): i.get("status") for i in (items or []) if isinstance(i, dict)},
            "runs_per_label": per_item, "ok": sc["ok"], "pytest": sc["pytest"], "rc": rc,
            "wall_s": round(time.time() - t0, 1), "hub": hinfo, "stderr": err if rc else "", **cost}


def run_unit(u: dict, a, work: Path) -> dict:
    exp, arm = u["exp"], u["arm"]
    if exp == "way":
        return way_unit(u, a, work, arm)
    if exp.startswith("screen") or (exp in ("review", "coop") and arm in ("off", "single")):
        return direct(u, a, work, [*LUNA, "--no-escalate", "--review", "off"])
    if exp == "review":
        return direct(u, a, work, [*LUNA, "--no-escalate", "--review", arm])
    if exp == "coop":
        return way_unit(u, a, work, "visible") if arm == "way" else draft_unit(u, a, work)
    if exp == "par":
        if arm in ("p3", "p10"):
            return batch_unit(u, a, work, int(arm[1:]))
        pick = LUNA if arm in ("p1", "native") else ["--to", "claude", "--model", "haiku", "--effort", "low"]
        return single_par(u, a, work, pick, ["--parallel"] if arm in ("native", "c_on") else ["--no-subagents"])
    if exp == "route":
        if arm == "fixed":
            return direct(u, a, work, ["--to", "claude", "--model", "sonnet", "--effort", "medium", "--no-escalate",
                                       "--review", "off"])
        return direct(u, a, work, ["--to", "auto", "--review", "off"], state=a.state if arm == "warm" else None)
    if exp == "learn":
        return learn_unit(u, a, work)
    if exp == "func":
        if arm == "f11":
            row = single_par(u, a, work, ["--to", "claude", "--model", "sonnet", "--effort", "medium"],
                             ["--parallel", "--budget", "0.0001", "--no-escalate"])
            return row
        return queue_unit(u, a, work)
    raise ValueError(exp)


def learn_unit(u: dict, a, work: Path) -> dict:
    """One routed run in the shared learning hub (created on the first unit from the same state copy as route:warm)."""
    task = by_id(u["task"])
    hub = work / "hub-learn"
    info_f = work / "hub-learn.json"
    if not info_f.exists():
        info_f.write_text(json.dumps(make_hub(hub, a.state)), encoding="utf-8")
    repo = work / f"learn-{u['arm']}-{u['task']}"
    make_repo(task, repo)
    before = sha(hub / "ccx" / "routing-state.json")
    argv = ["run", "--mode", "write", "--new", "--no-ab", "--force", "--label", u["label"], "--minutes",
            str(MINUTES.get(u["task"], 15)), "--check", ACCEPT, "--to", "auto", "--review", "off", task["brief"]]
    res, rc, wall, err = ccx(argv, repo, hub, a.timeout)
    sc = score(repo, task)
    rec = record(hub, res.get("run_id"))
    v = verify(hub, res.get("run_id"), sc["ok"], sc["pytest"])
    return {**u, "wall_s": wall, "rc": rc, "ok": sc["ok"], "pytest": sc["pytest"], "ccx_ok": res.get("ok"),
            "model": res.get("model"), "agent": res.get("agent"), "escalated": res.get("escalated"),
            "route_p": (rec.get("route") or {}).get("p"), "route_rung": (rec.get("route") or {}).get("rung"),
            "state_before": before, "state_after": sha(hub / "ccx" / "routing-state.json"), "verify": v,
            "hub": json.loads(info_f.read_text(encoding="utf-8")), "stderr": err if rc else "",
            **hub_cost(hub, {u["label"]})}


# ------------------------------------------------------------------ schedule and run

def schedule(groups: list[str], seed: int, tasks: dict[str, list[str]] | None = None) -> list[dict]:
    out = []
    for g in groups:
        spec = GROUPS[g]
        for rd in range(1, spec["rounds"] + 1):
            rnd = random.Random(f"{seed}:{g}:{rd}")
            ts = list((tasks or {}).get(g) or spec["tasks"])
            rnd.shuffle(ts)
            if g == "learn":                           # phase 1 for every task, then phase 2: the order matters
                out += [{"exp": g, "round": rd, "task": t, "arm": arm} for arm in spec["arms"] for t in ts]
                continue
            if g == "way":                             # three runs per risk, one task each
                out += [{"exp": g, "round": rd, "task": t, "arm": arm} for t in ts for arm in spec["arms"]]
                continue
            for t in ts:
                arms = list(spec["arms"])
                rnd.shuffle(arms)
                out += [{"exp": g, "round": rd, "task": t, "arm": arm} for arm in arms]
    return out


def unit_key(u: dict) -> str:
    return f"{u['tag']}:{u['exp']}:{u['round']}:{u['task']}:{u['arm']}"


def spent(rows: list[dict]) -> float:
    return round(sum(r.get("usd") or 0 for r in rows), 4)


def coop_tasks(rows: list[dict], k: int = 7) -> list[str]:
    """The trap tasks the cheap single run got wrong most often in the second screen (at least k, ties by task
    order)."""
    fails = {t: 0 for t in TRAP2_IDS}
    for r in rows:
        if r.get("exp") == "screen2":
            fails[r["task"]] += not r["ok"]
    order = sorted(TRAP2_IDS, key=lambda t: (-fails[t], TRAP2_IDS.index(t)))
    keep = [t for t in order if fails[t]]
    return keep if len(keep) >= k else order[:k]


def cmd_run(a) -> int:
    out = Path(a.out) if a.out else OUT / "results.jsonl"
    work = Path(a.workdir or tempfile.mkdtemp(prefix="ccx-r2-"))
    a.state = Path(a.state) if a.state else default_state()
    rows = read_jsonl(out)
    done = {unit_key(r) for r in rows}
    tasks = {"coop": coop_tasks(rows)} if "coop" in a.groups.split(",") else {}
    if a.tasks:
        tasks = {g: a.tasks.split(",") for g in a.groups.split(",")}
    print(f"work dir: {work}  results: {out}  state: {a.state} sha256={sha(a.state)}", flush=True)
    for u in schedule(a.groups.split(","), a.seed, tasks):
        if a.rounds and u["round"] > a.rounds:
            continue
        u = {**u, "tag": a.tag, "seed": a.seed}
        u["label"] = f"eval-r2:{a.tag}:{u['exp']}:{u['round']}:{u['task']}:{u['arm']}"
        if unit_key(u) in done:
            continue
        total = spent(read_jsonl(out))
        if total >= a.budget:
            print(f"budget ${a.budget} reached (${total:.3f}): stopping", flush=True)
            return 2
        if a.dry_run:
            print(f"[dry] {u['label']}")
            continue
        try:
            row = run_unit(u, a, work)
        except Exception as e:  # noqa: BLE001 — one broken unit is recorded, the batch goes on
            row = {**u, "ok": False, "error": f"{type(e).__name__}: {e}"[:400], "usd": 0.0, "tokens": 0, "wall_s": 0}
        row["ts"] = time.time()
        append_jsonl(out, row)
        print(f"{u['exp']:6} r{u['round']} {u['task']:10} {u['arm']:8} ok={row.get('ok')} ${row.get('usd', 0):.4f} "
              f"tok={row.get('tokens')} {row.get('wall_s')}s rungs={row.get('rungs')} total=${spent(read_jsonl(out))}",
              flush=True)
    return 0


def cmd_tiers(a) -> int:
    """4-D: what `ccx route` picks at 5 / 15 / 30 minutes, warm and cold (no model is called)."""
    out = Path(a.out) if a.out else OUT / "tiers.json"
    work = Path(tempfile.mkdtemp(prefix="ccx-r2-tiers-"))
    state = Path(a.state) if a.state else default_state()
    briefs = {t: by_id(t)["brief"] for t in ["slugify", "csvstats", "cart"]}
    res = {"state_sha256": sha(state), "picks": []}
    for warm in (True, False):
        hub = work / ("warm" if warm else "cold")
        make_hub(hub, state if warm else None)
        for t, b in briefs.items():
            for m in (5, 15, 30):
                r, rc, _, err = ccx(["route", "--to", "auto", "--minutes", str(m), b], ROOT, hub, 120)
                res["picks"].append({"warm": warm, "task": t, "minutes": m, "rung": r.get("rung"), "p": r.get("p"),
                                     "ladder": r.get("ladder"), "b": r.get("b"), "rc": rc})
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps(res, indent=1))
    return 0


# ------------------------------------------------------------------ statistics

def pairs(rows: list[dict], exp: str, A: str, B: str) -> list[tuple[dict, dict]]:
    by: dict = {}
    for r in rows:
        if r.get("exp") == exp and "error" not in r:
            by.setdefault((r["tag"], r["round"], r["task"]), {})[r["arm"]] = r
    return [(d[A], d[B]) for _, d in sorted(by.items()) if A in d and B in d]


METRICS = {"usd": lambda r: r.get("usd") or 0, "tokens": lambda r: r.get("tokens") or 0,
           "wall_s": lambda r: r.get("wall_s") or 0}


def compare_arms(ps: list[tuple[dict, dict]], A: str, B: str) -> dict:
    ka, kb = sum(bool(p[0]["ok"]) for p in ps), sum(bool(p[1]["ok"]) for p in ps)
    b = sum(bool(p[0]["ok"]) and not p[1]["ok"] for p in ps)
    c = sum(bool(p[1]["ok"]) and not p[0]["ok"] for p in ps)
    usd_a, usd_b = sum(p[0].get("usd") or 0 for p in ps), sum(p[1].get("usd") or 0 for p in ps)
    return {"arms": [A, B], "pairs": len(ps), "tasks": len({p[0]["task"] for p in ps}), "ok": {A: ka, B: kb},
            "ok_wilson": {A: S.wilson(ka, len(ps)), B: S.wilson(kb, len(ps))}, "discordant": {f"only_{A}": b,
                                                                                            f"only_{B}": c},
            "mcnemar_p": S.mcnemar_p(b, c), "spend_ratio": round(usd_b / usd_a, 2) if usd_a else None,
            "ccx_ok_hidden_failed": {arm: sum(bool(p[i].get("ccx_ok")) and not p[i]["ok"] for p in ps)
                                     for i, arm in enumerate((A, B))},
            "metrics": {k: S.compare(ps, f) for k, f in METRICS.items()}}


def brier(rs: list[dict]) -> float | None:
    xs = [(r["route_p"] - bool(r["ok"])) ** 2 for r in rs if r.get("route_p") is not None]
    return round(statistics.fmean(xs), 4) if xs else None


def summarize(rows: list[dict]) -> dict:
    res: dict = {"spend_usd": spent(rows), "units": len(rows),
                 "spend_by_group": {g: spent([r for r in rows if r.get("exp") == g]) for g in GROUPS}}
    comps = {"review": [("off", "on"), ("off", "auto")], "coop": [("single", "way"), ("single", "draft"),
                                                                  ("draft", "way")],
             "par": [("p1", "native"), ("c_off", "c_on"), ("p1", "p3"), ("p1", "p10")],
             "route": [("fixed", "warm"), ("fixed", "cold"), ("cold", "warm")]}
    for exp, cs in comps.items():
        for A, B in cs:
            ps = pairs(rows, exp, A, B)
            if ps:
                res[f"{exp}:{A}->{B}"] = compare_arms(ps, A, B)
    prim = {k: res[k]["mcnemar_p"] for k in ("review:off->on", "coop:single->way", "coop:single->draft") if k in res}
    res["primary_holm"] = {k: {"p": p, "p_holm": q} for k, (p, q) in S.holm(prim).items()}
    per_arm = {}
    for r in rows:
        if "error" in r:
            continue
        s = per_arm.setdefault(f"{r['exp']}:{r['arm']}", {"n": 0, "ok": 0, "usd": 0.0, "tokens": 0, "wall": []})
        s["n"] += 1
        s["ok"] += bool(r.get("ok"))
        s["usd"] = round(s["usd"] + (r.get("usd") or 0), 6)
        s["tokens"] += r.get("tokens") or 0
        s["wall"].append(r.get("wall_s") or 0)
        for k in ("n_ok", "conflicts", "children", "n_runs", "rework"):
            if isinstance(r.get(k), (int, float)):
                s.setdefault(k, []).append(r[k])
        if r.get("exp") in ("route", "learn", "screen", "review"):
            s.setdefault("rungs", {})
            for g in r.get("rungs") or []:
                s["rungs"][g] = s["rungs"].get(g, 0) + 1
            if r.get("escalated"):
                s["escalated"] = s.get("escalated", 0) + 1
    for s in per_arm.values():
        s["wall_median"] = statistics.median(s.pop("wall")) if s["n"] else None
    res["per_arm"] = per_arm
    way = [r for r in rows if r.get("exp") == "way"]
    if way:
        res["way_smoke"] = [{k: r.get(k) for k in ("arm", "task", "state", "ok", "plan_steps", "plan_accepts",
                                                   "plan_other", "acceptance", "pick", "version_ok", "pick_right",
                                                   "rework", "usd", "wall_s", "rc")} for r in way]
    lr = [r for r in rows if r.get("exp") == "learn" and "error" not in r]
    warm = {r["task"]: r for r in rows if r.get("exp") == "route" and r.get("arm") == "warm" and "error" not in r}
    if lr:
        p1 = [r for r in lr if r["arm"] == "phase1"]
        p2 = {r["task"]: r for r in lr if r["arm"] == "phase2"}
        both = [t for t in p2 if t in warm]
        res["learn"] = {"brier_phase1": brier(p1), "brier_phase2_learning": brier(list(p2.values())),
                        "brier_frozen(route:warm)": brier([warm[t] for t in both]),
                        "ok": {"phase1": sum(bool(r["ok"]) for r in p1), "phase2": sum(bool(r["ok"]) for r in p2.values()),
                               "frozen": sum(bool(warm[t]["ok"]) for t in both), "n": len(both)},
                        "frozen_vs_learning": compare_arms([(warm[t], p2[t]) for t in both], "frozen", "phase2")
                        if both else None,
                        "state_changed": sum(r.get("state_before") != r.get("state_after") for r in lr),
                        "rungs_phase1": [r.get("route_rung") for r in p1],
                        "rungs_phase2": [p2[t].get("route_rung") for t in p2]}
    return res


def cmd_summary(a) -> int:
    rows = read_jsonl(Path(a.file) if a.file else OUT / "results.jsonl")
    if a.tag:
        rows = [r for r in rows if r.get("tag") == a.tag]
    if a.groups:
        rows = [r for r in rows if r.get("exp") in a.groups.split(",")]
    print(json.dumps(summarize(rows), ensure_ascii=False, indent=1))
    return 0


def cmd_spend(a) -> int:
    rows = read_jsonl(Path(a.file) if a.file else OUT / "results.jsonl")
    print(json.dumps({"total": spent(rows), **{g: spent([r for r in rows if r.get("exp") == g]) for g in GROUPS}}))
    return 0


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--groups", required=True)
    r.add_argument("--tag", default="r2")
    r.add_argument("--seed", type=int, default=26)
    r.add_argument("--rounds", type=int, default=0, help="only rounds up to this one (0 = the group's default)")
    r.add_argument("--tasks", default="", help="only these task ids")
    r.add_argument("--budget", type=float, default=6.0, help="stop before a new unit once ALL results reach $")
    r.add_argument("--state", default="", help="routing state to copy for warm hubs (default: the person's hub)")
    r.add_argument("--out", default="")
    r.add_argument("--workdir", default="")
    r.add_argument("--timeout", type=int, default=900)
    r.add_argument("--dry-run", action="store_true")
    r.set_defaults(fn=cmd_run)
    t = sub.add_parser("tiers")
    t.add_argument("--state", default="")
    t.add_argument("--out", default="")
    t.set_defaults(fn=cmd_tiers)
    for name, fn in (("summary", cmd_summary), ("spend", cmd_spend)):
        s = sub.add_parser(name)
        s.add_argument("--file", default="")
        s.add_argument("--tag", default="")
        s.add_argument("--groups", default="")
        s.set_defaults(fn=fn)
    return ap


def main(argv=None) -> int:
    a = parser().parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
