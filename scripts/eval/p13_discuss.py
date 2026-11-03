"""P0-13 preregistered discuss A/B. Default is planning only; paid runs require --execute.

python scripts/eval/p13_discuss.py --dry-run
python scripts/eval/p13_discuss.py summary
"""
from __future__ import annotations

import argparse
import contextlib
import json
import math
import shlex
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import preflight as PF  # noqa: E402
import r3  # noqa: E402
import r5  # noqa: E402
import tasks_r5  # noqa: E402
from common import ROOT, append_jsonl, archive_hub, read_jsonl  # noqa: E402
from ccx import ledger  # noqa: E402
from ccx.config import Paths  # noqa: E402

ARMS = ("nodiscuss", "discuss")
SELECTION = {
    "q-killed-spend": "Interrupted-run state, ledger idempotency and queue cost must agree.",
    "q-resume-session": "Queue recovery must reconnect a session across queue and run records.",
    "projects-refresh": "New refresh API, background process and single-scan guard coordinate with session start.",
    "dsh-archive": "Atomic archive data updates must coordinate archive, restore and resume interfaces.",
    "quota-stop-log": "New evidence schema connects quota detection, attempt recording and quota reporting.",
    "mem-report": "New usage schema and report API connect memory producers, consumers and the CLI.",
}
LEAD = ("sonnet", "medium")
WORKER = ("gpt-6-luna", "low")
DISCUSS_WITH = "codex,claude,deepseek"
# Planning allowances, not measured prices or spending caps. No price lookup starts a CLI.
EST = {"lead": 0.025, "worker": 0.06, "discuss": 0.15, "preflight": 0.04}


def main_checkout() -> Path:
    """A linked worktree writes measurements beside the main checkout's other evals."""
    dot = ROOT / ".git"
    if dot.is_file():
        text = dot.read_text(encoding="utf-8").strip()
        if text.startswith("gitdir:"):
            gd = (ROOT / text[7:].strip()).resolve()
            common = gd / "commondir"
            if common.is_file():
                return (gd / common.read_text(encoding="utf-8").strip()).resolve().parent
    return ROOT


def output(a) -> Path:
    return Path(a.out).resolve() if a.out else main_checkout() / ".ccx/eval/p13/p13-results.jsonl"


def schedule(ids: list[str], tag: str) -> list[dict]:
    # One round, serial pairs; alternate first arm to balance order 3:3.
    return [{"task": tid, "arm": arm, "round": 1, "tag": tag, "taskset": "r5",
             "label": f"eval-p13:{tag}:{tid}:{arm}"}
            for i, tid in enumerate(ids) for arm in (ARMS if i % 2 == 0 else ARMS[::-1])]


def unit_of(u: dict, a, work: Path) -> PF.Unit:
    # Same prompt paths in each pair, with fresh folders for each arm.
    key = f"1-{u['task']}"
    return PF.Unit(key=key, work=work, repo=work / key, hub=work / f"h-{key}", label=u["label"],
                   claude=a.claude_isolation, codex_home=Path(a.codex_home) if a.codex_home else None,
                   dsh="unit")


def commands(u: dict, iso: PF.Unit) -> tuple[list[str], list[str]]:
    ccx = [Path(sys.executable).as_posix(), (ROOT / "ccx.py").as_posix()]
    run = [*ccx, "run", "--to", "codex", "--model", WORKER[0], "--effort", WORKER[1],
           "--mode", "write", "--new", "--no-ab", "--force", "--no-escalate", "--no-fallback",
           "--no-subagents", "--no-worktree", "--review", "off", "--context", "off",
           "--from", "claude", "--label", u["label"], "--brief-file", (iso.repo / "p13-brief.txt").as_posix()]
    discuss = [*ccx, "discuss", "--with", DISCUSS_WITH, "--rounds", "1", "--tier", "T1",
               "--confirmed", "--from", "user", "--question-file", (iso.repo / "p13-question.txt").as_posix()]
    return discuss, run


