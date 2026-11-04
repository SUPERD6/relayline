"""Experimental P4 long sessions. No model call without --run; defaults stay unchanged.

Each episode has four tasks in one persistent Claude conversation per arm. Tasks
are interleaved between arms; the repository is rebuilt at each reference parent.
Hidden scoring happens in a separate directory and is never sent to the lead.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import shutil
import statistics
import sys
import tempfile
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
import r5
import preflight as PF
import ext_repo as E
import evidence_streams as ES
import long_check as LC
import tasks_long as TASKS
from common import ROOT, append_jsonl, read_jsonl

ARMS = ("self", "ccxlong")
N = 4
LIMITATION = "Delegation and one-line acceptance change together; their effects are not separated."


def schedule(tasks: list[dict], rounds: int = 1) -> list[dict]:
    if len(tasks) % N:
        raise ValueError("episodes must contain exactly four tasks")
    result = []
    for rd in range(1, rounds + 1):
        for ep, start in enumerate(range(0, len(tasks), N), 1):
            group = tasks[start:start + N]
            if len({t["repo"] for t in group}) != 1:
                raise ValueError("an episode must use one repository")
            for turn, task in enumerate(group, 1):
                # Same task order in both arms; alternate who runs first.
                for arm in (ARMS if (rd + ep + turn) % 2 else ARMS[::-1]):
                    result.append({"round": rd, "episode": ep, "turn": turn,
                                   "task": task["id"], "arm": arm})
    return result


def estimate(units: list[dict]) -> dict:
    # Historical r5 tasks were about 40 changed code lines. Scale by the
    # frozen task's actual implementation size, not documentation/type stubs.
    details = []
    for u in units:
        task = TASKS.by_id(u["task"])
        lines, files = task.get("code_lines", 40), len(task["code"])
        scale = max(1, lines / 40, files / 2)
        base = r5.UNIT_USD["self" if u["arm"] == "self" else "ccx2"]
        details.append({"task": u["task"], "arm": u["arm"], "code_lines": lines, "code_files": files,
                        "size_multiplier": scale, "usd": round(base * scale * 1.5, 6)})
    by_arm = {a: round(sum(x["usd"] for x in details if x["arm"] == a), 4) for a in ARMS}
    return {"usd": round(sum(by_arm.values()), 4), "by_arm": by_arm,
            "tasks": details,
            "method": "r5 means self=$0.20, ccx2=$0.12 x max(1, code_lines/40, code_files/2) x1.5 context; API-equivalent USD",
            "uncertainty": "Unknown: larger external changes and resumed context have not been measured",
            "historical_source": "scripts/eval/r5.py UNIT_USD (r5 tags; ccx2 r5c-r5h)"}


def task_caps(a, arm: str) -> tuple[float, float]:
    legacy = getattr(a, "task_cap", None)
    if legacy is not None:
        return (legacy, 0.0) if arm == "self" else (legacy / 2, legacy / 2)
    return float(getattr(a, "lead_budget", 1.5)), (float(getattr(a, "child_budget", 1.5)) if arm == "ccxlong" else 0.0)


def budget_envelope(a) -> dict:
    lead, child = task_caps(a, "ccxlong")
    return {"budget_usd": a.budget, "lead_allowance_usd": lead, "child_allowance_usd": child,
            "max_task_reservation_usd": lead + child, "overrun_allowance_usd": lead + child,
            "operational_upper_usd": a.budget + lead + child, "absolute_hard_cap": False,
            "basis": "reserve lead+child before each task; allow one final overrun allowance per role; CLI caps are step-boundary checks, not a provider billing guarantee"}


@dataclass
class Budget:
    cap: float
    spent: float = 0.0
    unknown: bool = False

    def reserve(self, amount: float) -> bool:
        return not self.unknown and amount > 0 and self.spent + amount <= self.cap + 1e-9

    def charge(self, amount: float | None) -> None:
        if amount is None or not math.isfinite(amount) or amount < 0:
            self.unknown = True
        else:
            self.spent += amount


def prompt(task: dict, arm: str, child_cap: float, receipt: Path | None = None) -> str:
    common = ("The repository has been reset to a different historical parent for this task. "
              "Earlier code changes are intentionally absent; conversation context is preserved. "
              "Implement only the request below. Do not fetch history or packages, commit, or inspect other "
              "sessions, grading files, or evaluation artifacts. Run relevant existing tests, using "
              "python -m pytest -q -o addopts= with PYTHONPATH=. . Do not change existing tests.\n\n"
              + task["brief"] + "\n\n")
    if arm == "self":
        how = "Do all implementation and checking yourself. Do not use Agent, ccx, or another model/CLI."
    else:
        ccx = f'python "{(receipt or Path(__file__).with_name("p4_receipt.py")).as_posix()}"'
        how = ("Do not edit code yourself. Delegate the request verbatim to Codex through ccx. "
               "Use the shipped default tradeoff (omit --tradeoff), review and routing; run synchronously:\n"
               f'{ccx} run --to codex --mode write --context auto --new --no-ab '
               f'--max-usd {child_cap:g} --check "python -m pytest -q -o addopts=" "<verbatim request>"\n'
               "CCX_LEAD_VIEW=line enables the existing compact receipt. If receipt ok=true, accept that one "
               "line and finish: do not read files, diff, full result, or rerun checks. Only if receipt ok is not "
               "true may you use ccx show <run_id> and ccx resume <run_id> to diagnose or request a repair; "
               "any repair shares the remaining delegation allowance, never increase it. Do not use another "
               "delegation path or run in the background.")
    return common + how + "\nFinish with one line DONE: <summary>."


def lead_argv(unit: PF.Unit, sid: str, turn: int, cap: float) -> list[str]:
    argv = r5.r3.lead_argv("ccx", cap, "sonnet", "medium") + PF.lead_flags(unit)
    return argv + (["--session-id", sid] if turn == 1 else ["--resume", sid])


def telemetry(stream: str) -> dict:
    messages = {}
    for event in PF._events(stream):
        if event.get("type") == "assistant" and not event.get("parent_tool_use_id"):
            message = event.get("message") or {}
            usage = message.get("usage")
            if usage:
                messages[message.get("id") or len(messages)] = usage
    contexts = [sum(int(u.get(k) or 0) for k in ("input_tokens", "cache_read_input_tokens",
                                               "cache_creation_input_tokens")) for u in messages.values()]
    return {"context_tokens": contexts, "context_first": contexts[0] if contexts else None,
            "context_last": contexts[-1] if contexts else None,
            "cache_read_tokens": sum(int(u.get("cache_read_input_tokens") or 0) for u in messages.values()),
            "lead_usage": r5.TL.lead_stream(stream)["usage"]}


def reset_repo(repo: Path, tree: bytes) -> None:
    # Owned, disposable episode directory only; never git reset the source checkout.
    PF.rmtree(repo)
    E.repo_from_tar(tree, {"stubs": []}, repo)
    exclude = repo / ".git" / "info" / "exclude"
    with exclude.open("a", encoding="utf-8", newline="") as f:
        f.write("\n/.ccx-eval-tmp-*/\n")


def score(repo: Path, task: dict, material: dict, python: str) -> dict:
    # The live repo never contains hidden tests or their output. A separate copy
    # also prevents a later --resume from seeing a previous hidden test.
    with tempfile.TemporaryDirectory(prefix="p4-score-") as tmp:
        target = Path(tmp) / "repo"
        shutil.copytree(repo, target, ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache", ".ccx-eval-tmp-*"))
        E.restore_test_setup(target, material["tar"], {"test_dirs": ["tests"]})
        for rel, body in material["tests"].items():
            (target / rel).parent.mkdir(parents=True, exist_ok=True)
            (target / rel).write_bytes(body)
        # check_tree extracts a supplied tar; score the already assembled copy.
        return run_hidden(target, task["tests"], python)


def run_hidden(repo: Path, tests: list[str], python: str) -> dict:
    env = {**PF.base_env(), "PYTHONPATH": str(repo), "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
           "PYTHONDONTWRITEBYTECODE": "1", "PIP_NO_INDEX": "1"}
    out, err, rc, _ = PF.run([python, "-m", "pytest", "-q", "-o", "addopts=", "-p", "no:cacheprovider", *tests],
                             cwd=repo, env=env, timeout=180)
    text = out + err
    return {"ok": rc == 0, "rc": rc, "summary": text.strip().splitlines()[-1] if text.strip() else "empty",
            "output": text, "environment_error": rc not in (0, 1)}


class Episode:
    def __init__(self, key: str, a, material: dict, task: dict):
        self.sid = str(uuid.uuid4())
        other_roots = tuple(a.work / (prefix + other) for other in a.session_keys if other != key
                            for prefix in ("repo-", "hub-", "x-"))
        grade_files = (a.out, a.out.with_suffix(".pending.jsonl"), a.out.with_suffix(".events.jsonl"))
        self.iso = PF.Unit(key, a.work, a.work / ("repo-" + key), a.work / ("hub-" + key),
                           claude="config-dir", codex_home=Path(a.codex_home), codex_workspace_tmp=True,
                           hidden=(a.ext_cache, a.artifacts, *other_roots, *grade_files),
                           deny=("WebFetch", "WebSearch", *(f"Read({PF._rule_path(p)})" for p in grade_files)),
                           flags=(*r5.EXT_FLAGS, r"git\s+(?:fetch|clone|pull)"))
        self.before, self.job = PF.snapshot(), PF.Job()
        self.wall = 0.0
        self.lead_total = 0.0
        self.child_total = 0.0
        self.review_total = 0.0
        self.run_ids = set()
        self.first_context = None
        self.last_context = None
        self.rows = []
        self.streams = []
        reset_repo(self.iso.repo, material["tar"])
        (self.iso.hub / "ccx").mkdir(parents=True)
        # Fresh hub, shipped settings: unlike r3.make_hub, no model holdbacks.
        self.memory_empty = PF.hub_memory_empty(self.iso.hub)
        self.env = {**PF.prepare(self.iso), **E.run_env({"pythonpath": "."}),
                    "CCX_LEAD_VIEW": "line", "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "CCX_P4_ROOT": str(ROOT)}
        self.receipt = self.iso.x / "p4_receipt.py"
        shutil.copy2(Path(__file__).with_name("p4_receipt.py"), self.receipt)
        self.python = a.ext_python
        self.env["PATH"] = str(Path(a.ext_python).parent) + os.pathsep + self.env["PATH"]

    def step(self, u: dict, task: dict, material: dict, a, cap: float) -> dict:
        reset_repo(self.iso.repo, material["tar"])
        row = {**u, "session_id": self.sid, "reference_commit": task["commit"], "repo": task["repo"],
               "env_clean": False, "ok": None, "usd": None, "cost_complete": False,
               "evidence": getattr(a, "evidence", "not run"),
               "lead_model": "sonnet", "lead_effort": "medium", "tmp_policy": "codex-workspace-private"}
        self.rows.append(row)
        lead_cap, child_cap = task_caps(a, u["arm"])
        self.env["CCX_P4_CHILD_LIMIT"] = str(child_cap)
        self.env["CCX_P4_CHILD_START"] = str(self.child_total)
        row["budget_envelope"] = budget_envelope(a)
        row.update({"lead_allowance_usd": lead_cap, "child_allowance_usd": child_cap,
                    "reservation_usd": lead_cap + child_cap})
        stream = a.work / f"{self.iso.key}-{u['turn']}.jsonl"
        t0 = time.monotonic()
        out, err, rc, _ = PF.run(lead_argv(self.iso, self.sid, u["turn"], lead_cap),
                                  input=prompt(task, u["arm"], child_cap, self.receipt), cwd=self.iso.repo, env=self.env,
                                  timeout=a.timeout, job=self.job)
        row["wall_s"] = round(time.monotonic() - t0, 3)
        self.wall += row["wall_s"]
        row["episode_wall_s"] = round(self.wall, 3)
        stream.write_text(out, encoding="utf-8", newline="")
        stream.with_suffix(".stderr").write_text(err, encoding="utf-8", newline="")
        self.streams.append((stream, row))
        fin = r5.r3.last_result(out)
        # Keep per-invocation usage and raw CLI cost; real resumed cost semantics
        # are unverified; retain this evidence limit with explicit budgeted runs.
        row.update(telemetry(out))
        row["session_match"] = fin.get("session_id") == self.sid
        total = fin.get("total_cost_usd")
        row["lead_reported_usd"] = total
        lead = float(total) if total is not None else None
        row["cost_basis"] = "CLI result per invocation; real resume scope unverified"
        child = r5.r2.hub_cost(self.iso.hub)
        row.update({"rc": rc, "subtype": fin.get("subtype"), "lead_usd": lead,
                    "ccx_usd": round(child["usd"] - self.child_total, 6),
                    "ccx_review_usd": round(child["review_usd"] - self.review_total, 6),
                    "ccx_run_ids": [rid for rid in child["run_ids"] if rid not in self.run_ids]})
        self.child_total = child["usd"]
        self.review_total = child["review_usd"]
        self.run_ids.update(child["run_ids"])
        row["known_usd"] = row["ccx_usd"] + (lead or 0)
        if lead is not None:
            row["usd"] = round(lead + row["ccx_usd"], 6)
            row["cost_complete"] = True
            self.lead_total += lead
        if not row["session_match"]:
            row.update({"cost_complete": False, "usd": None, "environment_error": True})
        row["episode_usd"] = round(self.lead_total + self.child_total, 6) if row["cost_complete"] else None
        if self.first_context is None:
            self.first_context = row["context_first"]
        row["context_growth_tokens"] = (row["context_last"] - self.first_context
                                         if row["context_last"] is not None and self.first_context is not None else None)
        audit = PF.audit(self.iso, out)
        row["audit"] = audit
        redactor = ES.Redactor(self.iso, self.env)
        dest = a.artifacts / f"{self.iso.key}-{u['turn']}"
        dest.mkdir(parents=True)
        row["streams"] = ES.keep(dest / "streams", self.iso, stream, self.env)
        (dest / "stderr.txt").write_text(redactor.text(err), encoding="utf-8", newline="")
        diff = r5.final_diff(self.iso.repo)
        if diff is not None:
            (dest / "diff.patch").write_text(redactor.text(diff), encoding="utf-8", newline="")
        # No raw stream from another arm remains next to its live workspace.
        stream.unlink(missing_ok=True)
        stream.with_suffix(".stderr").unlink(missing_ok=True)
        scoring_start = time.monotonic()
        sc = score(self.iso.repo, task, material, self.python)
        row.update({"ok": sc["ok"], "pytest": sc["summary"], "score_rc": sc["rc"],
                    "environment_error": sc["environment_error"] or not row["session_match"],
                    "score_wall_s": time.monotonic() - scoring_start})
        (dest / "hidden.txt").write_text(redactor.text(sc["output"]), encoding="utf-8", newline="")
        return row

    def close(self, rep: dict, between: list[str]) -> None:
        cleanup = PF.after_unit(self.iso, self.before, self.job, [self.sid], keep_repo=False)
        for row in self.rows:
            row.update({"leftovers": cleanup, "hub": {"memory_empty": self.memory_empty},
                        "between_units": between, "fingerprint": PF.fingerprint(rep, self.iso, self.env),
                        "pinned_commit": rep["commit"]})
            row["env_clean"] = PF.env_clean(row, rep) and not row.get("environment_error", False)
        for stream, _ in self.streams:
            stream.unlink(missing_ok=True)
            stream.with_suffix(".stderr").unlink(missing_ok=True)


def _ratio(numerator, denominator):
    return {"numerator": numerator, "denominator": denominator,
            "ratio": numerator / denominator if numerator is not None and denominator else None}


def summary(rows: list[dict], expected: int, limits: dict | None = None) -> dict:
    evidence = {r.get("evidence", "not run") for r in rows}
    result = {"evidence": next(iter(evidence)) if len(evidence) == 1 else "not run",
              "limitation": LIMITATION}
    result["budget_envelope"] = limits or next((r["budget_envelope"] for r in rows if r.get("budget_envelope")), None)
    for name, subset in (("all", rows), ("env_clean", [r for r in rows if r.get("env_clean") is True])):
        arms = {}
        for arm in ARMS:
            rs = [r for r in subset if r["arm"] == arm]
            wall = [r["wall_s"] for r in rs if r.get("wall_s") is not None]
            arms[arm] = {"attempted": len(rs), "right": sum(r.get("ok") is True for r in rs),
                         "cost_known_usd": round(sum(r.get("usd") if r.get("usd") is not None else
                                                      r.get("known_usd", 0) for r in rs), 6),
                         "cost_unknown": sum(not r.get("cost_complete") for r in rs),
                         "wall_median_s": statistics.median(wall) if wall else None,
                         "wall_total_s": sum(wall), "episodes": {}}
            groups = {}
            for r in rs:
                groups.setdefault((r.get("tag"), r["round"], r["episode"]), []).append(r)
            arms[arm]["episodes"] = {"/".join(map(str, k)): {"tasks": len(v), "right": sum(x.get("ok") is True for x in v),
                                        "usd": sum(x.get("usd") or 0 for x in v),
                                        "wall_s": sum(x.get("wall_s") or 0 for x in v)} for k, v in groups.items()}
        s, c = arms["self"], arms["ccxlong"]
        ratios = {"cost": _ratio(c["cost_known_usd"], s["cost_known_usd"]),
                  "right": _ratio(c["right"], s["right"]),
                  "wall_median": _ratio(c["wall_median_s"], s["wall_median_s"])}
        complete = all(arms[a]["attempted"] == expected and not arms[a]["cost_unknown"] for a in ARMS)
        # Paired identity, not only equal denominators.
        keys = [{(r.get("tag"), r["round"], r["episode"], r["task"]) for r in subset if r["arm"] == a} for a in ARMS]
        complete = complete and keys[0] == keys[1] and len(keys[0]) == expected
        complete = complete and ratios["cost"]["ratio"] is not None and ratios["wall_median"]["ratio"] is not None
        vals = {"cost": ratios["cost"]["ratio"] is not None and ratios["cost"]["ratio"] <= .8,
                "right": c["right"] >= s["right"],
                "wall_median": ratios["wall_median"]["ratio"] is not None and ratios["wall_median"]["ratio"] <= 2}
        verdict = "Unknown" if not complete or any(r.get("environment_error") for r in subset) else (
            "Pass" if all(vals.values()) else "Fail")
        result[name] = {"arms": arms, "ratios": ratios, "thresholds": {"cost": .8, "right": "ccxlong >= self", "wall_median": 2},
                        "expected_per_arm": expected, "verdict": verdict}
    return result


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    action = p.add_mutually_exclusive_group()
    action.add_argument("--run", action="store_true")
    action.add_argument("--dry-run", action="store_true")
    action.add_argument("--summary", action="store_true")
    p.add_argument("--split", choices=("dev", "final", "all"), default="all")
    p.add_argument("--rounds", type=int, default=1)
    p.add_argument("--budget", type=float, default=None, help="must be explicit with --run; dry-run defaults to $12")
    p.add_argument("--lead-budget", type=float, default=1.5, help="Claude --max-budget-usd for each resumed invocation")
    p.add_argument("--child-budget", type=float, default=1.5, help="ccx --max-usd per task, including review and repairs")
    p.add_argument("--task-cap", type=float, default=None, help="legacy total task allowance; overrides lead/child split when explicitly supplied")
    p.add_argument("--pin-commit", default="")
    p.add_argument("--wait-quiet", type=float, default=0)
    p.add_argument("--tag", default="p4")
    p.add_argument("--out", type=Path, default=ROOT / ".ccx" / "eval" / "p4" / "results.jsonl")
    p.add_argument("--workdir", type=Path)
    p.add_argument("--ext-cache", type=Path)
    p.add_argument("--ext-python", default=sys.executable)
    p.add_argument("--timeout", type=int, default=1200)
    PF.add_options(p)
    p.set_defaults(claude_isolation="config-dir", codex_workspace_tmp=True)
    return p


def main(argv=None) -> int:
    a = parser().parse_args(argv)
    explicit_budget = a.budget is not None
    a.budget = 12.0 if a.budget is None else a.budget
    if a.run and not explicit_budget:
        raise SystemExit("--run requires explicit --budget; this is a bounded step budget, not an absolute hard cap. No model was called.")
    if (not math.isfinite(a.budget) or a.budget <= 0
            or any(not math.isfinite(x) or x <= 0 for x in (a.lead_budget, a.child_budget))
            or (a.task_cap is not None and (not math.isfinite(a.task_cap) or a.task_cap <= 0))
            or a.rounds < 1 or not math.isfinite(a.wait_quiet) or a.wait_quiet < 0):
        raise SystemExit("budget, task-cap and rounds must be positive; wait-quiet must be finite and nonnegative")
    tasks = [t for t in TASKS.T if a.split == "all" or t["split"] == a.split]
    units = schedule(tasks, a.rounds)
    previous = [r for r in read_jsonl(a.out) if r.get("tag") == a.tag]
    if a.summary:
        ids = {t["id"] for t in tasks}
        selected = [r for r in previous if r.get("task") in ids]
        limits = budget_envelope(a) if explicit_budget or not selected else None
        print(json.dumps(summary(selected, expected_count(a), limits), indent=2))
        return 0
    head = r5.git(ROOT, "rev-parse", "HEAD").strip()
    if a.pin_commit and a.pin_commit != head:
        raise SystemExit("--pin-commit does not match HEAD")
    if previous:
        raise SystemExit("tag already has attempts; use a new tag (never silently restart a lost long session)")
    plan = {"units": units, "estimate": estimate(units), "budget_usd": a.budget,
            "budget_envelope": budget_envelope(a), "available_tasks": len(tasks), "target_tasks": expected_count(a) // a.rounds,
            "pinned_commit": head, "tasks_sha256": PF.sha256_file(Path(TASKS.__file__)),
            "selection_sha256": PF.sha256_file(TASKS.SELECTION_FILE),
            "cli_checked": "Claude Code 2.1.316 --help (2026-11-04): --session-id, --resume, -p; live resume not run",
            "limitation": LIMITATION, "run": a.run,
            "budget_semantics": "before a task: spent + lead allowance + child allowance <= budget; unknown accounting stops; operational overrun envelope is not an absolute provider hard cap"}
    print(json.dumps(plan, indent=2), flush=True)
    if not a.run:
        return 0
    a.evidence = "measured"
    return run_experiment(a, tasks, units)


def expected_count(a, fallback: int = 0) -> int:
    split = getattr(a, "split", None)
    return {"dev": 4, "final": 8, "all": 12}[split] * a.rounds if split else fallback


def run_experiment(a, tasks: list[dict], units: list[dict]) -> int:
    """Execution engine; only the explicit --run --budget CLI path invokes it."""
    if not a.ext_cache or not a.codex_home:
        raise ValueError("--ext-cache and a dedicated --codex-home are required")
    a.work = (a.workdir or Path(tempfile.gettempdir()) / ("p4-" + uuid.uuid4().hex)).resolve()
    a.out = a.out.resolve()
    a.session_keys = {f"{u['round']}-{u['episode']}-{u['arm']}" for u in units}
    _, a.artifacts = r5.run_artifacts_dir(a.out)
    budget = Budget(a.budget)
    for previous in read_jsonl(a.out):
        budget.charge(previous.get("usd"))
        if previous.get("usd") is None:
            budget.spent += previous.get("known_usd", 0)
    # Read only the explicit bare clones before any model starts, keep solutions
    # in evaluator memory, and deny that cache to the agents.
    materials = {t["id"]: LC.material(a.ext_cache, t) for t in tasks}
    if a.wait_quiet and not r5.wait_quiet(a.wait_quiet):
        return 2
    rep = PF.run_checks(PF.Options(a.work, ["self", "ccx2"], jobs=1, claude="config-dir",
                                  codex_home=Path(a.codex_home), canary=False, start=True,
                                  tasks_file=Path(TASKS.__file__), codex_workspace_tmp=True))
    if not rep["ok"]:
        return 2
    if a.pin_commit and a.pin_commit != rep["commit"]:
        raise ValueError("pin changed before run")
    sessions, rows = {}, []
    watcher = PF.Watch([str(a.work)]).start()
    between = []
    stopped = None
    not_started = None
    try:
        for u in units:
            lead_cap, child_cap = task_caps(a, u["arm"])
            if not budget.reserve(lead_cap + child_cap):
                stopped = "budget_unknown" if budget.unknown else "budget"
                not_started = {**u, "spent_known_usd": budget.spent, "lead_allowance_usd": lead_cap,
                               "child_allowance_usd": child_cap, "reservation_usd": lead_cap + child_cap}
                break
            if a.wait_quiet and not r5.wait_quiet(a.wait_quiet, busy=lambda: r5._busy_now([str(a.work)])):
                stopped = "busy"
                break
            task = next(t for t in tasks if t["id"] == u["task"])
            key = f"{u['round']}-{u['episode']}-{u['arm']}"
            session = sessions.get(key)
            try:
                if session is None:
                    session = Episode(key, a, materials[u["task"]], task)
                    sessions[key] = session
                row = session.step({**u, "tag": a.tag}, task, materials[u["task"]], a, lead_cap + child_cap)
            except (Exception, KeyboardInterrupt) as exc:
                # Keep a failed/interrupted attempt. A missing terminal receipt
                # is unknown cost, never a free attempt, and stops the run.
                child = r5.r2.hub_cost(session.iso.hub) if session else {"usd": 0}
                if session and session.rows and session.rows[-1].get("turn") == u["turn"]:
                    row = session.rows[-1]
                else:
                    row = {**u, "tag": a.tag, "usd": None, "cost_complete": False}
                    if session:
                        session.rows.append(row)
                row.update({"ok": None, "env_clean": False, "error": type(exc).__name__, "environment_error": True})
                row["known_usd"] = row.get("known_usd", 0) + max(0, child["usd"] - (session.child_total if session else 0))
                stopped = "interrupted_or_error"
            rows.append(row)
            budget.charge(row.get("usd"))
            if row.get("usd") is None:
                budget.spent += row.get("known_usd", 0)
            # Journal outside every agent's allowed roots; never inject a grade
            # into the session, ccx verify, shared memory, or the live repo.
            append_jsonl(a.out.with_suffix(".pending.jsonl"), row)
            between = PF.between_units(rep, True, ours=[str(a.work)], seen=watcher.take())
            if stopped or between or budget.unknown or budget.spent >= a.budget:
                stopped = stopped or ("environment" if between else "budget")
                break
    finally:
        watcher.close()
        for session in sessions.values():
            try:
                session.close(rep, between)
            except Exception as exc:
                for row in session.rows:
                    row.update({"env_clean": False, "cleanup_error": type(exc).__name__})
        for row in rows:
            append_jsonl(a.out, row)
        limits = {**budget_envelope(a), "spent_known_usd": budget.spent, "cost_unknown": budget.unknown,
                  "observed_overspend_usd": max(0, budget.spent - budget.cap)}
        append_jsonl(a.out.with_suffix(".events.jsonl"), {"event": "stop" if stopped else "complete", "reason": stopped,
                     "spent_known_usd": budget.spent, "cost_unknown": budget.unknown, "budget_usd": budget.cap,
                     "budget_envelope": limits, "not_started": not_started})
    print(json.dumps(summary(rows, expected_count(a, len(units) // 2), limits), indent=2))
    return 2 if stopped else 0


if __name__ == "__main__":
    raise SystemExit(main())
