"""Delegating work: run, ask, resume, batch, send, route, verify, A/B, task, plan."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .. import lanes, learn, ledger, merge, router, usage
from ..config import AGENTS, DELEGATE_AGENTS, PROVIDER_AGENTS, TIER_ORDER, load_config, paths
from ..delegate import Request, compact, exit_ok, human_summary, recap, run, verify
from ..gitstate import SHARED_WHY, STALE_WHY, clean, in_git
from ..runners import find_bin
from ..workspace import missing_test_paths
from .common import (_brief, _caller, _out, _routing_args, human_tail, _spec_from_args, _target, find_continuable,
    apply_mode, find_seat, installed_agents, lead_session_id, parse_quota, person_named_to, picked_tier,
    provider_agents, resolve, tier_policy)
from .install import tier_spec_safe
from ..plan import routing_mode
from ..subagents import parse_spec as subagents_spec


def cmd_ab(a) -> int:
    """Close an A/B self-run sample: sum the lead's own usage since the sample opened."""
    p = paths()
    f = p.state / "ab" / f"{a.ab_id}.json"
    if not f.exists():
        raise FileNotFoundError(f"no open A/B sample {a.ab_id}")
    s = json.loads(f.read_text(encoding="utf-8"))
    subs = {x for r in ledger.rows(p) if not r.get("type") for x in r.get("sessions", [])}
    w = usage.window_usage(s["caller"], s["ts"], None, subs, s.get("lead_session"))
    model = w["model"] or load_config(p).get("lead", {}).get(s["caller"], "")
    ae = learn.price_usd(p, s["caller"], model, w["usage"])
    row = {"type": "selfrun", "ab_id": s["id"], "agent": s["caller"], "model": model, "b": s["b"],
           "would_route": s["would_route"], "ok": bool(a.ok), "usage4": w["usage"],
           "messages": w["messages"], "ae_usd": None if ae is None else round(ae, 6),
           "seconds": round(time.time() - s["ts"], 1), "ts": time.time(),
           **{k: s[k] for k in ("trial", "bucket", "kind") if s.get(k)}}
    ledger.append_event(p, row)
    f.unlink()
    _out(row)
    return 0


# ---------------------------------------------------------------- commands
# a write run without --check: one line on stderr (PM review 2026-10-29); what ccx does is unchanged
# 2026-10-31 new-machine walkthrough: `--effort medium` without --model left the route's codex:gpt-6-luna:low as it
# was, and nothing said so. stderr only: the JSON a lead reads stays as it was.
EFFORT_ALONE_NOTE = ("ccx: --effort is used only together with --model (or --provider); without one the route picks the "
                     "model and its effort. To set the effort, name the model too (--model <m> --effort <e>), or pick "
                     "a tier (--tier T0..T4)")
NO_CHECK_NUDGE = ("ccx: tip: this run may edit files and has no --check; add --check \"<test command>\" so ccx re-runs "
                  "it and the result is checked, not only reported")


def _background(argv: list[str], p, procs: list | None = None) -> dict:
    """Re-run this exact command detached; the run id is fixed up front so the caller can poll it. `procs`, when
    given, gets the detached process (for `--bg --wait N`, which waits on it in the same call)."""
    from .common import detach
    run_id = ledger.new_run_id(p)                # its folder made here: no other run can draw the same id
    log = p.runs / run_id / "bg.log"
    proc = detach(_without_wait(argv), log, {"CCX_RUN_ID": run_id})
    if procs is not None:
        procs.append(proc)
    # peek: a look now, without waiting (it follows a review fix round too). Named `check` earlier: renamed so it
    # is not read as the acceptance check, which the result reports under `check`
    return {"run_id": run_id, "state": "started", "peek": f"ccx show {run_id}", "log": str(log),
            "next": f"ccx show {run_id} --wait"}     # blocks until done, under a 10-minute tool-call limit


def _without_wait(argv: list[str]) -> list[str]:
    """argv without `--wait N` / `--wait=N`: the detached child runs the work itself and must not wait on itself.
    argparse also took the unique prefixes `--wa` / `--wai` for it (no other run/resume option starts with
    `--wa`), so those go too; after a bare `--` every word is a positional and stays."""
    out, skip, rest = [], False, False
    for x in argv:
        name = x.split("=", 1)[0]
        if skip:
            skip = False
        elif rest or name not in ("--wa", "--wai", "--wait"):
            rest = rest or x == "--"
            out.append(x)
        elif "=" not in x:
            skip = True
    return out


def _bg_maybe_wait(argv: list[str], p, wait: float | None) -> int:
    """`--bg`: detach and print the run id. `--bg --wait N` (one call instead of `--bg` then `ccx show --wait`):
    the id goes to stderr at once (flushed: a lead whose tool call is cut off still has it), then this process waits
    up to N s. Finished: the final compact result on stdout (exit 0 / 2 as a foreground run). Not finished:
    exactly what plain --bg prints. A child that exits without writing its record (a crash before the run
    started) ends the wait at once with the end of its log; refusals write a finished record (_bg_refused /
    _bg_not_delegated) and end it the same way."""
    procs: list = []
    bg = _background(argv, p, procs)
    if wait is None:
        _out(bg)
        return 0
    from .records import RunWaiter
    rid = bg["run_id"]
    print(f"ccx: started {rid} in the background; waiting up to {wait:g} s (else: ccx show {rid} --wait)",
          file=sys.stderr, flush=True)
    proc = procs[0] if procs else None
    waiter = RunWaiter(p, rid)                   # the same polling as `ccx show --wait` (follows a fix round)
    from ..wake import waiting
    with waiting(p, rid):                        # the run sends no notice while this call reads its result
        return _wait_loop(p, rid, bg, proc, waiter, wait)


def _wait_loop(p, rid: str, bg: dict, proc, waiter, wait: float) -> int:
    from .. import recover
    from .records import POLL_SEC, _result
    deadline = time.time() + max(0.0, wait)
    swept = time.time()
    while True:
        rec = waiter.poll()
        if rec is not None:
            res = _result(rec, rid, waiter.rid, False)
            extra = _child_extras(proc, p.runs / rid / "bg.log", deadline)
            if extra:                            # what the foreground run adds after run(): route, L2 merge, ...
                rc = res.pop("recap", None)
                res.update({k: v for k, v in extra.items() if k not in res})
                if rc is not None:
                    res["recap"] = rc            # last key: survives `| tail`
            _out(res)
            return 0 if exit_ok(rec) else 2
        if time.time() - swept >= 20:            # a run whose ccx process died: interrupted, not running forever
            recover.sweep(p)
            swept = time.time()
        if proc is not None and proc.poll() is not None and not (p.runs / rid / "run.json").exists():
            tail = ""
            try:
                tail = (p.runs / rid / "bg.log").read_text(encoding="utf-8", errors="replace")[-2000:]
            except OSError:
                pass
            _out({"run_id": rid, "state": "failed", "ok": False, "exit": proc.returncode,
                  "error": "the background ccx process ended before the run started", "log": bg["log"],
                  "log_tail": tail.strip()})
            return 2
        if time.time() >= deadline:
            _out(bg)                             # exactly what plain --bg prints: the lead goes on as it would
            return 0
        time.sleep(min(POLL_SEC / 4, max(0.0, deadline - time.time())))


_CHILD_EXTRAS = ("continued_from", "route", "project", "autonomy")


def _child_extras(proc, log: Path, deadline: float) -> dict:
    """The keys a foreground `ccx run` adds to its result after the run record is final (`route`, `continued_from`,
    `project`, `autonomy` with the L2 merge outcome), taken from the detached child's own result at the end of its
    log once it has exited (waiting for that until the deadline, at least 30 s). {} when it is not there."""
    if proc is None:
        return {}
    try:
        proc.wait(timeout=max(30.0, deadline - time.time()))
    except Exception:  # noqa: BLE001 — still running (a slow merge): the result goes out without these keys
        return {}
    try:
        text = log.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    tops = list(re.finditer(r"(?m)^\{\r?$", text))   # _out's indent=2: only a top-level document starts a line
    if not tops:
        return {}
    try:
        doc = json.loads(text[tops[-1].start():])
    except ValueError:
        return {}
    return {k: doc[k] for k in _CHILD_EXTRAS if isinstance(doc, dict) and k in doc}


def _check_names_real_tests(check: str | None, cwd: Path) -> str | None:
    """Stop before any sub-agent is paid when --check names test files that are not there (pytest exit 4 later).
    A missing tests/X.py is swapped for the files tests/X_*.py that exist (a guessed short name; listed one by one, not
    a glob, so it works on Windows), else for its one near-identical match (a typo), with a one-line notice on stderr;
    otherwise the error lists the test files that do exist, so the lead can fix the check in one retry."""
    miss = missing_test_paths(check or "", cwd)
    if not miss:
        return check
    if all(m["prefix"] or len(m["sure"]) == 1 for m in miss):
        for m in miss:
            use = " ".join(m["prefix"] or m["sure"])
            check = re.sub(r"(?<![\w./\\-])" + re.escape(m["path"]) + r"(?![\w./\\-])", lambda _: use, check)
            print(f"ccx: --check names {m['path']}, which does not exist; using {use}", file=sys.stderr)
        return check
    tests = cwd / "tests"
    known = sorted(q.relative_to(cwd).as_posix() for q in tests.rglob("test*.py")) if tests.is_dir() else []
    shown = ", ".join(known[:40]) + (f", ... (+{len(known) - 40} more)" if len(known) > 40 else "")
    raise ValueError("--check names test files that do not exist in " + str(cwd) + ": " + "; ".join(
        m["path"] + (" (close: " + ", ".join(m["close"]) + ")" if m["close"] else " (no close match)")
        for m in miss) + ". Existing test files: " + (shown or "none"))


def _refused_off(p, cfg: dict, a, what: str) -> bool:
    """routing.mode=off (P0-9) without --force: print the refusal (JSON + a plain tail) and say so. Nothing starts,
    so the detached half of --bg records it finished, as a refused proposal does."""
    from ..plan import off_refusal, routing_mode
    out = off_refusal(cfg, bool(getattr(a, "force", False)), what)
    if not out:
        if routing_mode(cfg) == "off":           # --force: stderr only, the JSON a lead reads stays as it was
            print(f"ccx: routing.mode is off; {what} --force delegates this one anyway", file=sys.stderr, flush=True)
        return False
    _bg_refused(p, a, _caller(getattr(a, "caller", None)), out["advice"], next_step=out["hint"])
    _out(out)
    human_tail([f"Not delegated: {out['advice']}", "Cost: $0 (nothing ran)", f"Next: do it yourself, or {out['hint']}"])
    return True