def lead_argv(iso: PF.Unit, budget: float, planning: bool = False) -> list[str]:
    # Dry-run must work even on a machine without any agent installed, without locating a CLI.
    argv = (["claude", "-p", "--output-format", "stream-json", "--verbose", "--model", LEAD[0],
             "--effort", LEAD[1], "--tools", "Bash", "--permission-mode", "acceptEdits",
             "--allowed-tools", "Bash", "--strict-mcp-config", "--exclude-dynamic-system-prompt-sections",
             "--disable-slash-commands", "--max-budget-usd", str(budget)] if planning else
            r3.lead_argv("ccx", budget, *LEAD)) + PF.lead_flags(iso)
    # The lead dispatches exactly one run; coding belongs to the fixed worker in both arms.
    argv[argv.index("--tools") + 1] = "Bash"
    argv[argv.index("--allowed-tools") + 1] = "Bash"
    return argv


def lead_prompt(run: list[str]) -> str:
    return ("Execute the following command once with Bash and wait for it to finish. Do not edit files, "
            "inspect the repository, retry, resume, discuss or delegate any other work. Report its result.\n"
            f"Command: {shlex.join(run)}\nP13_RUN_ARGV={json.dumps(run)}\n")


def hub_stats(hub: Path, *, discussion_started: bool = False, worker_started: bool = False) -> dict:
    rows = [r for r in ledger.rows(Paths(hub)) if not r.get("type")]
    talks = [r for r in rows if str(r.get("label", "")).startswith("discuss:")]
    work = [r for r in rows if str(r.get("label", "")).startswith("eval-p13:")]
    def cost(rs, required=True):
        if not rs:
            return None if required else 0.0
        return round(sum(r["ae_usd"] for r in rs), 6) if all(
            isinstance(r.get("ae_usd"), (int, float)) and math.isfinite(r["ae_usd"]) for r in rs) else None
    talk_usd, worker_usd = cost(talks, discussion_started), cost(work, worker_started)
    total = cost(rows) if talk_usd is not None and worker_usd is not None else None
    return {"ccx_usd": total, "discuss_usd": talk_usd, "worker_usd": worker_usd,
            "ccx_run_ids": [r["run_id"] for r in rows], "worker_runs": len({r["run_id"] for r in work}),
            "worker_results": [{k: r.get(k) for k in ("run_id", "status", "kind", "ok")} for r in work],
            "discussion_runs": len({r["run_id"] for r in talks})}


