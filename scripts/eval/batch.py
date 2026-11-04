"""Batch / pipeline throughput eval (request 7: "hand off task A, B, C... in parallel, accept the results as they come
back"): one lead session gets several past changes at once, and what counts is the merged tree at the end.

Batches (scripts/eval/tasks_batch.py) are hold-out changes (scripts/eval/tasks_holdout.py) of one repository put on
one common start (scripts/eval/batch_start.py): the end is the first commit that has all of them, every batch commit
is reverted on it (newest first, git's three-way revert), so each change's hidden test fails at the start and all of
them pass at the end. `check` builds every batch and checks it the way holdout_check checks a task: band and
leakage against r5 (holdout_check.static), each change has hidden nodes that fail at the start and pass at the end,
none of them sits in the start's test files word for word, the start imports, and the declared same-file overlap is
the real one. A combination that cannot be put on one start (a revert conflicts in code or tests) is dropped and
said so; the batch is then the largest feasible set.

Arms (one lead session per batch; the lead is a fresh headless Claude Code, --lead-model / --lead-effort as r5,
default opus medium as the design asks, recorded in every row, its fingerprint and done-key):

  self          the lead does the whole batch itself
  builtin       the lead hands the changes to Claude Code's built-in `worker` sub-agent; several at once allowed
  ccx-batch     the lead writes one plan and runs today's `ccx batch` (parallel, a worktree per writer), merges
  ccx-pipeline  the lead queues the plan (`ccx q add --plan`), `ccx q run --bg`, waits with
                `ccx show <ids> --any --wait`, accepts each result as it comes back, merges the branches listed
                under waiting / unmerged, then `ccx q done` (the agent-delegate skill's "several pieces" text)
  balanced      the lead splits by tier: large file-disjoint changes to `ccx run --bg --worktree --tradeoff
                balanced`, the small and the same-file ones itself, then `show --any --wait`, merges

Per unit (batch x repeat x arm): total wall; lead $ and sub-agent $ (builtin: the worker model's share of the lead's
bill; ccx arms: the hub's ledger); hidden tests on the FINAL tree of the lead's checkout (per change: all its nodes
pass; all-right: every change right and no node that passed at the start fails); merge conflicts the lead met
(CONFLICT lines in its tool results) and conflict markers left in the tree; the lead's requests, turns, tokens,
wake-ups (blocking waits that came back: Agent calls, `show --wait`, `ccx batch`, foreground `ccx run` / `q run`)
and idle ratio (the union of those waits' time over the wall, from the arrival time of each stream line); quota
events (rejected rate-limit events of the lead, quota / rate-limit / auth attempts in the ccx runs, backpressure).
The clean room is round 5's (scripts/eval/preflight.py): preflight before the first unit, a fingerprint, audit,
leftovers and env_clean on every row, checks between units.

  python scripts/eval/batch.py check [--batches ho5-overlap] [--static] [--ext-cache DIR] [--ext-python PY]
  python scripts/eval/batch.py run --dry-run --reps 2                 # plan and cost estimate, nothing runs
  python scripts/eval/batch.py run --reps 2 --tag bt1 --budget 25 --codex-home <eval codex home>
  python scripts/eval/batch.py summary [--tag bt1]

The summary gives per batch and arm the wall median / p90 over repeats, $ (lead, sub-agents), right per change and
all-right, conflicts, wake-ups, turns, tokens, idle ratio, quota events; and every two arms paired on the repeats of
the same batch, as plain per-batch numbers with n: a few batches of five changes are too few for a task-level
bootstrap.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import re
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import batch_start as BS  # noqa: E402
import ext_repo  # noqa: E402
import preflight as PF  # noqa: E402
import r2  # noqa: E402
import r3  # noqa: E402
import r5  # noqa: E402
import tasks_batch as TB  # noqa: E402
from common import ROOT, append_jsonl, archive_hub, ccx_verify, read_jsonl  # noqa: E402

OUT = ROOT / ".ccx" / "eval" / "batch"
RESULTS = OUT / "results.jsonl"
ARMS = ("self", "builtin", "ccx-batch", "ccx-pipeline", "balanced")
CCX_ARMS = ("ccx-batch", "ccx-pipeline", "balanced")
# the round-3/5 arm whose lead command line (tools, Agent + worker, session file) and preflight needs an arm uses
FLAGS_ARM = {"self": "self", "builtin": "builtin", "ccx-batch": "ccx", "ccx-pipeline": "ccx", "balanced": "ccx"}
DEFAULT_LEAD = ("opus", "medium")
LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

# Dry-run estimate only (not a measurement): $ per change with an opus lead, from the round-5 based projection of
# the pipeline design (self ~$1.0 a batch of five, ccx save pipeline ~$0.6-0.8, balanced ~$0.80-0.85); other lead
# models scaled roughly by price.
EST_USD_PER_TASK = {"self": 0.20, "builtin": 0.18, "ccx-batch": 0.16, "ccx-pipeline": 0.14, "balanced": 0.17}
EST_WALL_PER_TASK = {"self": 100, "builtin": 60, "ccx-batch": 170, "ccx-pipeline": 190, "balanced": 110}
LEAD_PRICE = {"opus": 1.0, "fable": 1.0, "sonnet": 0.6, "haiku": 0.2}

BATCH_PROMPT = """You are the lead agent on this repository: {name}. {setup}The person asked for {n} separate changes,
{letters}. Each is its own request; together they are one batch.

{briefs}

{how}