def _bg_not_delegated(p, a, route: dict, caller: str) -> None:
    """The detached half of `ccx run --bg` whose routing says "do it yourself": no sub-agent starts, so nothing
    would ever write the run.json `ccx show <id> --wait` polls, and the lead waited out its whole timeout. Write a
    finished record instead (ok false, kind not_delegated, the advice as its summary). Only for that detached
    process: its id came in CCX_RUN_ID and _background made its folder; a foreground refusal is unchanged."""
    rid = os.environ.get("CCX_RUN_ID")
    if not rid or not (p.runs / rid / "bg.log").exists() or (p.runs / rid / "run.json").exists():
        return
    advice = route.get("advice") or "routing advised against delegating this task"
    rec = {"run_id": rid, "ts": time.time(), "state": "finished", "ok": False, "kind": "not_delegated",
           "to": route.get("to") or "-", "tier": route.get("tier") or "-",
           "mode": (route.get("mode") or {}).get("mode"), "caller": caller,
           "cwd": str(Path(a.cwd or os.getcwd()).resolve()), "label": getattr(a, "label", None) or "",
           "attempts": [], "route": route, "error": advice,
           "ephemeral": True,                       # no session, no spend: not a piece of work in stats or the ui
           "result": {"status": "not_delegated", "summary": advice,
                      "next_step": "do it yourself, or run it again with --force to delegate anyway"}}
    ledger.write_record(p.runs / rid, rec)


def _bg_refused(p, a, caller: str, error: str, cwd: str | None = None, to: str | None = None,
                next_step: str | None = None) -> None:
    """The detached half of `ccx run --bg` refused before any sub-agent starts (a pre-authorised proposal that is
    used up, sized smaller, or lapsed), or of `ccx resume --bg` whose session another run is working in: write a
    finished record so `ccx show <id> --wait` ends at once instead of waiting out its timeout. Only for that
    detached process; a foreground refusal stays an error."""
    rid = os.environ.get("CCX_RUN_ID")
    if not rid or not (p.runs / rid / "bg.log").exists() or (p.runs / rid / "run.json").exists():
        return
    rec = {"run_id": rid, "ts": time.time(), "state": "finished", "ok": False, "kind": "refused",
           "to": to or getattr(a, "to", None) or "-", "tier": getattr(a, "tier", None) or "-", "mode": None,
           "caller": caller, "route": {"proposal": getattr(a, "proposal", None)},
           "cwd": str(Path(cwd or getattr(a, "cwd", None) or os.getcwd()).resolve()),
           "label": getattr(a, "label", None) or "",
           "attempts": [], "error": error, "proposal": getattr(a, "proposal", None),
           "ephemeral": True,                       # no session, no spend: not a piece of work in stats or the ui
           "result": {"status": "refused", "summary": error,
                      "next_step": next_step or "run `ccx propose` again for this task, then run it with the new id"}}
    ledger.write_record(p.runs / rid, rec)


_BANDS = ("small", "medium", "large")


def _preauth_for_run(p, cfg: dict, proposal: str, spec: dict) -> dict | None:
    """The tier (as route["policy"]) when the person's picked tier pre-authorised `proposal` and this run may use
    it, else None. A pre-authorisation covers one run of that task: refused when the setting changed since, when a
    run already used it, or when this run is sized smaller than the proposal (its band would not have been sent out
    by the tier), and when the tier would not send this run's own brief out (its hard or uncertain rules plan it
    self). The returned policy keeps the proposal's tier and planned mode, with this run's band and estimate.
    Being used is claimed atomically when the run starts (proposals.claim), not here."""
    from .. import proposals
    pre = proposals.preauthorized(p, proposal)
    if not pre:
        return None
    if pre.get("tier") != picked_tier(cfg):
        raise ValueError(f"proposal {proposal} was pre-authorised by tier {pre.get('tier')}, which the "
                         "person's settings no longer pick (policy.picked): run `ccx propose` again and offer it")
    if proposals.answered(p, proposal) or proposals.claimed(p, proposal):
        raise ValueError(f"proposal {proposal} was pre-authorised for one run, which has already used it: run "
                         "`ccx propose` again for this task")
    own = tier_policy(p, cfg, {**spec, "files": int(spec.get("files") or 0)}, pre["tier"]) or {}
    if own.get("band") in _BANDS and pre.get("band") in _BANDS:
        if _BANDS.index(own["band"]) < _BANDS.index(pre["band"]):
            raise ValueError(f"proposal {proposal} was pre-authorised for a {pre['band']} task, but this run is "
                             f"sized {own['band']} (its --minutes / --files / brief): pass the estimate you proposed "
                             "with, or `ccx propose` this task on its own")
        pre = {**pre, "proposal_band": pre["band"], "band": own["band"], "signals": own.get("signals") or {}}
    if own.get("error") or (own.get("mode") and own["mode"] not in ("ccx2", "direct")):
        # re-plan this run's own brief: the tier's hard / uncertain rules apply to what is sent, not only its size
        why = own.get("error") or own.get("why") or ""
        raise ValueError(f"proposal {proposal} was pre-authorised by tier {pre['tier']}, but that tier plans this "
                         f"run's own task as {own.get('mode') or 'unplannable'}" + (f" ({why})" if why else "") +
                         ": a pre-authorisation covers the task it was proposed for; `ccx propose` this brief")
    return pre


def cmd_run(a) -> int:
    rid = os.environ.get("CCX_RUN_ID")          # the detached child of --bg (run() takes the variable away)
    if rid:                                      # nobody reads its stdout: tell the lead, however it ends (wake.py)
        from ..wake import after_bg
        with after_bg(paths(), rid):
            return _cmd_run(a)
    return _cmd_run(a)


def _cmd_run(a) -> int:
    p = paths()
    cfg = load_config(p)
    if getattr(a, "mode", None) != "read" and _refused_off(p, cfg, a, "ccx run"):
        return 0                                 # --mode read (a review, a second opinion) edits nothing: it runs
    proj = None
    if a.project:                                # into a project from the catalog (ccx/commands/projects.py)
        from .projects import for_run
        proj, stop = for_run(a)
        if stop:
            _out(stop)
            return 0
    auto = None
    if proj or a.autonomy:                       # a manager's dispatch: its autonomy level decides (K4)
        from .. import autonomy
        auto = autonomy.level_for(proj["name"] if proj else None, p, cfg, flag=a.autonomy)
    if a.check:
        a.check = _check_names_real_tests(a.check, Path(a.cwd or os.getcwd()))
    if a.bg and not a.brief and not a.brief_file:
        raise ValueError("--bg needs the task as text or --brief-file (stdin is not passed on)")
    if a.wait is not None and not a.bg:
        raise ValueError("--wait N goes with --bg (a foreground run already waits until it is done)")
    if a.effort and not a.model and not a.provider:
        print(EFFORT_ALONE_NOTE, file=sys.stderr, flush=True)
    if a.bg and not auto:
        if a.proposal:
            # refuse a used-up, smaller or lapsed pre-authorisation here, before detaching: the detached child's
            # refusal would leave `ccx show <id> --wait` waiting (it checks again, and records a refusal, below)
            _preauth_for_run(p, cfg, a.proposal, _spec_from_args(a, _brief(a)))
        if not a.check and apply_mode(_spec_from_args(a, _brief(a)))["mode"] == "write":
            print(NO_CHECK_NUDGE, file=sys.stderr, flush=True)     # here, where the person sees it
        return _bg_maybe_wait(sys.argv[1:], p, a.wait)
    text = _brief(a)
    caller = _caller(a.caller)
    spec = _spec_from_args(a, text)
    if person_named_to(caller, a.to, a.force) and not a.proposal and not (proj or a.autonomy):
        spec["person_to"] = True
    preauth, tier_self = None, False
    if a.proposal:
        from .. import proposals
        try:
            preauth = _preauth_for_run(p, cfg, a.proposal, spec)   # a tier the person picked, not a yes to it
        except ValueError as e:
            _bg_refused(p, a, caller, str(e))
            raise
        if preauth:
            spec["tier_preauth"] = True          # the tier decided who does it: no random A/B self-run, no trial
        else:
            # a proposal the picked tier planned "self" was never offered: sending it out is the lead's own call
            tier_self = proposals.tier_decided(proposals.get(p, a.proposal) or {})
    mode = apply_mode(spec)                      # before routing: start-up cost depends on read/write
    kw, route = resolve(spec, caller, p, cfg)
    route["mode"] = mode
    if a.proposal:
        if preauth:
            # the run row keeps the proposal's tier and planned mode, with this run's own band and estimate. Its
            # answer (source "tier") is written only when the run really starts, below
            route["policy"] = preauth
        else:
            # the person said yes to an offer (H12, written here as before); a tier-planned "self" sent out anyway
            # is the lead's (source "lead": not a yes in proposals.stats)
            proposals.answer(p, a.proposal, True, source="lead" if tier_self else "person")
        route["proposal"] = a.proposal
    if kw is None:
        _bg_not_delegated(p, a, route, caller)
        _out({"delegated": False, "advice": route.get("advice"), "route": route,
              "hint": "add --force to delegate anyway"})
        human_tail([f"Not delegated: {route.get('advice')}", "Cost: $0 (nothing ran)",
                    "Next: do it yourself, or add --force to delegate anyway"])
        return 0
    if route.get("cheaper_self"):
        print(f"ccx: {route['cheaper_self']}", file=sys.stderr, flush=True)
    if mode["mode"] == "write" and not a.check:  # stderr only: stdout (the JSON a lead reads) stays as it was
        print(NO_CHECK_NUDGE, file=sys.stderr, flush=True)
    if auto:
        plan = {"to": kw["to"], "model": kw.get("model"), "effort": kw.get("effort"), "mode": mode["mode"],
                **{k: route[k] for k in ("rung", "p", "expected_usd") if route.get(k) is not None},
                **({"check": a.check} if a.check else {}), **({"budget_usd": a.budget} if a.budget else {}),
                **({"project": proj["name"]} if proj else {})}
        # a yes to an offer is the person's approval; a tier pre-authorisation, or a proposal the tier planned self
        # (never offered), is not (L0/L1 still ask)
        stop = autonomy.gate(auto, mode["mode"], bool(a.approved or (a.proposal and not preauth and not tier_self)),
                             plan)
        if stop:
            _out(stop)
            return 0
        if a.bg:
            return _bg_maybe_wait(sys.argv[1:], p, a.wait)
    lead = lead_session_id(caller)
    cwd = Path(a.cwd or os.getcwd())
    fork = None
    if a.fork:
        if kw["to"] != "claude" or caller != "claude" or not os.environ.get("CLAUDE_CODE_SESSION_ID"):
            raise ValueError("--fork works only from a Claude Code lead to a Claude sub-agent (a session can "
                             "only be copied within the same tool); other directions get the context via the brief")
        fork = os.environ["CLAUDE_CODE_SESSION_ID"]
    if a.seat:
        prev = None if (a.new or a.fork or a.worktree) else find_seat(p, a.seat, cwd, kw["to"])
    else:
        prev = None if (a.new or a.fork or a.worktree) else find_continuable(p, lead, cwd, kw["to"], mode["mode"])
    if proj:
        text = f"{proj['header']}\n\n{text}"
    req = Request(brief=text, mode=mode["mode"], mode_source=mode["source"], mode_why=mode["why"], cwd=cwd, caller=caller,
                  worktree=a.worktree, escalate=False if a.no_escalate else None,
                  label=f"seat:{a.seat}" if a.seat else (a.label or ""),
                  fallback=not a.no_fallback, task=a.task, step=a.step, mcp=True if a.mcp else None,
                  lead_session=lead, resume_run=prev, continued=bool(prev), fork_lead=fork,
                  allow_subagents=not a.no_subagents, check=a.check, review=a.review, risk=a.risk,
                  namecheck=getattr(a, "namecheck", None),
                  subagents="off" if a.no_subagents else subagents_spec(a.subagents), budget_usd=a.budget,
                  parallel=True if a.parallel else None, share_context=a.context,
                  progress=not os.environ.get("CCX_RUN_ID"), **kw)    # not the detached child of --bg
    if preauth:
        # the run of a proposal the picked tier pre-authorised starts now: only now is it used (once), and only now
        # did it go out (actual_mode). Source "tier": not counted as a yes in proposals.stats. The claim is atomic:
        # of two runs started together, only one gets it
        if not proposals.claim(p, a.proposal):
            err = (f"proposal {a.proposal} was pre-authorised for one run, which has already used it: run "
                   "`ccx propose` again for this task")
            _bg_refused(p, a, caller, err)
            raise ValueError(err)
        proposals.answer(p, a.proposal, True, source="tier")
    rec = run(req, p)
    res = compact(rec)
    if prev:
        res["continued_from"] = prev          # same sub-session: it remembers the earlier task(s)
    res["route"] = {k: v for k, v in route.items() if k in ("source", "b", "rung", "p", "chain_p", "tier",
                                                              "stale", "mode", "trial", "cheaper_self")}
    if proj:
        res["project"] = {k: proj[k] for k in ("name", "path", "approval_rules") if proj.get(k)}
    if auto:
        res["autonomy"] = {k: auto[k] for k in ("level", "source")}
        if auto["level"] == "L2" and rec["ok"] and res.get("worktree"):
            res["autonomy"]["merge"] = autonomy.merge(p, rec["run_id"], auto, cfg,
                                                      rules=(proj or {}).get("approval_rules"),
                                                      apply=auto["auto_merge"])
    if route.get("b") is None:
        # an explicit pick with no size: its verdict reaches the ledger but not routing (seven-cores A/B, PR #30)
        res["route"]["learns"] = "no: give --minutes (or the rubric flags) so this run's verdict can teach routing"
    res["recap"] = recap(rec, res)              # last key: survives `| tail`
    _out(res)
    human_tail(human_summary(rec, res))
    return 0 if exit_ok(rec) else 2