def run_unit(u: dict, a, work: Path, rep: dict) -> dict:
    iso = unit_of(u, a, work)
    task = tasks_r5.by_id(u["task"])
    row = {**u, "ok": None, "outcome": "Unknown", "lead_model": LEAD[0], "lead_effort": LEAD[1], "lead_usd": 0.0,
           "lead_tokens": 0, "discuss_wall_s": 0.0, "protocol_ok": False}
    before, job, env, stream = PF.snapshot(), PF.Job(), None, ""
    discussion_started, worker_started, accounting_unknown = False, False, False
    start = time.monotonic()
    try:
        PF.rmtree(iso.hub)
        r5.make_repo(task, iso.repo)
        (iso.hub / "ccx").mkdir(parents=True)
        # Fresh hub, fixed tiers, no adaptation, reviews, escalation or provider fallback.
        (iso.hub / "ccx/tiers.toml").write_text(
            '[defaults]\nab_self_rate = 0\n[routing]\nmode = "auto"\n'
            '[sessions]\narchive = "manual"\n', encoding="utf-8")
        row["hub"] = {"memory_empty": PF.hub_memory_empty(iso.hub)}
        env = PF.prepare(iso)
        env.update(BASH_DEFAULT_TIMEOUT_MS=str(int(a.timeout * 1000)),
                   BASH_MAX_TIMEOUT_MS=str(int(a.timeout * 1000)))
        discuss, run = commands(u, iso)
        row["commands"] = {"run": run, "discuss": discuss if u["arm"] == "discuss" else None}
        brief = task["brief"]
        if u["arm"] == "discuss":
            (iso.repo / "p13-question.txt").write_text(
                "Propose and critique an implementation design for this task. Do not edit files.\n\n" + brief,
                encoding="utf-8")
            t0 = time.monotonic()
            print(shlex.join(discuss), flush=True)
            discussion_started = True
            out, err, rc, _ = PF.run(discuss, cwd=iso.repo, env=env, timeout=a.timeout, job=job)
            accounting_unknown = rc == -9  # the killed turn may have spent without reaching the ledger
            row["discuss_wall_s"] = round(time.monotonic() - t0, 3)
            (work / f"{u['task']}-{u['arm']}.discuss.json").write_text(out, encoding="utf-8")
            d = json.loads(out)
            row["discussion"] = d
            if rc or d.get("state") != "done" or not (d.get("result") or {}).get("recommendation"):
                raise RuntimeError(f"discussion did not finish: rc={rc} {err[-200:]}")
            if d.get("rounds") != 1 or not d.get("judge_independent") or any(
                    t.get("unparsed") for t in d.get("turns", [])):
                raise RuntimeError("discussion protocol not met")
            brief += "\n\nDiscussion conclusion (advice; implement the original requirements):\n" + json.dumps(
                d["result"], ensure_ascii=False, indent=2)
            row["discussion_attached"] = True
        (iso.repo / "p13-brief.txt").write_text(brief, encoding="utf-8")
        row["lead_usd"], row["lead_tokens"] = None, None
        print("lead dispatch: " + shlex.join(run), flush=True)
        worker_started = True
        out, err, rc, _ = PF.run(lead_argv(iso, a.lead_budget), input=lead_prompt(run), cwd=iso.repo,
                                 env=env, timeout=a.timeout, job=job)
        stream = out
        (work / f"{u['task']}-{u['arm']}.stream.jsonl").write_text(out, encoding="utf-8")
        fin = r3.last_result(out)
        row.update(r3.lead_metrics(out), rc=rc, lead_usd=fin.get("total_cost_usd"))
        if not fin.get("usage"):
            row["lead_tokens"] = None
        if rc or fin.get("is_error") or not fin:
            raise RuntimeError(f"lead failed: rc={rc} {err[-200:]}")
        st = hub_stats(iso.hub, discussion_started=discussion_started, worker_started=worker_started)
        # Count actual dispatch records, independent of command quoting, length or truncated Bash telemetry.
        row["ccx_runs"] = st["worker_runs"]
        if st["worker_runs"] != 1 or row["ccx_runs"] != 1 or row["lead_edits"] or row["ccx_resumes"]:
            raise RuntimeError("lead must dispatch exactly one ccx run without edits or retries")
        worker = st["worker_results"][0]
        if worker["status"] != "done" or worker["kind"] not in (None, "ok", "no_changes", "check_failed", "ok_self_checked"):
            raise RuntimeError(f"worker did not complete: status={worker['status']} kind={worker['kind']}")
        row["protocol_ok"] = True
        row.update(r5.score(iso.repo, task, work, job))
        row["outcome"] = "Right" if row["ok"] else "Wrong"
    except Exception as exc:  # keep failures and spend, never silently rerun a failed unit
        row["ok"], row["outcome"] = None, "Unknown"
        row["error"] = f"{type(exc).__name__}: {exc}"[:500]
    finally:
        row.update(hub_stats(iso.hub, discussion_started=discussion_started, worker_started=worker_started))
        if accounting_unknown:
            row["ccx_usd"], row["discuss_usd"] = None, None
        row["usd"] = (round(row["lead_usd"] + row["ccx_usd"], 6)
                      if row["lead_usd"] is not None and row["ccx_usd"] is not None else None)
        row["wall_s"] = round(time.monotonic() - start, 3)
        try:
            row["audit"] = PF.audit(iso, stream)
        except Exception as exc:
            row["audit"] = {"clean": False, "problems": [f"audit failed: {exc}"], "session_ids": []}
        row["fingerprint"] = PF.fingerprint(rep, iso, env, {"lead": LEAD, "worker": WORKER,
                                                          "discussion": DISCUSS_WITH, "discussion_tier": "T1"})
        if env:
            try:
                row["archived_sessions"] = archive_hub(iso.hub, env)
            except Exception as exc:
                row["archived_sessions"] = None
                row["audit"]["clean"] = False
                row["audit"].setdefault("problems", []).append(f"archive failed: {exc}")
        # Keep hub records and streams as evidence; work files do not carry into the next arm.
        evidence = work / "evidence" / u["task"] / u["arm"]
        try:
            evidence.parent.mkdir(parents=True, exist_ok=True)
            if iso.hub.exists():
                shutil.copytree(iso.hub, evidence)
        except OSError as exc:
            row["error"] = f"could not preserve hub evidence: {exc}"
        try:
            row["leftovers"] = PF.after_unit(iso, before, job, row["audit"].get("session_ids") or [], keep_repo=False)
        except Exception as exc:
            job.close()
            row["leftovers"] = {"snapshot": False, "error": str(exc), "unkilled": ["unknown"]}
    return row