Only what is in this checkout at the end counts: work left on another branch or in a worktree does not. Commit the
work here when it is done. When every change is done and its tests pass, end with one line per change:
DONE <letter>: <what changed>."""
NAME_THIS = "relayline, the `ccx` command (Python, standard library only; see AGENTS.md)"
SETUP_THIS = ("The full test suite takes about 7 minutes, so run the tests that matter for a change, e.g. "
              "`python -m pytest -q tests/test_<area>.py`. ")
SETUP_EXT = ("It is not installed, and nothing can be installed (pip has no package index here): PYTHONPATH=src is "
             "set, so from the repository root `python -m pytest -q tests/...` tests the code in src/. {note}Run the "
             "tests that matter for each change. ")
PLAN_FILE = ("Write the plan file outside this checkout (for example in your temp folder, $TMP / %TEMP%), so the "
             "checkout stays clean and worktrees see all of it.")
MERGE = ("A change that ran in a worktree left its work on the branch `ccx/<run_id>` (if it is not committed there "
         "yet, commit it in that worktree first): merge it into this checkout and settle any conflict yourself.")
HOW = {
    "self": "Do all the work yourself, in this checkout.",
    "builtin": (
        "Do not edit files yourself: hand the changes to your sub-agent. Call the Agent tool with subagent_type "
        "`worker` and a brief per change that contains everything it needs. You may start several workers at once "
        "(several Agent calls in one message) for changes that touch different files; changes that may touch the "
        "same file go to one worker, or one after another. All workers work in this same checkout. When a worker "
        "reports back, check the result (read the diff, run the tests); if something is wrong or missing, send it "
        "back to a worker saying what to fix."),
    "ccx-batch": (
        "Do not edit files yourself: hand the changes to sub-agents through ccx, in one batch. Write a plan file "
        "{{\"tasks\": [{{\"id\": \"A\", \"brief\": \"<brief>\", \"mode\": \"write\", \"check\": \"<a pytest command "
        "for its test files>\"}}, ...]}} with one task per change. " + PLAN_FILE + " Then run\n"
        "  {ccx} batch <plan file>\n"
        "It runs the pieces in parallel (each writer in its own git worktree when there are several) and prints one "
        "JSON object with every piece's result (run_id, ok, check, worktree, ...). " + MERGE + " "
        + r5.LEAN_BRIEF + " "
        + r5.LEAN_ACCEPT.replace("{send_back}", "{ccx} resume <run_id> \"<what to fix>\"")),
    "ccx-pipeline": (
        "Do not edit files yourself: hand every change to a sub-agent through ccx's work queue and accept the "
        "results as they come back. Write a plan file {{\"tasks\": [{{\"id\": \"A\", \"title\": \"<short title>\", "
        "\"brief\": \"<brief>\", \"check\": \"<a pytest command for its test files>\", \"files\": [<files you expect "
        "it to touch, if you know them>]}}, ...]}}; a change that touches a file another one touches gets "
        "\"deps\": [\"<the other's id>\"], so the two never run side by side. " + PLAN_FILE + " Then\n"
        "  {ccx} q add --plan <plan file>\n"
        "  {ccx} q run --bg\n"
        "`{ccx} q ls` shows each running item's run id as `live`; wait for them with\n"
        "  {ccx} show <live run ids> --any --wait\n"
        "which hands back every run that has finished; call it again with the ids still running (and new `live` "
        "ones) until none is left. Accept each one as it comes back. Items listed under `waiting` or `unmerged` "
        "(in `{ccx} q ls`) ran in a worktree: " + MERGE + " Then `{ccx} q done <id> --ok 1` and `{ccx} q run --bg` "
        "again for what waits on it; `dep_blocked` items wait on one that failed. If `last_run` says "
        "`stopped: backpressure` (quota or auth), start nothing new. When everything is merged, run the union of "
        "the checks once. Never resume a run that is still running; do not pipe ccx output through tail or head. "
        + r5.LEAN_BRIEF + " "
        + r5.LEAN_ACCEPT.replace("{send_back}", "{ccx} resume <run_id> \"<what to fix>\"")),
    "balanced": (
        "Split the batch by size. Hand each larger change whose files no other change touches to ccx in the "
        "background, one run each, in its own worktree:\n"
        "  {ccx} run --bg --worktree --tradeoff balanced --context auto --mode write --new --no-ab "
        "--label {label}:<letter> --check \"<a pytest command for its test files>\" \"<brief>\"\n"
        "(it prints the run_id at once). Do the small changes, and every change that shares a file with another, "
        "yourself in this checkout, smallest first, while those runs work. Then wait for them with\n"
        "  {ccx} show <run ids> --any --wait\n"
        "and call it again with the ids still running until none is left. " + MERGE + " Never resume a run that is "
        "still running; do not pipe ccx output through tail or head. " + r5.LEAN_BRIEF + " "
        + r5.LEAN_ACCEPT.replace("{send_back}", "{ccx} resume <run_id> \"<what to fix>\"")),
}


# ------------------------------------------------------------------ batches and their material

def batch_tasks(b: dict) -> list[dict]:
    return [TB.task_by_id(t) for t in b["tasks"]]


def spec_of(b: dict) -> dict | None:
    return TB.REPOS[b["repo"]] if b.get("repo") else None


def tasks_sha() -> str:
    """The batches and the hold-out tasks they are made of (briefs, commits, tests): a cached check is stale when
    either changed."""
    import hashlib
    import tasks_holdout
    h = hashlib.sha256()
    for f in (TB.__file__, tasks_holdout.__file__):
        h.update((PF.sha256_file(Path(f)) or "").encode())
    return h.hexdigest()[:16]


def check_sha() -> str:
    """What a cached check depends on: the batches and tasks (tasks_sha) and the code that builds the start and
    selects the nodes (batch_start.py, this file). A cached check is used only when this is the same."""
    import hashlib
    h = hashlib.sha256(tasks_sha().encode())
    for f in (BS.__file__, __file__):
        h.update((PF.sha256_file(Path(f)) or "").encode())
    return h.hexdigest()[:16]


def check_file(bid: str) -> Path:
    return OUT / "checks" / f"{bid}.json"


def _source(b: dict, tmp: Path, ext_source: str | None) -> Path:
    """Where the batch's commits come from: this checkout, or a bare clone of the other repository made in `tmp`
    (from its URL, or from --ext-cache)."""
    spec = spec_of(b)
    if not spec:
        return ROOT
    return ext_repo.fetch(b["repo"], spec, tmp / "cache", Path(ext_source).expanduser() if ext_source else None)


def tip_of(b: dict, src: Path) -> str:
    """The history the end is looked for in: this checkout's HEAD, or the other repository's default branch."""
    return BS.full(src, "HEAD")


def _tree_env(iso: Path, spec: dict | None, python: str) -> dict:
    env = r5.iso_env(iso, python)
    if spec:
        env.update(ext_repo.run_env(spec))
    return env


def pytest_nodes(repo: Path, files: list[str], spec: dict | None, python: str, scratch: Path,
                 deselect: list[str] = (), job: PF.Job | None = None, timeout: int = 1200) -> dict:
    """The hidden test files run in `repo` (throwaway homes, as r5.score), node by node. A file that does not
    collect (it imports a name the tree lacks) is an error for that file only: the other files still run
    (--continue-on-collection-errors), so one change's missing name does not fail every change's nodes."""
    iso = Path(tempfile.mkdtemp(prefix="r5iso-", dir=scratch))
    try:
        args = [python, "-m", "pytest", "-q", "-rA", "-p", "no:cacheprovider", "--color=no",
                "--continue-on-collection-errors", *files]
        for n in deselect:
            args += ["--deselect", n]
        out, _err, rc, _left = PF.run(args, cwd=repo, env=_tree_env(iso, spec, python), timeout=timeout, job=job)
        res = BS.parse_results(out)
        tail = r5.ANSI.sub("", (out.strip().splitlines() or [""])[-1])
        res.update(rc=rc, tail=("timeout" if rc == -9 else tail[:200]))
        return res
    finally:
        r2._rmtree(iso)


def put_tests(repo: Path, hidden: dict[str, bytes], spec: dict | None, end_tar: bytes | None = None,
              keep: list[str] = ()) -> None:
    """The hidden test files over whatever is there. Another repository: its test folder and test configuration
    put back from the end first and its install-time stubs; this one: today's tests/conftest.py, as r5."""
    if spec and end_tar is not None:
        ext_repo.restore_test_setup(repo, end_tar, spec, keep=list(keep))
    for f, body in hidden.items():
        (repo / f).parent.mkdir(parents=True, exist_ok=True)
        (repo / f).write_bytes(body)
    if spec:
        ext_repo.write_stubs(repo, spec)
    else:
        (repo / "tests").mkdir(exist_ok=True)
        (repo / "tests" / "conftest.py").write_text(r5.CONFTEST, encoding="utf-8")


def _run_tree(tar: bytes, hidden: dict, files: list[str], spec: dict | None, python: str, scratch: Path,
              deselect: list[str] = ()) -> dict:
    d = Path(tempfile.mkdtemp(prefix="tree-", dir=scratch))
    try:
        BS.extract(tar, d / "repo")
        put_tests(d / "repo", hidden, spec)
        return pytest_nodes(d / "repo", files, spec, python, d, deselect)
    finally:
        r2._rmtree(d)