def cmd_send(a) -> int:
    """Talk to a running *desktop/interactive* Codex session (the Codex app) instead of a headless one."""
    import subprocess
    codex = find_bin("codex")
    if not codex:
        raise FileNotFoundError("codex CLI not found")
    from ..runners import bin_argv
    if a.list or not a.thread:
        from ..usage import codex_threads
        _out({"threads": codex_threads(),
              "next": "ccx send --to codex --thread <thread> \"message\" (pick one whose cwd is your project)"})
        return 0
    text = " ".join(a.message) if a.message else sys.stdin.read()
    if not a.force:
        # don't cut in while the person is working in that conversation (OpenRig's typing guard)
        import time as _t
        from ..usage import thread_activity
        waited, act = 0, thread_activity(a.thread)
        while act["busy"] and waited < a.wait:
            _t.sleep(min(10, a.wait - waited))
            waited += 10
            act = thread_activity(a.thread)
        if act["busy"]:
            _out({"ok": False, "held": True, "thread": a.thread, "why": act["why"],
                  "next": "send again when the conversation is idle, or add --force to send now"})
            return 2
    r = subprocess.run([*bin_argv("codex"), "queue", "--thread", a.thread, "--message", text],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL)
    _out({"ok": r.returncode == 0, "thread": a.thread, "output": (r.stdout or r.stderr).strip()[-800:]})
    return 0 if r.returncode == 0 else 2


def cmd_ask(a) -> int:
    """Quick second opinion from another model: read-only, low effort, no escalation, not learned from."""
    p = paths()
    cfg = load_config(p)
    caller = _caller(a.caller)
    to = _target(a.to, caller)
    spec = tier_spec_safe(cfg, "T2", to)
    if not spec:
        raise ValueError(f"no T2 model configured for {to}")
    effort = "default" if to == "gemini" else "low"
    req = Request(to=to, brief=_brief(a), mode="read", cwd=Path(a.cwd or os.getcwd()), caller=caller,
                  escalate=False, label="ask", model=spec["model"], effort=effort, ephemeral=True)
    rec = run(req, p)
    c = compact(rec)
    _out({k: c.get(k) for k in ("run_id", "agent", "model", "ok", "summary", "open_questions", "tokens", "kind",
                                "hint") if k in c or k not in ("kind", "hint")})
    return 0 if c["ok"] else 2


def _run_records(p):
    for f in p.runs.glob("*/run.json") if p.runs.exists() else []:
        try:
            yield json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue


def _restart_step(p, a, root: Path, step: dict, last: dict, brief: str) -> int:
    f = p.runs / last["run_id"] / "brief.md"
    own = f.read_text(encoding="utf-8") if f.exists() else step["title"]
    text = (f"{own}\n\n(An earlier attempt at this step, run {last['run_id']}, was cut off before its session "
            "started. Look at `git diff` for anything it already changed; do not redo finished work.)\n\n" + brief)
    rung = (last.get("first_rung") or "").split(":")
    model, effort = (rung[1], rung[2]) if len(rung) == 3 and rung[0] == last["to"] else (None, None)
    req = Request(to=last["to"], brief=text, mode=last.get("mode") or "write", cwd=Path(last.get("cwd") or root),
                  caller=_caller(a.caller), task=a.task, step=step["n"],
                  label=last.get("label") or f"{a.task}#{step['n']}",    # the same step: keep its label
                  model=model, effort=effort, check=last.get("check_cmd"), provider=last.get("provider"),
                  review=last.get("review_mode") or "auto")
    rec = run(req, p)
    _out(compact(rec) | {"restarted": last["run_id"], "why": "the earlier run was cut off before its session "
                         "started, so there was nothing to resume"})
    return 0 if rec["ok"] else 2


def cmd_task(a) -> int:
    """Long tasks (task-checkpoint): status, or continue an interrupted one with a single command."""
    p = paths()
    cp = learn.module(p, "checkpoint")
    root = learn.cp_root(Path(a.cwd or os.getcwd()))
    os.environ.setdefault("CHECKPOINT_ROOT", str(root))
    if a.task_cmd == "status":
        return int(cp.main(["status", *([a.task] if a.task else [])]) or 0)
    t = cp.Task(a.task, root)
    t.save()
    steps = t.plan["steps"]
    nxt = next((s for s in steps if s["status"] in ("doing", "failed")), None) or \
        next((s for s in steps if s["status"] == "todo"), None)
    if nxt is None:
        _out({"task": a.task, "state": "all steps done", "next": "verify, then checkpoint finish"})
        return 0
    runs = [r for r in ledger.rows(p) if not r.get("type") and r.get("task") == a.task and r.get("step") == nxt["n"]]
    if not runs:
        # a run killed mid-way (closed window, crash) never reached the ledger; its record and session id are on disk
        runs = sorted((r for r in _run_records(p) if r.get("task") == a.task and r.get("step") == nxt["n"]
                       and r.get("session_id")), key=lambda r: r.get("ts") or 0)
    brief = (t.dir / "checkpoint.md").read_text(encoding="utf-8")
    if not runs:
        started = sorted((r for r in _run_records(p) if r.get("task") == a.task and r.get("step") == nxt["n"]),
                         key=lambda r: r.get("ts") or 0)
        if started:
            # killed before its agent session began (seen in a real run, killed after 12 s): there is no session to
            # resume, so start the step again from the person's brief instead of only printing advice
            return _restart_step(p, a, root, nxt, started[-1], brief)
    if not runs:
        _out({"task": a.task, "step": nxt["n"], "title": nxt["title"], "delegated_before": False,
              "next": f"do step {nxt['n']} yourself, or: ccx run --task {a.task} --step {nxt['n']} \"...\"",
              "brief": brief})
        return 0
    last = runs[-1]
    quota_out = last.get("kind") == "quota" and not a.same
    if quota_out:
        # the old session's agent is (probably) still out of quota: a fresh session on the other agent,
        # handed the checkpoint brief + the diff, instead of waiting
        from ..delegate import other
        to = other(last["to"], load_config(p))
        text = (f"Continue step {nxt['n']} ({nxt['title']}) of a task another agent started and was cut off "
                f"by its quota. Do not redo finished steps. Look at `git diff` for work already done.\n\n{brief}")
        if last.get("session_id") and last["to"] in ("claude", "codex"):
            # what the cut-off session itself had got to, read by code from its session file
            from .memory import transcript_handoff
            got = transcript_handoff(p, root, last["to"], last["session_id"], 3000, use_model=False)
            if got:
                text += "\n\n# Where the cut-off session stood\n" + got[1]
        req = Request(to=to, brief=text, tier="T2" if to != "gemini" else "T2", caller=_caller(a.caller),
                      cwd=root, task=a.task, step=nxt["n"], label=last.get("label") or f"{a.task}#{nxt['n']}",
                      review=last.get("review_mode") or "auto")
        rec = run(req, p)
        out = compact(rec) | {"handoff": f"{last['to']} -> {to} (quota)"}
    else:
        req = Request(to=last["to"], brief=f"Continue step {nxt['n']} ({nxt['title']}) from where you stopped. "
                      "Do not redo finished work.", resume_run=last["run_id"], caller=_caller(a.caller),
                      review=None)    # None: the run's own review setting (ccx/delegate.py run)
        rec = run(req, p)
        out = compact(rec) | {"resumed": last["run_id"]}
    _out(out)
    return 0 if rec["ok"] else 2