def key(row: dict) -> tuple:
    return row.get("tag"), row.get("task"), row.get("round"), row.get("arm")


def estimate(units: list[dict]) -> float:
    return round(EST["preflight"] + sum(EST["lead"] + EST["worker"] +
                 (EST["discuss"] if u["arm"] == "discuss" else 0) for u in units), 2)


def plan(a, units: list[dict], work: Path) -> None:
    print(f"P13: {len(units)} units, one round; estimated ${estimate(units):.2f} including preflight allowance.")
    print("Estimate is an allowance, not a quote or hard cap; discussion format repair can add calls.")
    print("Lead sonnet/medium; worker gpt-6-luna/low; discussion codex,claude,deepseek T1, one round.")
    for tid, reason in SELECTION.items():
        print(f"task {tid}: {reason}")
    print(f"results: {output(a)}; log: {output(a).with_name('p13-run.log')}")
    print("Preflight: shared run_checks, Claude and Codex shell canaries (paid; never called by dry-run).")
    for u in units:
        iso = unit_of(u, a, work)
        discuss, run = commands(u, iso)
        print(f"[{u['task']} {u['arm']}] cwd={iso.repo}")
        if u["arm"] == "discuss":
            print(shlex.join(discuss))
            print("append discussion.result JSON to p13-brief.txt after the original task brief")
        print(shlex.join(lead_argv(iso, a.lead_budget, planning=True)))
        print("lead stdin: " + lead_prompt(run).strip())
    print("Not done: user approval, real canaries, paid units and scientific measurement.")


def cmd_run(a) -> int:
    ids = a.tasks.split(",") if a.tasks else list(SELECTION)
    if not ids or len(ids) != len(set(ids)) or any(t not in SELECTION for t in ids):
        raise ValueError("--tasks must contain distinct registered task IDs")
    if not a.tag or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_." for c in a.tag):
        raise ValueError("tag must be a simple name")
    work = Path(a.workdir or Path(tempfile.gettempdir()) / f"p13-{a.tag}").resolve()
    units = schedule(ids, a.tag)
    if a.dry_run:
        plan(a, units, work)
        return 0
    if not a.execute:
        plan(a, units, work)
        print("Not started: paid execution requires user approval, then --execute.")
        return 2
    if not a.codex_home:
        raise ValueError("--codex-home (dedicated eval home) is required")
    res = output(a)
    # A tag is one immutable attempt: no survivor/duplicate selection, no silent retries.
    if any(r.get("tag") == a.tag for r in read_jsonl(res)) or work.exists():
        raise ValueError("tag/workdir already used; preserve it and use a new registered run tag")
    res.parent.mkdir(parents=True, exist_ok=True)
    log = res.with_name("p13-run.log")
    with log.open("a", encoding="utf-8", newline="") as fh:
        class Tee:
            def write(self, s):
                sys.__stdout__.write(s)
                fh.write(s)
                return len(s)

            def flush(self):
                sys.__stdout__.flush()
                fh.flush()

        code = 1
        with contextlib.redirect_stdout(Tee()):
            try:
                plan(a, units, work)
                code = execute(a, units, work, res)
                return code
            except (ValueError, OSError) as exc:
                code = 2
                print(f"p13: {exc}", flush=True)
                return code
            finally:
                print(f"exit={code}", flush=True)