def smoke(tar: bytes, spec: dict | None, python: str, scratch: Path) -> str | None:
    """Does the start import? (this repository: `ccx -h`; another one: import its module with PYTHONPATH=src)."""
    d = Path(tempfile.mkdtemp(prefix="smoke-", dir=scratch))
    try:
        BS.extract(tar, d / "repo")
        if spec:
            ext_repo.write_stubs(d / "repo", spec)
            argv = [python, "-c", f"import {spec['module']}"]
        elif (d / "repo" / "ccx.py").exists():
            argv = [python, "ccx.py", "-h"]
        else:                                       # a small test repository: it compiles
            argv = [python, "-m", "compileall", "-q", "."]
        out, err, rc, _ = PF.run(argv, cwd=d / "repo", env=_tree_env(d / "iso", spec, python), timeout=300)
        return None if rc == 0 else f"the start does not import: {(err or out).strip()[-200:]}"
    finally:
        r2._rmtree(d)


def build(b: dict, tmp: Path, ext_source: str | None = None, python: str | None = None, run_tests: bool = True,
          cached: dict | None = None, source: Path | None = None, tasks: list[dict] | None = None) -> dict:
    """A batch's material: the start and end trees (tar bytes, in memory), the hidden test files, every change's
    hidden nodes and the check's findings. `cached` (an earlier check of the same start tree, end, changes and
    check code) saves the pytest runs.
    `source` / `tasks` replace the batch's repository and task definitions (tests use a small repository)."""
    python = python or sys.executable
    spec = spec_of(b)
    ts = tasks or batch_tasks(b)
    src = source or _source(b, tmp, ext_source)
    c = BS.clone(src, tmp / f"clone-{b['id']}")
    end, order = BS.plan(c, [t["commit"] for t in ts], tip_of(b, src))
    sha_of = {BS.full(c, t["commit"]): t["id"] for t in ts}
    rev = BS.revert_all(c, end, order)
    kept = [t for t in ts if BS.full(c, t["commit"]) in rev["reverted"]]
    probs: list[str] = []
    if b.get("end") and not end.startswith(b["end"]):
        probs.append(f"end is {end[:12]}, the batch says {b['end']}")
    dropped = {sha_of[s]: files for s, files in rev["dropped"].items()}
    if dropped:
        probs.append(f"cannot be put on one start (revert conflicts): {sorted(dropped)}; the largest feasible set "
                     f"is {[t['id'] for t in kept]}")
    files = {t["id"]: BS.changed_files(c, t["commit"]) for t in kept}
    ov = BS.overlap(files)
    got = sorted({f for o in ov for f in o["files"] if not f.startswith("tests/")})
    if sorted(b.get("overlap") or []) != got:
        probs.append(f"same-file overlap is {got}, the batch says {sorted(b.get('overlap') or [])}")
    test_files = sorted({f for t in kept for f in t["tests"]})
    hidden = {f: BS.show(c, end, f) for f in test_files}
    probs += [f"{f} is missing at the end" for f, v in hidden.items() if v is None]
    hidden = {f: v for f, v in hidden.items() if v is not None}
    start_files = {f: BS.show(c, rev["start"], f) for f in test_files}
    mat = {"batch": b["id"], "repo": b.get("repo") or "this", "end": end, "start": rev["start"],
           "tasks": [t["id"] for t in kept], "commits": {t["id"]: BS.full(c, t["commit"]) for t in kept},
           "dropped": dropped, "docs_from_parent": rev["docs_from_parent"], "overlap": ov, "files": files,
           "tests": {t["id"]: t["tests"] for t in kept}, "test_files": test_files,
           # tests of these files unrelated to the changes and flaky under load (tasks_holdout's `deselect`)
           "deselect": sorted({n for t in kept for n in t.get("deselect") or ()}),
           "changed": sorted({f for v in files.values() for f in v}),
           "start_tar": BS.archive(c, rev["start"]), "end_tar": BS.archive(c, end), "hidden": hidden,
           "start_tree": BS.tree(c, rev["start"]), "tasks_sha256": tasks_sha(), "check_sha256": check_sha()}
    # the start's tree, not its commit: what the lead and the scoring see is the tree
    if cached and cached.get("start_tree") == mat["start_tree"] and cached.get("end") == end and \
            cached.get("tasks") == mat["tasks"] and cached.get("check_sha256") == mat["check_sha256"] and \
            cached.get("nodes"):
        for k in ("nodes", "start_passed", "failing_at_end", "not_failing_at_start", "coupled", "leaks",
                  "smoke", "without_how", "collect_errors"):
            mat[k] = cached.get(k)
        probs += [p for p in cached.get("problems") or [] if p not in probs and not p.startswith(("end is",
                                                                                                    "cannot be put"))]
        mat["problems"] = probs
        mat["from_cache"] = True
        return mat
    if run_tests:
        scratch = tmp / f"runs-{b['id']}"
        scratch.mkdir(parents=True, exist_ok=True)
        ds = mat["deselect"]
        e = _run_tree(mat["end_tar"], hidden, test_files, spec, python, scratch, ds)
        s = _run_tree(mat["start_tar"], hidden, test_files, spec, python, scratch, ds)
        without, how = {}, {}
        kept_order = [s for s in order if s in rev["reverted"]]
        for t in kept:
            tar, how[t["id"]] = BS.without_one(c, end, rev["start"], kept_order, mat["commits"][t["id"]])
            without[t["id"]] = None if tar is None else _run_tree(tar, hidden, test_files, spec, python, scratch, ds)
        mat["without_how"] = how
        sel = BS.select_nodes(e, without, s, mat["tests"])
        mat["nodes"] = sel["nodes"]
        mat["not_failing_at_start"] = sel["not_failing_at_start"]
        mat["coupled"] = sel["coupled"]
        mat["failing_at_end"] = sorted(e["failed"])
        # a hidden file that does not collect at the start (it imports what the change adds) is expected; it
        # is recorded, and its nodes simply do not pass there
        mat["collect_errors"] = {"end": sorted(e["errors"]), "start": sorted(s["errors"]),
                                 "without": {t: sorted(w["errors"]) for t, w in without.items() if w}}
        if e["errors"]:
            probs.append(f"test files that do not even collect at the end: {sorted(e['errors'])}")
        if not (s["passed"] or s["failed"] or s["errors"]):
            probs.append(f"the start run gave no result: {s['tail']}")
        mat["start_passed"] = sorted(s["passed"])
        mat["leaks"] = BS.leaks(sel["nodes"], hidden, start_files)
        mat["smoke"] = smoke(mat["start_tar"], spec, python, scratch)
        probs += sel["problems"] + mat["leaks"] + ([mat["smoke"]] if mat["smoke"] else [])
    mat["problems"] = probs
    return mat


def static_problems(b: dict, tmp: Path, ext_source: str | None) -> list[str]:
    """holdout_check.static for every change of the batch: band, recorded size, leakage from r5's tasks."""
    import holdout_check as HC
    against = list(r5.TASKSETS["r5"].T)
    ctx = HC.Ctx(tmp / "hc", ext_source)
    out = []
    for t in batch_tasks(b):
        out += [f"{t['id']}: {p}" for p in HC.static(t, against, ctx)]
    return out


def report(mat: dict) -> dict:
    """The check's findings without the trees (what `check` prints and caches)."""
    return {k: v for k, v in mat.items() if k not in ("start_tar", "end_tar", "hidden")}