def cmd_verify(a) -> int:
    if a.sweep:
        from ..delegate import soft_verdicts
        done = soft_verdicts(paths(), a.after_h)
        _out({"recorded": done, "note": "probable verdicts from the evidence (soft); `ccx verify RUN --ok 0|1` "
              "overrides any of them"} if done else {"recorded": [], "note": "nothing old enough with clear evidence"})
        return 0
    if a.sample:
        import sys
        from ..verdicts import review_sample, sample_soft
        picks = sample_soft(paths(), a.sample, include_evals=a.include_evals)
        if not picks:
            _out({"sample": [], "note": "no probable verdict this week that nobody judged since"})
        elif sys.stdin.isatty() and not a.list:
            done = review_sample(paths(), picks)
            _out({"judged": done, "overturned": sum(d["overturned"] for d in done)})
        else:
            _out({"sample": picks, "how": "look at each, then `ccx verify RUN_ID --ok 1|0` (run this in a terminal "
                  "to answer one by one)"})
        return 0
    if a.dismiss:
        if not a.run_id or a.ok is not None:
            raise ValueError("--dismiss takes a run id and no --ok: the run counts neither way")
        from ..verdicts import dismiss
        _out(dismiss(paths(), a.run_id, a.note))
        return 0
    if a.ok is None:
        raise ValueError("give --ok 1 or --ok 0 (or --dismiss, --sweep, --sample N)")
    if a.builtin:
        from ..delegate import verify_builtin
        if a.b is None:
            raise ValueError("--builtin needs --b (the difficulty ccx route used)")
        _out(verify_builtin(paths(), a.builtin, a.b, bool(a.ok), a.agent_id, a.note))
        return 0
    if not a.run_id:
        raise ValueError("give a run id, or --builtin <rung> --b <b> for work your own sub-agent did")
    _out(verify(paths(), a.run_id, bool(a.ok), a.note, a.reason or ""))
    return 0


def cmd_plan(a) -> int:
    """Thin wrapper over the task-split skill (size / check / template / record / show)."""
    p = paths()
    sp = learn.module(p, "split")
    return int(sp.main(a.args) or 0)


def cmd_namecheck(a) -> int:
    """The static undefined-name check by hand: a run's changes (what fail mode ran), the working tree's changes
    since --base, or whole files. Exit 1 on a hit."""
    from .. import namecheck as nck
    from ..review import _git
    from ..workspace import run_snapshot
    if a.files:
        res: dict = {"hits": [], "files": 0}
        for f in a.files:
            try:
                data = Path(f).read_bytes()
            except OSError as e:
                res.setdefault("not_checked", []).append(f"{f}: {e.strerror or e}")
                continue
            res["files"] += 1
            hits, why = nck.check_source(data, f)
            res["hits"] += hits
            if why:
                res.setdefault("not_checked", []).append(f"{f}: {why}")
    elif a.run:
        p = paths()
        rec = ledger.load_run(p, a.run)
        res = nck.scan(Path(rec.get("cwd") or os.getcwd()), run_snapshot(p, rec))
    else:
        cwd = Path.cwd()
        top = _git(cwd, "rev-parse", "--show-toplevel").strip()
        if not top:
            print("ccx namecheck: not in a git repo; name the files to check", file=sys.stderr)
            return 2
        res = nck.scan(cwd, {"repo": top, "base": a.base, "untracked": []})
    for h in res["hits"]:
        print(nck.line(h))
    if a.json:
        _out(res)
    elif not res["hits"]:
        print(f"namecheck: no undefined names ({res['files']} file{'s' if res['files'] != 1 else ''})")
    return 1 if res["hits"] else 0


def cmd_resume(a) -> int:
    rid = os.environ.get("CCX_RUN_ID")          # the detached child of --bg resume, as cmd_run's
    if rid:
        from ..wake import after_bg
        with after_bg(paths(), rid):
            return _cmd_resume(a)
    return _cmd_resume(a)


def _cmd_resume(a) -> int:
    p = paths()
    from ..recover import sweep
    if getattr(a, "wait", None) is not None and not getattr(a, "bg", False):
        raise ValueError("--wait N goes with --bg (a foreground resume already waits until it is done)")
    refused = _env_refused(p, a)                     # before --bg detaches anything: nothing is spent
    if refused is not None:
        return refused
    if getattr(a, "bg", False):
        if not a.brief and not a.brief_file:
            raise ValueError("--bg needs the follow-up as text or --brief-file (stdin is not passed on)")
        prev = ledger.load_run(p, a.run_id)          # an unknown run id fails here, not in the detached child
        if a.check:                                  # the same check the child makes, before anything detaches
            _check_names_real_tests(a.check, Path(prev.get("cwd") or os.getcwd()))
        sweep(p)
        # a session another run is still working in: refuse here, as the child would, instead of detaching a child
        # that exits without a record (plain --bg then printed `started` and `ccx show ID --wait` waited it out)
        from ..delegate import refuse_if_busy
        refuse_if_busy(p, prev)
        return _bg_maybe_wait(sys.argv[1:], p, a.wait)
    sweep(p)                            # closes it as interrupted first if its ccx process died mid-run
    req = Request(to="codex", brief=_brief(a), tier=a.tier, resume_run=a.run_id,
                  caller=_caller(a.caller), escalate=False if a.no_escalate else None,
                  model=a.model, effort=a.effort, budget_usd=a.budget, review=a.review, check=a.check,
                  namecheck=getattr(a, "namecheck", None), progress=not os.environ.get("CCX_RUN_ID"))
    if a.check:                         # replaces the stored check (one that named a missing file, say)
        prev = ledger.load_run(p, a.run_id)
        req.check = _check_names_real_tests(a.check, Path(prev.get("cwd") or os.getcwd()))
    from ..delegate import SessionBusy
    try:
        rec = run(req, p)
    except SessionBusy as e:            # busy after the parent of a --bg resume checked: a record, not a silent exit
        prev = ledger.load_run(p, a.run_id)
        _bg_refused(p, a, req.caller, str(e), cwd=prev.get("cwd"), to=prev.get("to"),
                    next_step=f"wait for the run named in the error, then `ccx resume {a.run_id}` again")
        raise
    res = compact(rec)
    if not res["ok"] and _session_gone(rec):     # after compact's hint (check failed, cap...), not instead of it
        gone = (f"the sub-session of {a.run_id} is gone (\"No conversation found\"), so it cannot be resumed: "
                "send the task again as a fresh run with `ccx run --new ...`")
        res["hint"] = f"{res['hint']} Also: {gone}" if res.get("hint") else gone
    res["recap"] = recap(rec, res)
    _out(res)
    human_tail(human_summary(rec, res))
    return 0 if exit_ok(rec) else 2


def _env_refused(p, a) -> int | None:
    """A run that stopped on an environment failure (kind env) is not resumed unless the person fixed the machine
    and said so with --env-fixed: the same attempt would meet the same wall and be paid for again (2026-10-31 eval
    pg1). Prints the needs_lead record and returns exit 2; None when the resume may go on."""
    if getattr(a, "env_fixed", False):
        return None
    from ..delegate import env_refusal
    out = env_refusal(ledger.load_run(p, a.run_id))
    if out is None:
        return None
    _out(out)
    return 2


def _session_gone(rec: dict) -> bool:
    """Claude Code's errors[] says "No conversation found" when the session to resume no longer exists. Only the
    final cause counts: the run's error, else its last attempt's (an earlier attempt that fell back does not)."""
    last = (rec.get("attempts") or [{}])[-1]
    return "no conversation found" in str(rec.get("error") or last.get("error") or "").lower()


def cmd_stop(a) -> int:
    from ..stop import stop
    out = stop(paths(), a.run_id, wait=a.wait)
    _out(out)
    return 0 if out.get("stopped") or out.get("requested") else 2