def execute(a, units: list[dict], work: Path, res: Path) -> int:
    if a.wait_quiet and not r5.wait_quiet(a.wait_quiet):
        print("wait-quiet expired or process listing failed; no units started")
        return 3
    rep = PF.run_checks(PF.Options(work=work, arms=["ccx"], jobs=1, claude=a.claude_isolation,
                                  codex_home=Path(a.codex_home), dsh="unit", canary=True, start=True,
                                  force_unclean=a.force_unclean))
    rep["lead"] = {"model": LEAD[0], "effort": LEAD[1]}
    rep["p13_script_sha256"] = PF.sha256_file(Path(__file__))
    print(json.dumps(rep, ensure_ascii=False), flush=True)
    if not rep["ok"] and not a.force_unclean:
        return 3
    work.mkdir(parents=True, exist_ok=True)
    (work / "preflight.json").write_text(json.dumps(rep, indent=2), encoding="utf-8")
    ours = [PF._norm(work)]
    watch = PF.Watch(ours).start()
    spent = EST["preflight"]  # conservative allowance; preflight accounting stays separate
    try:
        for u in units:
            if spent >= a.budget:
                print(f"budget ${a.budget:.2f} reached before {u['task']} {u['arm']}")
                return 4
            if a.wait_quiet and not r5.wait_quiet(a.wait_quiet, busy=lambda: r5._busy_now(ours)):
                return 3
            row = run_unit(u, a, work, rep)
            row["between_units"] = PF.between_units(rep, True, ours, watch.take())
            row["env_clean"] = PF.env_clean(row, rep) and not a.force_unclean
            row["fingerprint"]["p13_script_sha256"] = rep["p13_script_sha256"]
            append_jsonl(res, row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
            if row["usd"] is None:
                print("unknown spend: stopping before further paid work")
                return 4
            spent += row["usd"]
            why = list(row["between_units"])
            if row["leftovers"].get("unkilled"):
                why.append("unkilled processes")
            if why and not a.force_unclean:
                if not (a.wait_quiet and all(w.startswith("busy") for w in why) and
                        r5.wait_quiet(a.wait_quiet, busy=lambda: r5._busy_now(ours))):
                    return 3
    finally:
        watch.close()
    return 0


def summarize(rows: list[dict], include_unclean: bool = False) -> dict:
    def unknown(r):
        return r.get("ok") is None or r.get("outcome") == "Unknown" or bool(r.get("error")) or r.get("protocol_ok") is not True
    eligible = [r for r in rows if r.get("env_clean") is True and r.get("protocol_ok") is True
                and not unknown(r)]
    table = rows if include_unclean else eligible
    arms = {}
    for arm in ARMS:
        rs = [r for r in table if r.get("arm") == arm]
        known = [r for r in rs if not unknown(r)]
        ok = sum(r.get("ok") is True for r in known)
        def total(k):
            return round(sum(r[k] for r in rs), 6) if rs and all(
                isinstance(r.get(k), (int, float)) and math.isfinite(r[k]) for r in rs) else None
        usd = total("usd")
        arms[arm] = {"ok": ok, "n": len(known), "right": f"{ok}/{len(known)}", "usd": usd,
                     "unknown": sum(unknown(r) for r in rows if r.get("arm") == arm),
                     "cps": round(usd / ok, 6) if ok and usd is not None and len(known) == len(rs) else None,
                     **{k: total(k) for k in ("wall_s", "lead_tokens", "lead_usd", "discuss_usd", "discuss_wall_s")}}
    # A conclusion needs exactly one complete clean six-pair run, all costs known.
    tags = {r.get("tag") for r in rows}
    expected = {(tid, arm) for tid in SELECTION for arm in ARMS}
    valid = (len(tags) == 1 and len(rows) == len(eligible) == 12 and
             {(r.get("task"), r.get("arm")) for r in eligible} == expected and
             all(r.get("round") == 1 for r in eligible))
    canonical = summarize(eligible, True)["arms"] if include_unclean and rows != eligible else arms
    base, talk = canonical["nodiscuss"], canonical["discuss"]
    delta = talk["ok"] - base["ok"]
    ratio = talk["cps"] / base["cps"] if talk["cps"] is not None and base["cps"] else None
    verdict = ("Useful" if delta >= 2 and ratio <= 1.5 else "Negative") if valid and ratio is not None else "Unknown"
    return {"arms": arms, "verdict": verdict, "success_delta": delta, "cps_ratio": ratio,
            "unknown": sum(unknown(r) for r in rows),
            "clean_complete_six_pairs": valid, "excluded_rows": len(rows) - len(eligible),
            "counted": "all rows (descriptive only)" if include_unclean else "clean protocol-valid rows",
            "selection": SELECTION, "estimated_usd": estimate(schedule(list(SELECTION), "p13")),
            "commands_after_approval": [
                "python scripts/eval/p13_discuss.py run --execute --tag p13-r1 --wait-quiet 30 --budget 2",
                "python scripts/eval/p13_discuss.py summary --tag p13-r1"],
            "requires": "CCX_EVAL_CODEX_HOME points to a dedicated logged-in eval home; DeepSeek key in environment",
            "not_done": "No real measurement is implied by dry-run or fake checks."}


def cmd_summary(a) -> int:
    rows = read_jsonl(output(a))
    if a.tag:
        rows = [r for r in rows if r.get("tag") == a.tag]
    result = summarize(rows, a.include_unclean)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("arm          right    USD       USD/success wall_s    lead_tokens discuss_USD Unknown")
    for arm, r in result["arms"].items():
        print(f"{arm:12} {r['right']:8} {str(r['usd']):9} {str(r['cps']):11} {str(r['wall_s']):9} "
              f"{str(r['lead_tokens']):11} {r['discuss_usd']} {r['unknown']}")
    return 0


def positive(value: str) -> float:
    n = float(value)
    if not math.isfinite(n) or n <= 0:
        raise argparse.ArgumentTypeError("must be finite and positive")
    return n


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run")
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--execute", action="store_true", help="paid run; only after explicit user approval")
    run.add_argument("--tag", default="p13-r1")
    run.add_argument("--tasks", default="", help="registered subset for smoke only; rule still requires six pairs")
    run.add_argument("--out", default="")
    run.add_argument("--workdir", default="")
    run.add_argument("--budget", type=positive, default=2.0, help="soft stop between units, includes canary allowance")
    run.add_argument("--lead-budget", type=positive, default=0.10)
    run.add_argument("--timeout", type=positive, default=1800)
    run.add_argument("--wait-quiet", type=r5._minutes, default=0, metavar="MINUTES")
    PF.add_options(run)
    run.set_defaults(fn=cmd_run)
    summary = sub.add_parser("summary")
    summary.add_argument("--out", "--results", default="")
    summary.add_argument("--tag", default="")
    summary.add_argument("--include-unclean", action="store_true")
    summary.set_defaults(fn=cmd_summary)
    return ap


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0].startswith("-"):
        argv.insert(0, "run")
    a = parser().parse_args(argv)
    try:
        return a.fn(a)
    except (ValueError, OSError) as exc:
        print(f"p13: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