def load_cached(bid: str) -> dict | None:
    try:
        d = json.loads(check_file(bid).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return d if d.get("check_sha256") == check_sha() else None


def cmd_check(a) -> int:
    ids = a.batches.split(",") if a.batches else TB.IDS
    tmp = Path(tempfile.mkdtemp(prefix="ccx-batch-check-"))
    rows = []
    try:
        for bid in ids:
            b = TB.by_id(bid)
            try:
                mat = build(b, tmp, a.ext_cache, a.ext_python or None, run_tests=not a.static)
                mat["problems"] = static_problems(b, tmp, a.ext_cache) + mat["problems"]
            except Exception as e:  # noqa: BLE001 — a batch that cannot be built is a finding
                mat = {"batch": bid, "problems": [f"{type(e).__name__}: {e}"[:400]]}
            rep = {**report(mat), "ok": not mat["problems"]}
            if not a.static and "nodes" in mat:
                check_file(bid).parent.mkdir(parents=True, exist_ok=True)
                check_file(bid).write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
            rows.append(rep)
            print(json.dumps(rep, ensure_ascii=False), flush=True)
    finally:
        ext_repo._rmtree(tmp)
    bad = [r["batch"] for r in rows if not r["ok"]]
    print(f"{len(rows) - len(bad)}/{len(rows)} ok" + (f"; with problems: {', '.join(bad)}" if bad else ""))
    return 1 if bad else 0


# ------------------------------------------------------------------ one unit

def lead_of(u: dict) -> tuple[str, str]:
    return (u.get("lead_model") or DEFAULT_LEAD[0], u.get("lead_effort") or DEFAULT_LEAD[1])


def lead_suffix(u: dict) -> str:
    """A non-default lead in a unit's folder name and summary arm (folder names keep to [\\w.-], as the work dir
    check expects)."""
    m, e = lead_of(u)
    return "" if (m, e) == DEFAULT_LEAD else "." + re.sub(r"[^\w.-]", "_", f"{m}-{e}")


def arm_of(r: dict) -> str:
    return f"{r['arm']}{lead_suffix(r)}"


def done_key(r: dict) -> tuple:
    return (r.get("tag"), r.get("rep"), r.get("batch"), r.get("arm"), *lead_of(r))


def unit_key(u: dict) -> str:
    return f"{u['rep']}-{u['batch']}-{u['arm']}{lead_suffix(u)}"


def lead_prompt(u: dict, b: dict, mat: dict) -> str:
    spec = spec_of(b)
    ids = mat["tasks"]
    letters = LETTERS[:len(ids)]
    briefs = "\n\n".join(f"## Change {letters[i]}\n\n{TB.task_by_id(t)['brief']}" for i, t in enumerate(ids))
    name = spec["name"] if spec else NAME_THIS
    setup = SETUP_EXT.format(note=r5.ext_note(spec)) if spec else SETUP_THIS
    how = HOW[u["arm"]].format(ccx=r3.CCX_CMD, label=u["label"])
    lt = ", ".join(letters[:-1]) + f" and {letters[-1]}" if len(letters) > 1 else letters
    return BATCH_PROMPT.format(name=name, setup=setup, n=len(ids), letters=lt, briefs=briefs, how=how)


def lead_argv(u: dict, budget: float) -> list[str]:
    model, effort = lead_of(u)
    return r3.lead_argv(FLAGS_ARM[u["arm"]], budget, model, effort)


def run_timed(argv: list[str], *, cwd: Path, env: dict, timeout: float, input: str | None = None,
              job: PF.Job | None = None) -> tuple[str, str, int, list[tuple[float, str]]]:
    """preflight.run, but every stdout line with the time it arrived (seconds from the start), for the lead's
    timeline. The child and all it starts live in `job`; on a timeout the job is killed."""
    own = job is None
    job = job or PF.Job()
    t0 = time.time()
    p = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.PIPE if input is not None else subprocess.DEVNULL,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                         errors="replace", **job.popen_kw())
    job.start(p)
    lines: list[tuple[float, str]] = []
    err: list[str] = []

    def read_out():
        for line in p.stdout:
            lines.append((round(time.time() - t0, 3), line.rstrip("\n")))

    def read_err():
        err.append(p.stderr.read())
    ts = [threading.Thread(target=read_out, daemon=True), threading.Thread(target=read_err, daemon=True)]
    for t in ts:
        t.start()
    if input is not None:
        try:
            p.stdin.write(input)
            p.stdin.close()
        except OSError:
            pass
    try:
        rc = p.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        if job.h:
            job.terminate()
        p.kill()
        rc = -9
    for t in ts:
        t.join(timeout=30)
    if own:
        job.close()
    return "\n".join(x for _, x in lines), "".join(err), rc, lines


WAIT_BASH = (re.compile(r"\bshow\b[^\n;&|]*--wait"), re.compile(r"ccx(\.py)?[\"']?\s+batch\b"))
FG_CCX = re.compile(r"ccx(\.py)?[\"']?\s+(run|resume|q\s+run)\b([^\n;&|]*)")
QUOTED = re.compile(r"\"[^\"]*\"|'[^']*'")          # quoted text: a brief or --check command, not flags
CONFLICT = re.compile(r"^CONFLICT \(", re.M)        # one line per conflicted file ("Automatic merge failed" follows)
MERGE_CMD = re.compile(r"\bgit\s+(merge|cherry-pick|rebase|am)\b")
QUOTA_KINDS = ("quota", "rate_limit", "auth")


def is_wait(name: str, inp: dict) -> bool:
    """A tool call that blocks the lead until sub-agent work comes back."""
    if name in ("Agent", "Task"):
        return True
    if name == "TaskOutput":
        return bool((inp or {}).get("block", True))
    if name != "Bash":
        return False
    cmd = str((inp or {}).get("command", ""))
    if any(p.search(cmd) for p in WAIT_BASH):
        return True
    # `--bg --wait N` (one call, #147) blocks like a foreground run; plain `--bg` returns at once. Flags are read
    # with quoted text (the brief, a --check command) blanked, so a brief that mentions --wait or --bg is not one.
    for m in FG_CCX.finditer(cmd):
        flags = QUOTED.sub('""', m.group(3))
        if not re.search(r"(?<![\w-])--bg\b", flags) or re.search(r"(?<![\w-])--wait\b", flags):
            return True
    return False


def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(_text(c.get("text") if isinstance(c, dict) and "text" in c else c.get("content")
                               if isinstance(c, dict) else c) for c in content)
    return "" if content is None else str(content)


def _union(iv: list[tuple[float, float]]) -> float:
    tot, cur = 0.0, None
    for s, e in sorted(iv):
        if cur is None or s > cur[1]:
            if cur:
                tot += cur[1] - cur[0]
            cur = [s, e]
        else:
            cur[1] = max(cur[1], e)
    return tot + (cur[1] - cur[0] if cur else 0.0)


def timeline(lines: list[tuple[float, str]], wall: float) -> dict:
    """From the lead's timed stream: its blocking waits (wake-ups: those that came back), the share of the wall it
    spent in them (idle ratio), merge conflicts it met, merges it ran, rejected rate-limit events and backpressure
    in tool results. Sub-agent messages (parent_tool_use_id set) are left out."""
    uses: dict[str, tuple[float, str, dict]] = {}
    back: dict[str, tuple[float, str]] = {}
    rejected = 0
    for t, line in lines:
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("type") == "rate_limit_event" and (ev.get("rate_limit_info") or {}).get("status") == "rejected":
            rejected += 1
        if ev.get("parent_tool_use_id") is not None:
            continue
        for c in (ev.get("message") or {}).get("content") or []:
            if not isinstance(c, dict):
                continue
            if ev.get("type") == "assistant" and c.get("type") == "tool_use" and c.get("id"):
                uses.setdefault(c["id"], (t, c.get("name") or "", c.get("input") or {}))
            elif ev.get("type") == "user" and c.get("type") == "tool_result" and c.get("tool_use_id"):
                back.setdefault(c["tool_use_id"], (t, _text(c.get("content"))))
    waits = [i for i, (_, n, inp) in uses.items() if is_wait(n, inp)]
    iv = [(uses[i][0], back[i][0] if i in back else wall) for i in waits]
    idle = min(float(wall), _union(iv)) if wall else 0.0
    texts = [x for _, x in back.values()]
    cmds = [str(inp.get("command", "")) for _, n, inp in uses.values() if n == "Bash"]
    return {"lead_waits": len(waits), "lead_wakeups": sum(i in back for i in waits),
            "lead_idle_s": round(idle, 1), "lead_idle_ratio": round(idle / wall, 3) if wall else None,
            "merge_conflicts": sum(len(CONFLICT.findall(x)) for x in texts),
            "merges": sum(len(MERGE_CMD.findall(c)) for c in cmds),
            "rate_limit_rejected": rejected, "backpressure": sum("backpressure" in x for x in texts)}