def cmd_batch(a) -> int:
    """plan.json: {"tasks":[{"id", "brief", "to"?, "mode"?, "cwd"?, "tier"? | "model"+"effort"? |
    rubric keys ("files","coupling","clarity","risk","novelty")?, "minutes"?, "task"?, "step"?, "check"?,
    "review"? (auto|on|off, as `ccx run --review`)}]}"""
    p = paths()
    cfg = load_config(p)
    if _refused_off(p, cfg, a, "ccx batch"):
        return 0
    plan = json.loads(Path(a.plan).read_text(encoding="utf-8"))
    caller = _caller(a.caller)
    tasks = plan["tasks"]
    for t in tasks:
        apply_mode(t)                            # a task without "mode" gets it from its brief
    writers = [t for t in tasks if t["mode"] == "write"]
    seen: dict[str, tuple[bool, bool]] = {}      # folder -> (in git, clean), asked once per folder
    shared: list = []
    stale: list = []                             # asked for a worktree in a dirty project

    def state(t: dict) -> tuple[bool, bool]:
        cwd = Path(t.get("cwd") or os.getcwd())
        key = str(cwd.resolve())
        if key not in seen:
            git = in_git(cwd)
            seen[key] = (git, git and clean(cwd, ignore=(Path(a.plan),)))
        return seen[key]

    def isolate(i: int, t: dict) -> bool:
        """Parallel writers in one repo must not trample each other: each gets a worktree. Outside git there is
        none, and with uncommitted changes a worktree (made from the last commit) would miss them: then they share
        the folder, as `ccx q run` does (listed under shared_folder), so keep pieces disjoint."""
        if "worktree" in t:                      # an explicit choice stands; say when it misses uncommitted work
            if t["worktree"] and state(t) == (True, False):
                stale.append(t.get("id") or f"#{i}")
            return t["worktree"]
        if not (len(writers) > 1 and t in writers):
            return False
        git, tidy = state(t)
        if git and not tidy:
            shared.append(t.get("id") or f"#{i}")
        return git and tidy
    reqs, skipped, req_tasks = [], [], []
    for i, t in enumerate(tasks):
        kw, route = resolve(t, caller, p, cfg)
        if kw is None:
            skipped.append({"id": t.get("id"), "advice": route.get("advice")})
            continue
        req_tasks.append(t)
        reqs.append(Request(brief=t["brief"], mode=t["mode"], mode_source=t["mode_source"], mode_why=t["mode_why"],
                            check=t.get("check"), review=t.get("review", "auto"), risk=t.get("risk"),
                            cwd=Path(t.get("cwd") or os.getcwd()), caller=caller, label=t.get("id", ""),
                            task=t.get("task"), step=t.get("step"), worktree=isolate(i, t), **kw))
    extra = {"shared_folder": {"ids": shared, "why": SHARED_WHY}} if shared else {}
    if stale:
        extra["stale_base"] = {"ids": stale, "why": STALE_WHY}
    threads = int(cfg["defaults"].get("max_parallel", 3))
    n = lanes.width(getattr(a, "lanes", None), cfg)
    use_merge, why = merge.choose(getattr(a, "merge", None), getattr(a, "lanes", None), cfg)
    if why:
        _out({"error": why})
        return 2
    if use_merge:
        return _batch_merged(p, cfg, reqs, req_tasks, skipped, extra, threads)
    if n:
        # warm lanes (ccx/lanes.py): same project + agent + mode share at most n sessions, piece after piece
        lane_list = lanes.split(reqs, n, lambda r: (str(r.cwd.resolve()), r.to, r.provider, r.mode))
        for lane in lane_list:                   # a lane works in one folder: its first piece's worktree (if any)
            for r in lane[1:]:
                r.worktree = lane[0].worktree

        bad: list[bool] = []                     # exit code as before compact's ok also said no to blocked/failed
        env_hit: list[str] = []                  # a piece whose sub-agent could not start a process on this machine

        def step(r, warm):
            if env_hit:                          # every later piece meets the same wall: start none (as `ccx q run`)
                bad.append(True)
                return {"label": r.label, "ok": False, "skipped": f"environment problem in run {env_hit[0]}: "
                        "nothing new was started; tell the person, and after their fix run these pieces again"}, None
            if warm:
                r.resume_run, r.continued = warm, True
            try:
                rec = run(r, p)
            except Exception as e:  # noqa: BLE001 — one piece's error must not stop its lane
                bad.append(True)
                return {"label": r.label, "ok": False, "error": f"{type(e).__name__}: {e}"[:300]}, None
            bad.append(not exit_ok(rec))
            if rec.get("kind") == "env":
                env_hit.append(rec["run_id"])
            return compact(rec), rec
        results = lanes.run_lanes(lane_list, step, lanes.limits(cfg), threads)
        _out({"results": results, "do_yourself": skipped, "lanes": len(lane_list), **extra})
        return 0 if not any(bad) else 2
    with ThreadPoolExecutor(max_workers=threads) as ex:
        recs = list(ex.map(lambda r: run(r, p), reqs))
    results = [compact(rec) for rec in recs]
    _out({"results": results, "do_yourself": skipped, **extra})
    return 0 if all(exit_ok(rec) for rec in recs) else 2


def _batch_merged(p, cfg: dict, reqs: list, tasks: list[dict], skipped: list, extra: dict, threads: int) -> int:
    """`ccx batch --merge` (ccx/merge.py): pieces that fit run as one; the rest as before. `results` keeps one entry
    per piece, in plan order; `merged` lists the merged runs."""
    groups = merge.groups(list(zip(reqs, tasks)), cfg)

    def job(idx: list[int]) -> list[tuple[int, dict, bool]]:
        try:
            if len(idx) == 1:
                rec = run(reqs[idx[0]], p)
                return [(idx[0], compact(rec), exit_ok(rec))]
            rs, ts = [reqs[i] for i in idx], [tasks[i] for i in idx]
            rec = run(merge.merged_request(rs, ts), p)
            got = merge.finish(rec, rs, ts, p, cfg)
            jobs_merged.append(got["merged"])
            return [(i, r, bool(r.get("ok"))) for i, r in zip(idx, got["results"])]
        except Exception as e:  # noqa: BLE001 — one group's error must not hide the others' results
            why = f"{type(e).__name__}: {e}"[:300]
            return [(i, {"label": reqs[i].label, "ok": False, "error": why}, False) for i in idx]

    jobs_merged: list[dict] = []
    with ThreadPoolExecutor(max_workers=threads) as ex:
        done = [x for part in ex.map(job, groups) for x in part]
    done.sort(key=lambda x: x[0])
    merged_runs = sorted(jobs_merged, key=lambda m: m["run_id"])
    _out({"results": [r for _, r, _ in done], "do_yourself": skipped,
          **({"merged": merged_runs} if merged_runs else {}), **extra})
    return 0 if all(ok for _, _, ok in done) else 2


def cmd_quota(a) -> int:
    from .. import quota
    p = paths()
    extra = {}
    if a.backfill:
        extra["backfilled"] = quota.backfill(p)
    if a.probe:
        extra["probe_readings"] = quota.probe(p)
    pr = quota.pressure(p)
    lam = {}
    try:
        tr = learn.module(p, "routing")
        lam = {ag: round(tr.shadow_lambda(v), 2) for ag, v in pr["quota"].items()}
    except Exception:  # noqa: BLE001
        pass
    stops = quota.recent_stops(p)
    if stops:
        extra["recent_quota_stops"] = stops       # H2: why each was taken for a quota stop
    _out({"projected_at_reset": pr["quota"], "quota_price_share_of_api": lam, "windows": pr["pace"], **extra})
    return 0


def cmd_bench(a) -> int:
    """Thin wrapper over task_routing.py refresh / sources (the data lives next to the routing state)."""
    tr = learn.module(paths(), "routing")
    if not hasattr(tr, "bench"):
        raise ValueError("the installed task-routing skill is older than benchmark support: update it")
    b = tr.bench()
    if a.what == "refresh":
        _out(b.refresh(tr.bench_path(), plugin_dirs=tr.bench_plugin_dirs() if hasattr(tr, "bench_plugin_dirs") else ()))
    else:
        d = b.load(tr.bench_path())
        _out({"cache": str(tr.bench_path()), "age_days": b.age_days(tr.bench_path()), **b.summary(d)} if d
             else {"cache": str(tr.bench_path()), "empty": "run: ccx bench refresh"})
    return 0


def cmd_route(a) -> int:
    out = _route(a)
    _out(out)
    human_tail(_route_summary(out))
    return 0


def _route_summary(out: dict) -> list[str]:
    """Plain lines for a person at a terminal (human_tail): the pick, why, and the command that runs it."""
    if out.get("rung"):
        pick = out["rung"].replace(":", " ", 1).replace(":", "/")
        usd = out.get("expected_usd")
        lines = [f"Pick: {pick}" + (f", p(success) {out['p']:.2f}" if isinstance(out.get("p"), (int, float)) else "")
                 + (f", expected ~${usd:.4f}" if isinstance(usd, (int, float)) else "")]
        if out.get("advice"):
            lines.append(f"Advice: {out['advice']}")
        if (out.get("small_self") or {}).get("applied") or out.get("routing_mode") == "off":
            return lines + ["Next: do it yourself"]
        return lines + [f"Next: ccx run --to {out['rung'].split(':')[0]} \"<the task>\" with the same flags"]
    tier, label = out.get("tier"), out.get("label")
    why = ", ".join(out.get("reasons") or [])
    if (out.get("small_self") or {}).get("applied") or out.get("routing_mode") == "off":
        return [f"Tier: {tier} ({label})" + (f": {why}" if why else ""), f"Advice: {out['advice']}",
                "Next: do it yourself"]
    if tier == "T0":
        nxt = ("do it yourself (a lead's `ccx run` refuses it; from your terminal, `ccx run --to <agent>` still "
               "delegates it, on the cheapest rung)")
    else:
        nxt = f"ccx run --tier {tier} \"<the task>\""
    return [f"Tier: {tier} ({label})" + (f": {why}" if why else ""), f"Next: {nxt}"]


def _route(a) -> dict:
    p = paths()
    cfg = load_config(p)
    if a.coupling or a.clarity or a.risk or a.novelty or a.b is not None or a.minutes:
        spec = {"to": a.to, "files": a.files, "b": a.b, "coupling": a.coupling, "clarity": a.clarity,
                "risk": a.risk, "novelty": a.novelty, "tradeoff": a.tradeoff, "force": True,
                "minutes": a.minutes,
                "brief": " ".join(a.text or []), "mode": getattr(a, "mode", None), "kind": a.kind}
        mode = apply_mode(spec)
        kw, route = resolve(spec, _caller(None), p, cfg)
        route["mode"] = mode            # recommended read/write and why; routing priced the start-up with it
        lead_ctx = a.lead_ctx or 0
        if a.lead and route.get("rung"):
            ctx = a.ctx_tokens
            for f in a.ctx_files or []:        # rough: 4 bytes per token
                try:
                    ctx += Path(f).stat().st_size // 4
                except OSError:
                    pass
            # what each of your own turns re-reads: given, else your conversation's last request (J5/H10)
            lead_agent, lead_ctx, src = a.lead.split(":")[0], a.lead_ctx, "given"
            if lead_ctx is None:
                from .. import context
                from .common import lead_session_id
                lead_ctx = context.lead_now(lead_agent, lead_session_id(lead_agent))
                src = "none" if lead_ctx is None else "lead_session"
                a.lead_ctx_read = True
            lead_ctx = lead_ctx or 0
            if route.get("policy") and lead_ctx:           # balanced: a big lead context sends medium tasks out
                tp = tier_policy(p, cfg, {**spec, "files": a.files, "lead_ctx": lead_ctx},
                                 route["policy"].get("tier") or route["tradeoff"])
                if tp:
                    route["policy"] = tp
            route["self_vs_delegate"] = learn.self_vs_delegate(p, route["b"], a.lead, route["rung"], ctx,
                                                               a.turns_left, route["tradeoff"], lead_ctx)
            route["self_vs_delegate"].update(ctx_tokens=ctx, lead_ctx_tokens=lead_ctx, ctx_source=src)
            others = ((installed_agents() or list(DELEGATE_AGENTS)) + provider_agents(load_config(p))
                      if a.to == "auto" else [a.to])      # three_way holds pay-per-token agents back itself
            quota = parse_quota(a.quota)
            choice = learn.three_way(p, route["b"], a.lead, others, ctx, a.turns_left, route["tradeoff"],
                                     needs=tuple(x for x in (a.needs or "").split(",") if x), quota=quota,
                                     kind=learn.task_kind(mode["mode"], a.kind), risk=a.risk or "low",
                                     lead_ctx=lead_ctx)
            if choice:
                choice.update(lead_ctx_tokens=lead_ctx, ctx_source=src)
                route["choice"] = choice      # self / built-in sub-agent / ccx: see the agent-delegate skill
        if routing_mode(cfg) == "off":
            _routing_off(route)
        else:
            _small_self(p, cfg, route, a, lead_ctx,
                        delegates=bool(route.get("rung")) and (route.get("policy") or {}).get("mode") != "self")
        _lead_by_task(cfg, route, a)    # after `choice`: its built-in pick wins over builtin_model
        return route
    r = router.classify(" ".join(a.text), a.files)
    t = cfg["tiers"][r.tier]
    out = r.as_dict() | {"label": tier_words(p, t, r.tier, "label"), "when": tier_words(p, t, r.tier, "when"),
                         "note": "keyword heuristic; give the rubric flags for a calibrated pick",
                         "mode": apply_mode({"brief": " ".join(a.text or []), "mode": getattr(a, "mode", None)})}
    for ag in AGENTS:
        if t.get(ag):
            out[ag] = t[ag]
    if routing_mode(cfg) == "off":
        _routing_off(out)
    else:
        _small_self(p, cfg, out, a, a.lead_ctx or 0, delegates=r.tier != "T0")
    return out


def _small_self(p, cfg: dict, route: dict, a, lead_ctx: int, delegates: bool) -> None:
    """P0-6, `routing.small_self` (off unless set): a task that would cost less to do yourself than delegating's
    fixed cost is advised as do-it-yourself instead of delegated. By `small_self_by`: files (default, #200's rule) =
    at most small_self_files source files; cost (experimental) = plan.self_cost (requests x your conversation's
    size, plus the files read) under `small_self_overhead_usd` (the lead's own share of a delegation: brief, wait,
    acceptance; pg1 ledger median $0.035), scaled to your conversation and model. --minutes does not gate it, so the agent-delegate offer path, which passes 15+
    minutes, is covered. Advice only: `ccx run` and the rung, ladder and tier plan are unchanged; a self/ccx `choice`
    is turned to self, its pick kept as `recommend_before`. Not when the person picked a tier (its rules win),
    --needs names what only a ccx run gives, the lead's context is large, or the lead's own quota is tight
    (docs/maintenance.md, section 3)."""
    from ..plan import _rnum, self_cost
    rc = cfg.get("routing") or {}
    on = rc.get("small_self", False)
    if not (on is True or str(on).strip().lower() in ("on", "true", "yes", "1")) or not delegates:
        return
    by = "cost" if str(rc.get("small_self_by", "files")).strip().lower() == "cost" else "files"
    files, src = int(getattr(a, "files", 0) or 0), "--files"
    if not files and (route.get("objective") or {}).get("files_named"):
        files, src = int(route["objective"]["files_named"]), "brief"
    requests = getattr(a, "requests", None)
    if requests is not None and requests <= 0:
        raise ValueError("--requests must be more than 0")
    if by == "files" and (not files or files > _rnum(rc, "small_self_files", 1)):
        return
    if by == "cost" and not files and not requests:
        return                                      # nothing to size it by: routing as before
    lead = (a.lead or "").split(":")[0] or _caller(None)
    pol = cfg.get("policy") or {}
    skip = None
    if picked_tier(cfg):
        skip = f"you picked tier {picked_tier(cfg)} (policy.picked): its rules decide"
    elif set(x for x in (getattr(a, "needs", None) or "").split(",") if x) & {"undo", "worktree", "other-vendor",
                                                                             "resume"}:
        skip = "--needs asks for what only a ccx run gives"
    if (not skip and by == "cost" and not lead_ctx and getattr(a, "lead_ctx", None) is None and lead in AGENTS
            and not getattr(a, "lead_ctx_read", False)):
        try:                                         # your conversation's size, as `ccx lead` reads it
            from .. import context
            lead_ctx = context.lead_now(lead, lead_session_id(lead)) or 0
        except Exception:  # noqa: BLE001 — no reading: self_cost uses a fresh conversation's size
            lead_ctx = 0
    if not skip and lead_ctx >= int((pol.get("bands") or {}).get("lead_ctx_large", 150000)):
        skip = f"your context is large ({lead_ctx} tokens): each turn of your own re-reads it"
    elif not skip:
        q = (route.get("choice") or {}).get("quota")       # three_way already read it
        if not isinstance(q, dict) and lead in AGENTS:
            try:
                q = learn.known_quota(parse_quota(getattr(a, "quota", None)), p)
            except Exception:  # noqa: BLE001 — no reading: the rule applies as if quota were fine
                q = None
        used = (q or {}).get(lead)
        limit = _rnum(rc, "small_self_quota", 0.9)
        limit = limit / 100 if limit > 1 else limit        # 90 means 90 %, like --quota
        if isinstance(used, (int, float)) and used >= limit:
            skip = f"your {lead} quota is tight ({used:.0%} projected)"
    row = {"by": by, "files": files, "files_from": src}
    est = None
    if by == "cost" and not skip:
        est = self_cost(p, cfg, a.lead or lead, files, requests, lead_ctx)
        if est is None:
            skip = "no price for your model nor the reference one: cannot tell what doing it yourself costs"
        else:
            row["self_cost"] = est
            if est["usd"] >= est["overhead_usd"]:
                skip = (f"doing it yourself costs about ${est['usd']:.3f} ({est['requests']:g} requests x "
                        f"~{est['ctx_tokens'] // 1000}k tokens on {est['model']}), not less than delegating's fixed "
                        f"${est['overhead_usd']:.3f}")
    if skip:
        route["small_self"] = {"applied": False, **row, "why": skip}
        return
    if by == "cost":
        why = (f"doing it yourself costs about ${est['usd']:.3f} ({est['requests']:g} requests x "
               f"~{est['ctx_tokens'] // 1000}k tokens on {est['model']}), less than delegating's fixed "
               f"${est['overhead_usd']:.3f} (your brief, the wait, your acceptance)")
    else:
        why = (f"small task ({files} file{'s' if files > 1 else ''} by {src}"
               + (f", {a.minutes:g} min" if a.minutes else "")
               + "): doing it yourself is quicker; delegating saves a little money and takes minutes")
    route["small_self"] = {"applied": True, **row, "why": why}
    if isinstance(route.get("choice"), dict) and route["choice"].get("recommend") != "self":
        route["choice"].update(recommend_before=route["choice"].get("recommend"), recommend="self",
                               why=f"routing.small_self: {why}")
    route["advice"] = (f"do-it-yourself: {why} (routing.small_self; `ccx run` still delegates it if you need ccx's "
                       "check, review or worktree)")


def _routing_off(route: dict) -> None:
    """P0-9, routing.mode=off: the route still shows its pick (rung, tier, estimates), but the advice is do it
    yourself; a self/ccx `choice` is turned to self, its pick kept as `recommend_before`."""
    from ..plan import OFF_HOW, OFF_WHY
    route["routing_mode"] = "off"
    route["advice"] = f"do-it-yourself: {OFF_WHY} ({OFF_HOW})"
    if isinstance(route.get("choice"), dict) and route["choice"].get("recommend") != "self":
        route["choice"].update(recommend_before=route["choice"].get("recommend"), recommend="self", why=OFF_WHY)


_CJK = re.compile(r"[　-〿一-鿿＀-￯]")


def tier_words(p, tier_cfg: dict, tier: str, key: str) -> str | None:
    """A tier's `label` / `when` in the person's language (`ccx config set ui.lang zh|en`, English when unset). The
    shipped tiers.toml words are Chinese; English output used them as they were (2026-10-29 new-user walkthrough).
    A label of the person's own in config is kept when it suits the language: any text in Chinese, text without
    Chinese characters in English."""
    from ..lang import current, say
    own = tier_cfg.get(key)
    lang = current(p)
    if own and (lang == "zh" or not _CJK.search(str(own))):
        return own
    try:
        return say(f"tier_{tier}_{key}", lang=lang)
    except KeyError:                       # a tier of the person's own: no shipped words for it
        return own


def _lead_by_task(cfg: dict, route: dict, a) -> None:
    """lead.model_by_task (opt-in, default off): the model for a NEW lead conversation on this task and for the lead's
    own built-in sub-agent, from the same b. Advice only; a running conversation keeps its model. `builtin_model` is
    only a fallback: when the calibrated `choice` recommends a built-in sub-agent, its `how` names that rung's model
    (one source; `ccx verify --builtin <rung>` then matches the model used) and builtin_model is left out."""
    from .. import leadmodel
    agent = a.lead.split(":")[0] if getattr(a, "lead", None) else _caller(None)
    lm = leadmodel.pick(cfg, agent, route.get("b"), getattr(a, "risk", None))
    if lm:
        note = ("for a new conversation on this task; never switch a running one" +
                ("" if lm["band"] == "easy" else "; the strong lead: start it on the model it normally runs on"))
        route["new_lead"] = {**lm, "note": note}
        bm = None if (route.get("choice") or {}).get("recommend") == "builtin" else leadmodel.builtin_model(lm)
        if bm:
            route["builtin_model"] = bm         # Claude Code's Agent tool `model` for your own sub-agent