def quota_attempts(hub: Path, run_ids: list) -> int:
    """ccx attempts that ended on quota, rate limit or auth (any attempt, not only the last: a fallback hides it)."""
    n = 0
    for rid in run_ids:
        rec = r2.record(hub, rid)
        n += sum(str(x.get("kind") or "") in QUOTA_KINDS for x in rec.get("attempts") or [])
    return n


def markers(repo: Path) -> int:
    """Conflict markers left in the checkout's files."""
    r = subprocess.run(["git", "grep", "-I", "-n", "-E", "^(<<<<<<<|>>>>>>>) ", "--", "."], cwd=repo,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return len([x for x in r.stdout.splitlines() if x.strip()])


def score_batch(repo: Path, mat: dict, scratch: Path, python: str | None = None, job: PF.Job | None = None) -> dict:
    """The hidden nodes on the final tree: per change, all its nodes pass; all-right, every change right and no
    node that passed at the start fails now (a regression)."""
    spec = TB.REPOS.get(mat["repo"]) if mat["repo"] != "this" else None
    n_mark = markers(repo)
    put_tests(repo, mat["hidden"], spec, mat["end_tar"], keep=mat["changed"])
    skip = {*(mat.get("deselect") or []), *(mat.get("failing_at_end") or [])}
    r = pytest_nodes(repo, mat["test_files"], spec, python or sys.executable, scratch, deselect=sorted(skip), job=job)
    tasks = {}
    for tid, ns in mat["nodes"].items():
        bad = sorted(set(ns) - r["passed"])
        tasks[tid] = {"ok": bool(ns) and not bad, "n": len(ns), "failed": bad[:5]}
    # a node left out of the run (flaky, or failing at the end itself) is not a regression
    regs = sorted(set(mat.get("start_passed") or []) - r["passed"] - skip)
    right = sum(v["ok"] for v in tasks.values())
    return {"ok": right == len(tasks) and not regs, "right": right, "n_tasks": len(tasks), "tasks_ok": tasks,
            "regressions": regs[:20], "n_regressions": len(regs), "conflict_markers": n_mark,
            "collect_errors": sorted(r["errors"]), "pytest": r["tail"]}


def make_repo(mat: dict, dest: Path) -> None:
    """The batch's start in a fresh one-commit repository (no history: nothing of the end is reachable), plus the
    install-time stubs (another repository) or today's tests/conftest.py (this one), committed."""
    spec = TB.REPOS.get(mat["repo"]) if mat["repo"] != "this" else None
    r2._rmtree(dest)
    if spec:
        ext_repo.repo_from_tar(mat["start_tar"], spec, dest)
        return
    BS.extract(mat["start_tar"], dest)
    (dest / "tests").mkdir(exist_ok=True)
    (dest / "tests" / "conftest.py").write_text(r5.CONFTEST, encoding="utf-8")
    ext_repo._git(dest, "init", "-q")
    ext_repo._git(dest, "add", "-A")
    ext_repo._git(dest, "commit", "-q", "--no-verify", "-m", "start")


def review_run_ids(hub: Path) -> set[str]:
    """The hub's independent-review runs: their ledger label is `review:<run id>` (their own run ids are ordinary
    timestamp ids), as r2.hub_cost tells them apart."""
    try:
        rows = r2.ledger.rows(r2.Paths(hub))
    except Exception:  # noqa: BLE001 — no ledger: no reviews
        return set()
    return {r.get("run_id") for r in rows if not r.get("type") and str(r.get("label") or "").startswith("review:")}


def cost_split(u: dict, by_model: dict, usd: float, ccx_usd: float) -> dict:
    """Lead $ and sub-agent $. ccx arms: the hub's ledger is the sub-agents'. builtin: the worker model's share of
    the lead's bill; this also holds Claude Code's own side calls on that model, which the other arms book as lead
    $ (`lead_worker_model_usd`, kept on every row, shows their size). A lead on the worker's model cannot be split:
    sub_usd and lead_only_usd are then None."""
    worker = round(sum(v for m, v in by_model.items() if r3.WORKER_MODEL in m), 6)
    out = {"lead_worker_model_usd": worker}
    if u["arm"] != "builtin":
        sub = ccx_usd
    elif r3.WORKER_MODEL in lead_of(u)[0]:
        out["cost_split"] = f"the lead runs on the worker's model ({r3.WORKER_MODEL}): no lead / sub-agent split"
        return {**out, "sub_usd": None, "lead_only_usd": None}
    else:
        sub = worker
    return {**out, "sub_usd": sub, "lead_only_usd": round(usd - sub, 6)}


def lead_unit(u: dict, a, b: dict, mat: dict, work: Path, repo: Path, hub: Path, iso: PF.Unit | None = None,
              env: dict | None = None, job: PF.Job | None = None) -> dict:
    """The lead on the whole batch: its row fields (cost split, requests, timeline)."""
    env = {**(env or PF.base_env()), "CCX_HUB": str(hub), "CCX_NO_QUOTA_PROBE": "1",
           "BASH_DEFAULT_TIMEOUT_MS": "900000", "BASH_MAX_TIMEOUT_MS": "1200000"}
    if spec_of(b):
        env = r5.task_env(batch_tasks(b)[0], env, r5.ext_python(a))
    argv = lead_argv(u, a.lead_budget) + (PF.lead_flags(iso) if iso else [])
    t0 = time.time()
    out, _err, rc, lines = run_timed(argv, input=lead_prompt(u, b, mat), cwd=repo, env=env, timeout=a.timeout,
                                     job=job)
    wall = round(time.time() - t0, 1)
    (work / f"{unit_key(u)}.stream.jsonl").write_text(out, encoding="utf-8")
    fin = r3.last_result(out)
    lm = r3.lead_metrics(out)
    cost = r2.hub_cost(hub)
    by_model = r3.model_split(fin.get("modelUsage") or {})
    lead_usd = float(fin.get("total_cost_usd") or 0)
    row = {"rc": rc, "wall_s": wall, "subtype": fin.get("subtype"), "lead_usd": round(lead_usd, 6),
           "by_model_usd": by_model, "ccx_usd": cost["usd"], "ccx_review_usd": cost["review_usd"],
           "ccx_agents": cost["agents"], "ccx_run_ids": cost["run_ids"], "usd": round(lead_usd + cost["usd"], 6),
           "lead_turns": fin.get("num_turns"), **lm, **timeline(lines, wall)}
    row.update(cost_split(u, by_model, row["usd"], cost["usd"]))
    # how much was handed away: built-in worker calls, or ccx runs in the ledger (review runs left out)
    reviews = review_run_ids(hub)
    row["ccx_ledger_rows"] = len([x for x in cost["run_ids"] if x not in reviews])
    row["delegated"] = lm["agent_calls"] if u["arm"] == "builtin" else row["ccx_ledger_rows"]
    row["ccx_quota_attempts"] = quota_attempts(hub, cost["run_ids"]) if cost["run_ids"] else 0
    row["quota_events"] = row["ccx_quota_attempts"] + row["rate_limit_rejected"] + row["backpressure"]
    if cost["run_ids"]:
        row["phases"] = r5.phase_wall(hub, cost["run_ids"], wall)
    return row


def unit_models(u: dict, row: dict) -> dict:
    model, effort = lead_of(u)
    out = {"lead": model, "lead_effort": effort, "builtin_worker": r3.WORKER_MODEL}
    seen = ((row.get("audit") or {}).get("init") or {}).get("model")
    if seen:
        out["lead_seen"] = seen
    if row.get("by_model_usd"):
        out["billed"] = sorted(row["by_model_usd"])
    return out


def unit_of(u: dict, a, b: dict, work: Path) -> PF.Unit:
    key = unit_key(u)
    guard = r5.ext_guard(batch_tasks(b)[0], a, work) if spec_of(b) else {}
    return PF.Unit(key=key, work=work, repo=work / key, hub=work / f"h-{key}", label=u["label"],
                   claude=a.claude_isolation, codex_home=Path(PF.codex_home_arg(a.codex_home)) if a.codex_home else None,
                   dsh=a.dsh_home, agents=tuple(r3.WORKER),
                   codex_workspace_tmp=getattr(a, "codex_workspace_tmp", False), **guard)


def run_unit(u: dict, a, mats: dict, work: Path) -> dict:
    """One batch x arm in its clean room (as r5.run_unit): the repository leaves the work dir after scoring, the
    stream is kept under .ccx/eval/batch/streams/<tag>/."""
    b, mat = TB.by_id(u["batch"]), mats[u["batch"]]
    iso = unit_of(u, a, b, work)
    repo, hub = iso.repo, iso.hub
    stream = work / f"{iso.key}.stream.jsonl"
    stream.unlink(missing_ok=True)
    row: dict = {**u, "tasks": mat["tasks"], "start": mat["start"][:12], "end": mat["end"][:12]}
    env = None
    before, job = PF.snapshot(), PF.Job()
    try:
        r2._rmtree(hub)
        make_repo(mat, repo)
        hinfo = r3.make_hub(hub)
        hinfo["memory_empty"] = PF.hub_memory_empty(hub)
        row["hub"] = hinfo
        env = PF.prepare(iso)
        row.update(lead_unit(u, a, b, mat, work, repo, hub, iso, env, job))
        row.update(r5.changed(repo))
        row.update(score_batch(repo, mat, work, r5.ext_python(a) if spec_of(b) else None, job))
        for rid in row.get("ccx_run_ids") or []:
            ccx_verify(rid, bool(row["ok"]), f"eval-batch merged-tree acceptance: {row['pytest']}", hub=hub, env=env)
        row["archived_sessions"] = archive_hub(hub, env=env)
    except Exception as e:  # noqa: BLE001 — recorded in the row; the clean-up below still runs
        row.update({"ok": False, "error": f"{type(e).__name__}: {e}"[:400]})
        row.setdefault("usd", 0.0)
        row.setdefault("wall_s", 0)
    finally:
        try:
            row["audit"] = PF.audit(iso, stream.read_text(encoding="utf-8") if stream.exists() else "")
        except Exception as e:  # noqa: BLE001
            row["audit"] = {"clean": False, "problems": [f"audit failed: {type(e).__name__}: {e}"[:200]],
                            "session_ids": []}
        if stream.exists():
            keep = OUT / "streams" / str(u.get("tag") or "untagged")
            keep.mkdir(parents=True, exist_ok=True)
            try:  # shutil.move: the work dir (temp) and the repo can be on different drives (os.replace cannot)
                shutil.move(str(stream), str(keep / stream.name))
            except OSError as e:
                row["audit"].setdefault("problems", []).append(f"stream not kept: {type(e).__name__}: {e}"[:200])
        row["leftovers"] = PF.after_unit(iso, before, job, row["audit"].get("session_ids") or [], keep_repo=False)
        if spec_of(b) and getattr(a, "ext_venv", None):
            # the Python that scores every unit is shared: something installed into it changes later units
            try:
                row["ext_venv_changed"] = r5.venv_state(r5.ext_python(a)) != a.ext_venv
            except Exception:  # noqa: BLE001
                row["ext_venv_changed"] = True
    rep = getattr(a, "preflight", None)
    if rep:
        row["fingerprint"] = PF.fingerprint(rep, iso, env, unit_models(u, row))
    return row


# ------------------------------------------------------------------ schedule, estimate, run

def schedule(reps: int, seed: int, batches: list[str], arms: list[str]) -> list[dict]:
    """Repeat by repeat: the batches in a shuffled order, and the arms of a batch in a shuffled order, so arms
    alternate in time (same period of the day for all of them)."""
    out = []
    for rep in range(1, reps + 1):
        rnd = random.Random(f"{seed}:batch:{rep}")
        bs = list(batches)
        rnd.shuffle(bs)
        for bid in bs:
            al = list(arms)
            rnd.shuffle(al)
            out += [{"exp": "batch", "rep": rep, "batch": bid, "arm": arm} for arm in al]
    return out


def estimate(u: dict) -> dict:
    """The dry-run's guess for one unit ($, wall s): not a measurement (EST_USD_PER_TASK)."""
    n = len(TB.by_id(u["batch"])["tasks"])
    model = lead_of(u)[0]
    f = next((v for k, v in LEAD_PRICE.items() if k in model), 1.0)
    return {"usd": round(EST_USD_PER_TASK[u["arm"]] * n * f, 2), "wall_s": EST_WALL_PER_TASK[u["arm"]] * n}


def spent(f: Path, tag: str | None = None) -> float:
    return round(sum(r.get("usd") or 0 for r in read_jsonl(f) if tag is None or r.get("tag") == tag), 4)


def prepare(todo: list[dict], a, tmp: Path) -> tuple[dict, list[str]]:
    """Every batch's material, before the first unit and before the paid canary, built in `tmp` (outside the work
    dir, removed after): the end and the other repositories' clones never sit next to a unit. A check cached by
    `check` with the same start tree, end, changes and check code (check_sha) saves the pytest runs. For another repository, its Python is checked as r5 does."""
    mats, probs = {}, []
    for bid in dict.fromkeys(u["batch"] for u in todo):
        b = TB.by_id(bid)
        try:
            m = build(b, tmp, a.ext_cache, r5.ext_python(a) if spec_of(b) else None, cached=load_cached(bid))
        except Exception as e:  # noqa: BLE001
            probs.append(f"{bid}: {type(e).__name__}: {e}"[:300])
            continue
        probs += [f"{bid}: {p}" for p in m["problems"]]
        mats[bid] = m
    ext = sorted({TB.by_id(bid)["repo"] for bid in mats if TB.by_id(bid).get("repo")})
    if ext:
        py = r5.ext_python(a)
        try:
            info = r5.python_info(py)
            a.ext_info = {"python": py, **info}
            needs = sorted({n for r in ext for n in TB.REPOS[r].get("needs") or ()})
            gone = r5.missing_modules(py, needs)
            if gone:
                probs.append(f"{py} cannot import {', '.join(gone)}: install them there or pass --ext-python")
            there = sorted(set(TB.REPOS[r]["module"] for r in ext) -
                           set(r5.missing_modules(py, [TB.REPOS[r]["module"] for r in ext])))
            if there:
                probs.append(f"{py} has {', '.join(there)} installed: its released code has the fixes")
            a.ext_venv = r5.venv_state(py)
        except Exception as e:  # noqa: BLE001
            probs.append(f"--ext-python {py}: {e}"[:300])
    return mats, probs


def cmd_run(a) -> int:
    out = Path(a.out) if a.out else RESULTS
    batches = a.batches.split(",") if a.batches else list(TB.IDS)
    bad_b = [x for x in batches if x not in TB.IDS]
    if bad_b:
        raise SystemExit(f"unknown batch(es): {', '.join(bad_b)} (known: {', '.join(TB.IDS)})")
    arms = a.arms.split(",") if a.arms else list(ARMS)
    bad = [x for x in arms if x not in ARMS]
    if bad:
        raise SystemExit(f"unknown arm(s): {', '.join(bad)} (known: {', '.join(ARMS)})")
    work = Path(a.workdir or (Path(tempfile.gettempdir()) / f"batch-{a.tag}"))
    done = {done_key(r) for r in read_jsonl(out)}
    lead = {"lead_model": a.lead_model or DEFAULT_LEAD[0], "lead_effort": a.lead_effort or DEFAULT_LEAD[1]}
    todo = []
    for u in schedule(a.reps, a.seed, batches, arms):
        u = {**u, "tag": a.tag, "seed": a.seed, **lead}
        u["label"] = f"eval-batch:{a.tag}:{u['rep']}:{u['batch']}:{u['arm']}{lead_suffix(u)}"
        if done_key(u) not in done:
            todo.append(u)
    est = [estimate(u) for u in todo]
    print(f"work dir: {work}  results: {out}  units: {len(todo)}  lead: {lead['lead_model']} {lead['lead_effort']}  "
          f"estimate: ${sum(e['usd'] for e in est):.2f}, {sum(e['wall_s'] for e in est) / 3600:.1f} h one after "
          f"another (a projection from round 5, not measured)", flush=True)
    if a.dry_run:
        for u, e in zip(todo, est):
            b = TB.by_id(u["batch"])
            print(f"[dry] {u['label']}  {len(b['tasks'])} changes ({b.get('repo') or 'this'}; overlap "
                  f"{b.get('overlap') or 'none'})  ~${e['usd']:.2f} ~{e['wall_s']}s")
        by_arm: dict = {}
        for u, e in zip(todo, est):
            by_arm[u["arm"]] = round(by_arm.get(u["arm"], 0) + e["usd"], 2)
        print(f"[dry] estimate by arm: {json.dumps(by_arm)}")
        return 0
    tmp = Path(tempfile.mkdtemp(prefix="ccx-batch-"))
    try:
        mats, probs = prepare(todo, a, tmp)
    finally:
        ext_repo._rmtree(tmp)
    for p in probs:
        print(f"[batch] {p}", flush=True)
    if probs:
        print("batches not ready: not starting (`batch.py check` shows the details)", flush=True)
        return 3
    pf_arms = sorted({FLAGS_ARM[x] for x in arms})
    rep = PF.run_checks(PF.options_from(a, pf_arms, work, canary_on=not a.no_canary, start=True,
                                        tasks_file=Path(TB.__file__)))
    for p in rep["problems"]:
        print(f"[preflight] {p}", flush=True)
    for w in rep.get("warnings") or []:          # not a problem, but the person must see it
        print(f"[preflight] *** {w} ***", flush=True)
    if not rep["ok"] and not a.force_unclean:
        print("preflight failed: not starting (fix the above, or --force-unclean to run anyway; it is recorded)",
              flush=True)
        return 3
    rep["lead"] = {"model": lead["lead_model"], "effort": lead["lead_effort"]}
    rep["batches_sha256"] = tasks_sha()           # tasks_batch.py and the hold-out briefs it uses
    work.mkdir(parents=True, exist_ok=True)
    (work / "preflight.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    a.preflight = rep
    need_codex = any(x in PF.CODEX_ARMS for x in pf_arms)
    ours = [PF._norm(work), PF._norm(f"eval-batch:{a.tag}:")]
    watch = PF.Watch(ours).start()
    lock, stop = threading.Lock(), threading.Event()
    run_usd = [0.0]

    def one(u):
        with lock:
            total = round(spent(out, a.tag) + (a.extra_spent or 0.0), 4)
            if stop.is_set() or total >= a.budget:
                if not stop.is_set():
                    print(f"budget ${a.budget} reached (tag {a.tag}: ${total:.3f}): stopping", flush=True)
                stop.set()
                return
        try:
            row = run_unit(u, a, mats, work)
        except Exception as e:  # noqa: BLE001
            row = {**u, "ok": False, "error": f"{type(e).__name__}: {e}"[:400], "usd": 0.0, "wall_s": 0}
        row["ts"] = time.time()
        if "fingerprint" not in row:
            row["fingerprint"] = PF.fingerprint(rep, None, None)
        between = PF.between_units(rep, need_codex, ours, watch.take())
        if between:
            row["between_units"] = between
        after = PF.codex_home_after(rep, need_codex)     # the eval Codex home after this unit
        if after is not None:
            row["codex_home_after"] = after
        row["env_clean"] = PF.env_clean(row, rep)
        why = list(between)
        if row.get("ext_venv_changed"):
            row["env_clean"] = False
            why.append(f"something was installed into {r5.ext_python(a)} during the unit (it scores every unit)")
        if (row.get("leftovers") or {}).get("unkilled"):
            why.append(f"processes that could not be killed: {row['leftovers']['unkilled']}")
        if why and not a.force_unclean:
            print(f"stopping: {'; '.join(why)[:400]}", flush=True)
            stop.set()
        with lock:
            append_jsonl(out, row)
            run_usd[0] += row.get("usd") or 0
            print(f"rep{u['rep']} {u['batch']:14} {arm_of(u):14} right={row.get('right')}/{row.get('n_tasks')} "
                  f"all={row.get('ok')} ${row.get('usd', 0):.3f} (lead ${row.get('lead_only_usd', 0) or 0:.3f}) "
                  f"{row.get('wall_s')}s wake={row.get('lead_wakeups')} idle={row.get('lead_idle_ratio')} "
                  f"conflicts={row.get('merge_conflicts')} quota={row.get('quota_events')} "
                  f"clean={row['env_clean']} run=${run_usd[0]:.3f}", flush=True)

    try:
        with ThreadPoolExecutor(max_workers=max(1, a.jobs)) as ex:
            list(ex.map(one, todo))
    finally:
        watch.close()
    rep["real_state_after"] = post = PF.real_state(PF.real_paths(), work)
    rep["postflight"] = "same" if post == rep["real_state"] else "changed"
    (work / "preflight.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    if post != rep["real_state"]:
        print(f"[postflight] the person's own state changed: {rep['real_state']} -> {post}", flush=True)
        return 4
    return 2 if stop.is_set() else 0


# ------------------------------------------------------------------ summary

def _med(xs):
    w = sorted(x for x in xs if x is not None)
    return w[len(w) // 2] if w else None


def _p90(xs):
    w = sorted(x for x in xs if x is not None)
    return w[-(-9 * len(w) // 10) - 1] if w else None


def cell(rs: list[dict]) -> dict:
    """One batch x arm over its repeats."""
    tasks: dict = {}
    for r in rs:
        for tid, v in (r.get("tasks_ok") or {}).items():
            d = tasks.setdefault(tid, [0, 0])
            d[0] += bool(v.get("ok"))
            d[1] += 1
    return {"n": len(rs), "reps": sorted(r.get("rep") for r in rs),
            "wall_med": _med(r.get("wall_s") for r in rs), "wall_p90": _p90(r.get("wall_s") for r in rs),
            "usd_med": _med(r.get("usd") for r in rs), "usd": round(sum(r.get("usd") or 0 for r in rs), 4),
            "lead_usd_med": _med(r.get("lead_only_usd") for r in rs), "sub_usd_med": _med(r.get("sub_usd") for r in rs),
            "right": [r.get("right") for r in rs], "n_tasks": _med(r.get("n_tasks") for r in rs),
            "all_right": sum(bool(r.get("ok")) for r in rs),
            "tasks_right": {t: f"{k}/{n}" for t, (k, n) in sorted(tasks.items())},
            "merge_conflicts": sum(r.get("merge_conflicts") or 0 for r in rs),
            "conflict_markers": sum(r.get("conflict_markers") or 0 for r in rs),
            "regressions": sum(r.get("n_regressions") or 0 for r in rs),
            "wakeups_med": _med(r.get("lead_wakeups") for r in rs), "turns_med": _med(r.get("lead_turns") for r in rs),
            "requests_med": _med(r.get("lead_requests") for r in rs),
            "lead_tokens_med": _med(r.get("lead_tokens") for r in rs),
            "idle_ratio_med": _med(r.get("lead_idle_ratio") for r in rs),
            "quota_events": sum(r.get("quota_events") or 0 for r in rs),
            "unclean": sum(r.get("env_clean") is False for r in rs)}


def arm_order(names) -> list[str]:
    base = lambda x: x.split(".", 1)[0]  # noqa: E731
    return sorted(set(names), key=lambda x: (ARMS.index(base(x)) if base(x) in ARMS else len(ARMS), x))


def paired(rows: list[dict]) -> dict:
    """Every two arms on the repeats they share of the same batch (tag, batch, rep): the per-unit differences B - A
    as they are, and per batch and over all of them how often B was faster, cheaper, right more often. n is said
    each time; there is no CI (a handful of batches)."""
    by: dict = {}
    for r in rows:
        by.setdefault((str(r.get("tag")), r.get("batch"), r.get("rep")), {})[arm_of(r)] = r
    arms = arm_order(arm_of(r) for r in rows)
    out = {}
    for i, A in enumerate(arms):
        for B in arms[i + 1:]:
            units = [(k, d[A], d[B]) for k, d in sorted(by.items(), key=lambda kv: tuple(map(str, kv[0])))
                     if A in d and B in d]
            if not units:
                continue
            diffs = [{"tag": k[0], "batch": k[1], "rep": k[2],
                      "wall_diff": round((y.get("wall_s") or 0) - (x.get("wall_s") or 0), 1),
                      "usd_diff": round((y.get("usd") or 0) - (x.get("usd") or 0), 4),
                      "right": [x.get("right"), y.get("right")], "all_right": [bool(x.get("ok")), bool(y.get("ok"))]}
                     for k, x, y in units]

            def counts(ds):
                return {"n": len(ds), f"{B}_faster": sum(d["wall_diff"] < 0 for d in ds),
                        f"{B}_cheaper": sum(d["usd_diff"] < 0 for d in ds),
                        f"{B}_more_right": sum((d["right"][1] or 0) > (d["right"][0] or 0) for d in ds),
                        f"{A}_more_right": sum((d["right"][0] or 0) > (d["right"][1] or 0) for d in ds),
                        "wall_diff_med": _med(d["wall_diff"] for d in ds),
                        "usd_diff_med": _med(d["usd_diff"] for d in ds)}
            per_batch = {bid: counts([d for d in diffs if d["batch"] == bid])
                         for bid in sorted({d["batch"] for d in diffs})}
            out[f"{A} vs {B}"] = {"diff_is": f"{B} - {A}", "all": counts(diffs), "by_batch": per_batch,
                                  "units": diffs,
                                  "note": f"{len(diffs)} paired units from {len(per_batch)} batch(es): plain "
                                          "counts, no CI (too few batches for a bootstrap)"}
    return out


def summarize(rows: list[dict]) -> dict:
    errors = [r for r in rows if "error" in r]
    rows = [r for r in rows if "error" not in r]
    cells: dict = {}
    for tag in sorted({str(r.get("tag")) for r in rows}):
        for bid in sorted({r.get("batch") for r in rows if str(r.get("tag")) == tag}):
            rs = [r for r in rows if str(r.get("tag")) == tag and r.get("batch") == bid]
            cells.setdefault(tag, {})[bid] = {arm: cell([r for r in rs if arm_of(r) == arm])
                                              for arm in arm_order(arm_of(r) for r in rs)}
    out = {"cells": cells, "paired": paired(rows), "error_rows": len(errors),
           "unclean_rows": sum(r.get("env_clean") is False for r in rows)}
    # the Codex Windows sandbox each row actually ran under: the rows without an error (as r5.py), whose arm's
    # preflight arm (FLAGS_ARM) starts Codex
    mix = PF.sandbox_mix(rows, lambda r: FLAGS_ARM.get(r.get("arm"), r.get("arm")) in PF.CODEX_ARMS)
    if mix:
        out["codex_windows_sandbox"] = mix
    return out


def cmd_summary(a) -> int:
    rows = [r for r in read_jsonl(Path(a.out) if a.out else RESULTS) if not a.tag or r.get("tag") == a.tag]
    res = summarize(rows)
    print(json.dumps(res, ensure_ascii=False, indent=1))
    note = (res.get("codex_windows_sandbox") or {}).get("note")
    if note:                                                  # batches under different sandboxes: say so loudly
        print(f"*** {note} ***", file=sys.stderr)
    return 0


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="build every batch's start and check it (no agent)")
    c.add_argument("--batches", default="")
    c.add_argument("--static", action="store_true", help="build and check without running pytest")
    c.add_argument("--ext-cache", default="")
    c.add_argument("--ext-python", default="")
    c.set_defaults(fn=cmd_check)
    r = sub.add_parser("run")
    r.add_argument("--tag", default="bt1")
    r.add_argument("--seed", type=int, default=71)
    r.add_argument("--reps", type=int, default=2, help="repeats of every batch x arm")
    r.add_argument("--batches", default="", help=f"comma-separated (default: all: {', '.join(TB.IDS)})")
    r.add_argument("--arms", default="", help=f"comma-separated (default: all: {', '.join(ARMS)})")
    r.add_argument("--budget", type=float, default=5.0, help="stop before a new unit once this tag's rows reach $")
    r.add_argument("--extra-spent", type=float, default=0.0)
    r.add_argument("--lead-model", default="", help=f"the lead's Claude model (default: {DEFAULT_LEAD[0]})")
    r.add_argument("--lead-effort", default="", help=f"the lead's effort (default: {DEFAULT_LEAD[1]})")
    r.add_argument("--jobs", type=int, default=1, help="units at the same time (a batch is parallel inside)")
    r.add_argument("--lead-budget", type=float, default=8.0, help="claude -p --max-budget-usd for one lead")
    r.add_argument("--out", default="")
    r.add_argument("--workdir", default="")
    r.add_argument("--timeout", type=int, default=5400)
    r.add_argument("--dry-run", action="store_true")
    r.add_argument("--no-canary", action="store_true",
                   help="skip the canaries: one tiny real lead and, when an arm starts Codex, one real Codex "
                        "T1 request that must run a shell command")
    r.add_argument("--ext-cache", default="")
    r.add_argument("--ext-python", default="")
    PF.add_options(r)
    r.set_defaults(fn=cmd_run)
    s = sub.add_parser("summary")
    s.add_argument("--tag", default=None)
    s.add_argument("--out", default="")
    s.set_defaults(fn=cmd_summary)
    return ap


def main(argv=None) -> int:
    a = parser().parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