def cmd_propose(a) -> int:
    """H12: estimate before offering to delegate, and record the offer and the person's answer."""
    from .. import proposals
    p = paths()
    if a.stats:
        _out(proposals.stats(p, a.days))
        return 0
    if a.no:
        _out(proposals.answer(p, a.no, False))
        return 0
    if not a.lead:
        raise ValueError("ccx propose needs --lead (your own rung, e.g. claude:opus:high) and the rubric or --minutes")
    route = _route(a)
    if "b" not in route:
        raise ValueError("ccx propose needs the rubric flags or --minutes, so the estimate has a difficulty")
    lead_agent = a.lead.split(":")[0]
    row = proposals.new(p, route, " ".join(a.text or []), lead_session_id(lead_agent))
    c = route.get("choice") or route.get("self_vs_delegate") or {}
    tp = route.get("policy") or {}
    def usd(x):
        return "?" if x is None else (f"${x:.4f}" if x < 0.01 else f"${x:.2f}")
    odds = "odds unknown" if row["p"] is None else f"about {row['p']:.0%} likely to work"
    out = {"proposal": row["proposal"]}
    if route.get("routing_mode") == "off":      # the master switch wins over a picked tier and small_self
        from ..plan import OFF_HOW, OFF_WHY
        out.update(worth_offering=False, authorized=False, recommend="self", why=OFF_WHY, say=None,
                   routing_mode="off", next=f"not worth offering: do it yourself, nothing to ask ({OFF_HOW})")
    elif tp.get("explicit") and tp.get("mode"):
        # the person picked this tier in their settings (policy.picked): it pre-authorises what the tier delegates
        # (docs/DECISIONS.md, tiers). worth_offering agrees with authorized: true when the tier delegates (a skill
        # copy that predates `authorized` then asks with `say`, the conservative side), false when it says self
        mode = tp["mode"]
        out.update(worth_offering=mode != "self", authorized=mode != "self", recommend=mode, why=tp["why"])
        if mode != "self":
            out["say"] = (f"Your picked tier {tp['tier']} delegates this: about {usd(row['delegate_usd'])} delegated "
                          f"vs {usd(row['self_usd'])} here, {odds}.")
        if mode == "self":
            out["next"] = f"tier {tp['tier']}: do it yourself, nothing to ask"
        else:
            # the delegated part picks its model like save; the proposal row keeps the tier
            out["next"] = (f"tier {tp['tier']} pre-authorises this: ccx run --tradeoff save "
                           + ("--review off " if mode == "direct" else "")
                           + f"--proposal {row['proposal']} --minutes ... --files ... [--check \"CMD\"] \"<brief>\""
                           + (", then take its --check result as it is (no review, no acceptance by you) and tell "
                              "the person the result may be wrong. Run through you, your own turns are still paid: "
                              "only a script or CI calling ccx run itself skips the lead's cost"
                              if mode == "direct" else
                              ", then accept by its check + review (on review_failed, its hint)"))
            if mode == "direct":
                out["may_be_wrong"] = True
    elif (route.get("small_self") or {}).get("applied"):
        out.update(worth_offering=False, recommend="self", why=route["small_self"]["why"],
                   say=None, next="not worth offering: do it yourself, nothing to ask (routing.small_self)")
    else:
        worth = (c.get("recommend") == "delegate")
        out.update(worth_offering=worth, recommend=c.get("recommend"), why=c.get("why"),
                   say=(f"This looks delegable: about {usd(row['delegate_usd'])} delegated vs {usd(row['self_usd'])} "
                        f"if I do it here, {odds}. Delegate it?") if worth else None,
                   next=(f"on yes: ccx run --proposal {row['proposal']} ... (no --no-ab), then ccx verify <run_id>; "
                         f"on no: ccx propose --no {row['proposal']}") if worth else
                   "not worth offering: do it yourself, nothing to ask")
    if route.get("new_lead"):
        from .. import leadmodel
        leadmodel.record(p, route["new_lead"], "propose", {"proposal": row["proposal"]})
        out["new_lead"] = route["new_lead"]
        if route.get("builtin_model"):
            out["builtin_model"] = route["builtin_model"]
    out.update(self_usd=row["self_usd"], delegate_usd=row["delegate_usd"], p=row["p"],
               lead_ctx_tokens=row["lead_ctx_tokens"], ctx_source=c.get("ctx_source"))
    if route.get("small_self"):
        out["small_self"] = route["small_self"]
    if tp:
        out["tier"] = {k: tp.get(k) for k in ("tier", "band", "mode", "uncertain", "hard", "explicit", "provisional",
                                              "error") if k in tp}
        if route.get("routing_mode") == "off":
            out["tier"]["note"] = "informational: routing.mode is off, nothing is delegated"
        elif not tp.get("explicit"):
            out["tier"]["note"] = "informational: no tier picked, the offer-first rule above applies"
        elif not tp.get("mode"):
            out["tier"]["note"] = "the tier could not be planned: the offer-first rule above applies"
    _out(out)
    return 0


def register(sub) -> None:
    r = sub.add_parser("run", help="delegate one task to the other agent")
    # `ccx run -h`: the options most runs use first; the routing rubric and the coordinator / lead-side flags
    # under one "advanced" heading (help layout only: every option parses as before)
    adv = r.add_argument_group("advanced (routing rubric, coordinator and lead-side options; most runs need none of them)")
    r.add_argument("brief", nargs="*", help="task text (or use --brief-file / stdin)")
    r.add_argument("--brief-file")
    r.add_argument("--to", choices=["auto", *DELEGATE_AGENTS, *PROVIDER_AGENTS], default="auto")
    adv.add_argument("--from", dest="caller", choices=[*DELEGATE_AGENTS, *PROVIDER_AGENTS, "user"])
    adv.add_argument("--provider", help="model API behind an agent CLI, e.g. deepseek (see [providers] in config)")
    r.add_argument("--bg", action="store_true", help="run detached; wait for it with `ccx show <run_id> --wait`")
    r.add_argument("--wait", type=float, metavar="SECONDS", help="with --bg: wait up to this long in the same call "
                   "and print the final result (the run id goes to stderr at once); not done by then: exactly what "
                   "--bg prints. Keep it under your tool-call limit (e.g. 540)")
    adv.add_argument("--tier", choices=["auto", *TIER_ORDER], default="auto")
    r.add_argument("--mode", choices=["read", "write"],
                   help="read: analyse only; write: may edit files. Not given: inferred from the task text "
                        "(analysis verbs -> read, edit verbs -> write, unclear -> write)")
    r.add_argument("--cwd")
    adv.add_argument("--project", help="run in a project from the catalog: its name, an alias or a sentence "
                                     "(`ccx where`); several fit -> an error listing them")
    adv.add_argument("--rules-ok", action="store_true", help="with --project: you read the project's approval rules "
                                                          "ccx showed and they allow this task")
    adv.add_argument("--autonomy", choices=["L0", "L1", "L2"], help="this run's autonomy level (default: the "
                   "project's, `ccx autonomy`): L0 proposes only, L1 stops before edits, L2 may merge a small branch")
    adv.add_argument("--approved", action="store_true", help="the person said yes to this dispatch (passes an "
                   "L0/L1 stop; never a spending cap, approval rules or a merge into a protected branch)")
    _routing_args(r, into=adv)
    r.add_argument("--model", help="explicit model (skips routing), e.g. gpt-6.1-sol or sonnet")
    r.add_argument("--effort", help="explicit reasoning effort with --model or --provider (alone it is "
                   "ignored: the route picks the effort): low|medium|high|xhigh|max")
    adv.add_argument("--minutes", type=float, help="how long a skilled engineer would need, in minutes: the standard "
                   "difficulty unit (b = log2 minutes, blended 60/40 with the rubric); task-split learns from it too")
    adv.add_argument("--task", help="task-checkpoint task id: the session id is saved into it at once")
    adv.add_argument("--step", type=int, help="task-checkpoint step number")
    adv.add_argument("--force", action="store_true", help="delegate even when routing says do it yourself/split, or routing.mode is off")
    adv.add_argument("--no-ab", action="store_true", help="never pick this task as an A/B self-run sample")
    adv.add_argument("--proposal", help="the `ccx propose` id the person said yes to (H12)")
    adv.add_argument("--mcp", action="store_true", help="Claude sub-agent: also load MCP tools (bigger start-up)")
    adv.add_argument("--new", action="store_true", help="always a fresh sub-session (default: continue the last "
                   "one from this conversation, same folder and agent, if under 1 h old)")
    adv.add_argument("--fork", action="store_true", help="Claude lead -> Claude sub only: start from a copy of "
                   "your whole conversation (full context, costs more per turn)")
    r.add_argument("--worktree", action="store_true", help="isolate write task in a git worktree")
    adv.add_argument("--quota", action="append", metavar="AGENT=USED",
                   help="share of a subscription's quota already used (claude=0.8; default: read by ccx, "
                        "`ccx quota`); the fuller it is, the dearer that quota is priced, so pay-per-token "
                        "providers such as deepseek win more often")
    adv.add_argument("--seat", metavar="NAME", help="a named long-lived role (e.g. reviewer): its sub-session is "
                   "kept for a week and reused by the next --seat NAME task here; --new starts it over")
    r.add_argument("--check", metavar="CMD", help="acceptance command (e.g. 'python -m pytest -q tests/test_x.py'): "
                   "the sub-agent runs it before finishing, then ccx runs it again; a failure counts as a failure")
    adv.add_argument("--allow-subagents", action="store_true", help="(the default) the sub-agent may use its own "
                   "sub-agents: one level, counted, stopped over the budget")
    adv.add_argument("--no-subagents", action="store_true", help="the sub-agent may not start its own sub-agents "
                   "(same as --subagents off)")
    adv.add_argument("--subagents", default="auto", metavar="auto|off|N", help="how many of its own at once: auto = "
                   "the tool's default, fewer when quota is tight (default); off; or a number")
    adv.add_argument("--budget", type=float, metavar="USD", help="spending cap for its own sub-agents on this piece "
                   "(default [subagents] max_usd, $2); over it the run stops and can go on with ccx resume --budget")
    adv.add_argument("--parallel", action="store_true", help="tell it explicitly to use sub-agents for independent "
                   "parts (only with this flag: a brief that lists several items does not add it)")
    r.add_argument("--review", choices=["auto", "on", "off"], default="auto", help="independent review of the diff "
                   "by another vendor's cheap model: auto = only when --risk is visible/critical, the sub-agent is "
                   "unsure, or its claimed files don't match the diff (default); on = every write run; off")
    adv.add_argument("--namecheck", choices=["warn", "fail", "off"], help="static check for names no scope "
                   "defines in the functions the run changed: warn = shown to you and the reviewer (default, "
                   "[defaults] namecheck); fail = a hit fails the work like a failed --check; off")
    adv.add_argument("--no-escalate", action="store_true")
    adv.add_argument("--no-fallback", action="store_true", help="on quota/rate limit, stop instead of "
                   "retrying on the other agent")
    r.add_argument("--context", choices=["auto", "on", "off"], help="shared work context: attach what your "
                   "conversation has been about lately (the person's recent asks, what was settled, your plan, files "
                   "you changed), read by code from your session file. auto = write tasks only (default, "
                   "[shared_context] run)")
    adv.add_argument("--label")
    r.set_defaults(fn=cmd_run)
    ak = sub.add_parser("ask", help="quick read-only second opinion from the other agent (low effort)")
    ak.add_argument("brief", nargs="*"); ak.add_argument("--brief-file")
    ak.add_argument("--to", choices=["auto", *DELEGATE_AGENTS, *PROVIDER_AGENTS], default="auto")
    ak.add_argument("--from", dest="caller", choices=[*DELEGATE_AGENTS, *PROVIDER_AGENTS, "user"]); ak.add_argument("--cwd")
    ak.set_defaults(fn=cmd_ask)
    tk = sub.add_parser("task", help="long tasks: status, or resume an interrupted one (task-checkpoint)")
    tks = tk.add_subparsers(dest="task_cmd", required=True)
    tst = tks.add_parser("status"); tst.add_argument("task", nargs="?")
    trs = tks.add_parser("resume"); trs.add_argument("task")
    trs.add_argument("--same", action="store_true", help="resume the same session even after a quota stop")
    trs.add_argument("--from", dest="caller", choices=[*DELEGATE_AGENTS, *PROVIDER_AGENTS, "user"])
    for x in (tst, trs):
        x.add_argument("--cwd")
    tk.set_defaults(fn=cmd_task)
    se = sub.add_parser("send", help="send a message into a live Codex desktop/interactive session")
    se.add_argument("message", nargs="*")
    # Codex only: `codex queue` is the one way in from outside. A Claude Code session (terminal or desktop app) has no
    # entrance for another program's message; a Claude sub-agent is followed up with `ccx resume <run_id>`
    se.add_argument("--to", choices=["codex"], default="codex",
                    help="codex (the only one: Claude sessions take no message from outside; use ccx resume)")
    se.add_argument("--thread", help="Codex thread id (see --list)")
    se.add_argument("--list", action="store_true", help="list live sessions (codex agents)")
    se.add_argument("--wait", type=int, default=120, help="seconds to wait for the conversation to go idle (120)")
    se.add_argument("--force", action="store_true", help="send even while you are working in that conversation")
    se.set_defaults(fn=cmd_send)
    v = sub.add_parser("verify", help="record your verdict on a run (calibrates routing and splitting)")
    v.add_argument("run_id", nargs="?")
    v.add_argument("--ok", type=int, choices=[0, 1], help="your verdict: 1 = right, 0 = wrong")
    v.add_argument("--note", default="", help="why (kept with the verdict)")
    v.add_argument("--reason", choices=["unfinished", "wrong", "overreach", "other"],
                   help="with --ok 0: what was wrong (not finished / done wrong / changed what it shouldn't / other)")
    v.add_argument("--dismiss", action="store_true", help="a test, probe or leftover, not real work: it leaves "
                   "'waits for you', counts neither right nor wrong and is never learned from (a later --ok undoes it)")
    vadv = v.add_argument_group("advanced (hooks, spot checks, built-in sub-agents)")
    vadv.add_argument("--sweep", action="store_true", help="record 'probably right' for finished runs nobody judged "
                      "whose check or self-check passed and review (if any) passed (undone ones wait for you); also "
                      "runs quietly at session start. Your own verdict always overrides these")
    vadv.add_argument("--after-h", type=float, default=12.0, help="with --sweep: only runs at least this old (hours)")
    vadv.add_argument("--sample", type=int, metavar="N", help="spot-check N random probable verdicts of this week: "
                      "shows what changed and asks ok / wrong (J7: tells how far probable verdicts can be trusted)")
    vadv.add_argument("--include-evals", action="store_true", help="with --sample: evaluation runs too")
    vadv.add_argument("--list", action="store_true", help="with --sample: print the picks as JSON instead of asking")
    vadv.add_argument("--builtin", metavar="RUNG", help="work your own built-in sub-agent did, e.g. "
                      "claude-builtin:haiku:low")
    vadv.add_argument("--b", type=float, help="with --builtin: the difficulty ccx route used")
    vadv.add_argument("--agent-id", help="with --builtin: the sub-agent's id, so its real cost is read and learned")
    v.set_defaults(fn=cmd_verify)
    pl = sub.add_parser("plan", help="task-split: size / check / template / record / show",
                        add_help=False)
    pl.add_argument("args", nargs=argparse.REMAINDER)
    pl.set_defaults(fn=cmd_plan)
    rs = sub.add_parser("resume", help="follow up in the same sub-session (it keeps its context)")
    rs.add_argument("run_id")
    rs.add_argument("brief", nargs="*")
    rs.add_argument("--brief-file")
    rs.add_argument("--bg", action="store_true", help="run detached, as ccx run --bg (needs the text or "
                    "--brief-file); wait for it with `ccx show <run_id> --wait`")
    rs.add_argument("--wait", type=float, metavar="SECONDS", help="with --bg: wait up to this long in the same call "
                    "and print the final result, as ccx run --bg --wait")
    rs.add_argument("--env-fixed", action="store_true", help="resume a run that stopped on an environment problem "
                    "(kind env) after the person fixed it; without it such a resume is refused and nothing is spent")
    radv = rs.add_argument_group("advanced (routing, caller and limits; most follow-ups need none)")
    radv.add_argument("--tier", choices=["auto", *TIER_ORDER], default="auto")
    radv.add_argument("--from", dest="caller", choices=[*DELEGATE_AGENTS, *PROVIDER_AGENTS, "user"])
    radv.add_argument("--no-escalate", action="store_true")
    rs.add_argument("--model")
    rs.add_argument("--effort")
    radv.add_argument("--budget", type=float, metavar="USD", help="a new spending cap for its own sub-agents (after "
                      "an over_budget stop)")
    rs.add_argument("--review", choices=["auto", "on", "off"], default=None, help="independent review of what this "
                    "follow-up changed, as for ccx run (default: the resumed run's own setting, auto for older runs)")
    rs.add_argument("--check", metavar="CMD", help="replace the run's acceptance command from here on (e.g. one "
                    "that named a missing file or ran no tests)")
    radv.add_argument("--namecheck", choices=["warn", "fail", "off"], help="static check for names no scope "
                      "defines in the functions the run changed: warn = shown to you and the reviewer (default, "
                      "[defaults] namecheck); fail = a hit fails the work like a failed --check; off")
    rs.set_defaults(fn=cmd_resume)
    nc = sub.add_parser("namecheck", help="static check for names no scope defines (NameError waiting to happen) "
                        "in changed Python functions; exit 1 on a hit")
    nc.add_argument("files", nargs="*", help="check these whole files instead of changed functions")
    nc.add_argument("--run", metavar="RUN_ID", help="the changes of that ccx run (what its namecheck saw)")
    nc.add_argument("--base", default="HEAD", help="without --run or files: changes since this commit "
                    "(default HEAD; untracked .py files count as new)")
    nc.add_argument("--json", action="store_true")
    nc.set_defaults(fn=cmd_namecheck)
    sp = sub.add_parser("stop", help="stop a running delegation (its whole process tree); `ccx resume` continues it")
    sp.add_argument("run_id")
    sp.add_argument("--wait", type=float, default=15.0, help="seconds to wait for the run to record the stop (15)")
    sp.set_defaults(fn=cmd_stop)
    b = sub.add_parser("batch", help="run independent tasks in parallel from plan.json")
    b.add_argument("plan")
    b.add_argument("--from", dest="caller", choices=[*DELEGATE_AGENTS, *PROVIDER_AGENTS, "user"])
    b.add_argument("--lanes", type=int, metavar="N", help="warm lanes: pieces for the same project and agent share "
                   "at most N sub-sessions, one piece after another (each still its own run, check and ledger row); "
                   "0 = every piece its own session (default: [lanes] default, 0)")
    b.add_argument("--merge", dest="merge", action="store_const", const=1, default=None,
                   help="experimental: small write pieces (minutes <= 5) for the same folder, agent, model and mode "
                   "run as one run; each keeps its own check, result line and `ccx undo --piece`; a piece not done "
                   "gets one follow-up, then a run of its own (default: [merge] default, off)")
    b.add_argument("--no-merge", dest="merge", action="store_const", const=0, help="off, whatever [merge] default says")
    b.add_argument("--force", action="store_true", help="delegate even with routing.mode off")
    b.set_defaults(fn=cmd_batch)
    ro = sub.add_parser("route", help="which agent/model/effort for a task (rubric -> task-routing)")
    ro.add_argument("text", nargs="*", help="the task description (used to recommend read or write)")
    ro.add_argument("--mode", choices=["read", "write"], help="explicit read/write (else inferred from the text)")
    ro.add_argument("--minutes", type=float, help="how long a skilled engineer would need (standard difficulty unit)")
    ro.add_argument("--to", choices=["auto", *DELEGATE_AGENTS, *PROVIDER_AGENTS], default="auto")
    _routing_args(ro)
    sv = ro.add_argument_group("self vs delegate (needs --lead)")
    sv.add_argument("--lead", help="your own rung, e.g. claude:opus:high")
    sv.add_argument("--ctx-files", nargs="*", help="files you would have to read yourself")
    sv.add_argument("--ctx-tokens", type=int, default=0, help="or the token count directly")
    sv.add_argument("--lead-ctx", type=int, help="tokens each of your requests re-reads (your conversation's size); "
                    "default: read from your conversation's last request")
    sv.add_argument("--turns-left", type=int, default=10, help="turns this session will still run")
    sv.add_argument("--requests", type=float, help="requests you expect the task takes if you do it yourself "
                    "(routing.small_self_by cost; default: 2 + 1.5 per --files)")
    sv.add_argument("--needs", help="comma list that only a ccx run gives: undo,worktree,other-vendor,resume")
    sv.add_argument("--quota", action="append", metavar="AGENT=USED",
                    help="share of an agent's quota already used, e.g. claude=0.4 (Codex's is read automatically)")
    ro.set_defaults(fn=cmd_route)
    pr = sub.add_parser("propose", help="before offering to delegate a large, checkable task: the estimate, one "
                        "line to say, and a record of the offer (H12)")
    for act in ro._actions:                    # the same flags as `ccx route`
        if act.dest != "help":
            pr._add_action(act)
    pr.add_argument("--no", metavar="PROPOSAL", help="the person said no to this offer")
    pr.add_argument("--stats", action="store_true",
                    help="proposed -> agreed -> delegated -> judged, and the share of real runs with a verdict")
    pr.add_argument("--days", type=float, default=7.0)
    pr.set_defaults(fn=cmd_propose)
    bn = sub.add_parser("bench", help="public benchmark data for routing: refresh (weekly by itself) or show sources")
    bn.add_argument("what", choices=["sources", "refresh"], nargs="?", default="sources")
    bn.set_defaults(fn=cmd_bench)
    qu = sub.add_parser("quota", help="subscription quota by pace: projected use of each window at its reset")
    qu.add_argument("--probe", action="store_true", help="one tiny Claude request now, to read its windows")
    qu.add_argument("--backfill", action="store_true", help="read Claude windows from past run logs (once)")
    qu.set_defaults(fn=cmd_quota)
    ab = sub.add_parser("ab", help="close an A/B self-run sample")
    abs_ = ab.add_subparsers(dest="ab_cmd", required=True)
    abd = abs_.add_parser("done"); abd.add_argument("ab_id"); abd.add_argument("--ok", type=int, choices=[0, 1],
                                                                               required=True)
    ab.set_defaults(fn=cmd_ab)
