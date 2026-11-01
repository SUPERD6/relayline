"""Verdicts on finished runs: the lead's (`ccx verify`), on built-in sub-agents, and the probable ones ccx
draws from the evidence (H13) (from delegate.py)."""
from __future__ import annotations

import time
from pathlib import Path

from . import learn, ledger
from .coverage import reviewed_ok
from .config import Paths
from .ledger import write_record as _write_record

# ---- verdicts without asking (H13) -------------------------------------------------------------------------------
SOFT_AFTER_H = 12.0          # a finished run nobody judged for this long, with good evidence, counts as probably right


REASONS = ("unfinished", "wrong", "overreach", "other")


def _hard_verdict(record: dict) -> bool:
    v = record.get("verdict") or {}
    return bool(v) and not v.get("soft")


def _soft_verdict(p: Paths, record: dict, ok: bool, reason: str, note: str) -> None:
    """A verdict ccx draws from the evidence. Kept apart from the lead's (`soft`), and a later `ccx verify`
    overrides it. It feeds routing only where nothing was learned yet, or to correct the provisional record."""
    record["verdict"] = {"ok": ok, "soft": True, "reason": reason, "note": note, "ts": time.time()}
    how = record.get("learned")
    auto_ok = bool(record.get("ok") and (record.get("result") or {}).get("status") == "done")
    if (record.get("route") or {}).get("b") is not None and (how is None or (how == "auto" and auto_ok != ok)) \
            and ledger.soft_trust(ledger.rows(p))["learn"]:      # J7: not when they were often overturned
        try:
            learn.record_outcomes(p, record, final_ok=ok)
            record["learned"] = "soft"
        except Exception:  # noqa: BLE001 — learning is best effort
            pass
    _write_record(p.runs / record["run_id"], record)
    ledger.append_event(p, {"type": "verify", "run_id": record["run_id"], "ok": ok, "soft": True,
                            "reason": reason, "ts": time.time()})


def soft_verdicts(p: Paths, min_age_h: float = SOFT_AFTER_H, now: float | None = None) -> list[dict]:
    """Finished runs nobody judged within `min_age_h`: 'probably right' when ccx's own check passed or the
    sub-agent's self-check ran, the independent review (if any) passed, it was neither undone nor sent back, and the
    check command has not let wrong work through before (J7). Undone runs and runs without such evidence stay
    unjudged: they wait for the person (the UI's 'please review' list)."""
    now = now or time.time()
    rows = ledger.rows(p)
    judged = {r.get("run_id") for r in rows if r.get("type") in ("verify", "dismiss")}
    out, trust = [], None
    for r in rows:
        if r.get("type") or r.get("run_id") in judged or not r.get("ok") or r.get("status") != "done":
            continue
        if now - float(r.get("ts") or now) < min_age_h * 3600 or r.get("ephemeral") or r.get("dismissed"):
            continue
        if (r.get("label") or "").startswith(("review:", "handoff-from-transcript", *ledger.SELFTEST_LABELS)):
            continue
        try:
            record = ledger.load_run(p, r["run_id"])
        except (FileNotFoundError, KeyError, ValueError):
            continue
        if _hard_verdict(record) or (record.get("verdict") or {}).get("soft") or record.get("dismissed"):
            continue
        if (p.runs / r["run_id"] / "undone.json").exists():       # undone: right or wrong is the person's call
            continue
        if record.get("kind") in ("check_failed", "check_broken", "review_issues", "review_failed", "needs_write",
                                 "split", "no_changes", "no_answer"):
            continue
        if record.get("kind") == "ok_self_checked" and not reviewed_ok(record):
            continue                    # its check is the sub-agent's own tests, no evidence (P0-8), and no review
            # held it against the task text and passed
        if (record.get("namecheck") or {}).get("hits"):  # a possible NameError (warn mode): the lead looks first
            continue
        if record.get("max_usd"):       # P0-15: the cap stopped a step (a review, say): the lead decides
            continue
        check = record.get("check")
        rev = (record.get("review") or {}).get("verdict")
        if rev == "pass" and (record.get("review") or {}).get("downgraded"):
            rev = "unclear"             # its [must]s were only downgraded (must_needs_repro): not a review pass
        checked = (check and check.get("passed")) or \
            (record.get("result") or {}).get("verification", "not-run") not in ("", "not-run")
        if not checked or (check and not check.get("passed")) or rev in ("issues", "unclear"):
            continue
        if check:                       # J7: a command that passed wrong work before is no evidence: ask the person
            trust = trust if trust is not None else ledger.check_trust(rows, p)
            if (trust.get(ledger.check_key(check.get("cmd", ""), record.get("cwd"))[0]) or {}).get("weak"):
                continue
        why = "ccx check passed" if check else "self-checked"
        if check and check.get("covers"):
            from .coverage import text
            why += f" ({text(check['covers'])})"
        if rev == "pass":
            why += ", review passed"
        _soft_verdict(p, record, True, "", f"auto after {min_age_h:g} h: {why}, not undone or reworked")
        out.append({"run_id": r["run_id"], "ok": True, "why": why})
    return out


def verify_builtin(p: Paths, rung: str, b: float, ok: bool, agent_id: str | None = None, note: str = "") -> dict:
    """Verdict on work the lead gave its OWN built-in sub-agent (ccx did not run it, so there is no run record).
    With the sub-agent's id its real cost is read from its transcript; routing learns from both."""
    from .usage import claude_events, codex_events
    cost = None
    if agent_id:
        since = time.time() - 7 * 86400
        ids = {agent_id, f"agent-{agent_id}"}
        events = claude_events(since, set()) if rung.startswith("claude") else codex_events(since, set())[0]
        mine = [e for e in events if e.get("role") == "builtin" and e.get("session") in ids]
        if mine:
            agent = rung.split("-")[0]
            cost = round(sum(learn.price_usd(p, agent, e["model"], e["usage"]) or 0 for e in mine), 6)
    tr = learn.module(p, "routing")
    with tr._Lock(tr.state_path()):
        pri, st = tr.load_priors(), tr.load_state()
        if hasattr(tr, "builtin_rungs"):                 # built-in rungs are not in the priors file itself
            pri = {**pri, "rungs": pri["rungs"] + tr.builtin_rungs(pri, rung.replace("-builtin", "", 1))}
        learned = tr.record(rung, float(b), ok, pri, st, cost_usd=cost)
        tr.save_state(st)
    ledger.append_event(p, {"type": "builtin_verdict", "rung": rung, "b": b, "ok": ok, "cost_usd": cost,
                            "agent_id": agent_id, "note": note, "ts": time.time()})
    return {"builtin": rung, "verdict": ok, "cost_usd": cost, "learned": learned,
            **({} if cost is not None or not agent_id else {"note": "no transcript found for that id: cost not learned"})}


def verify(p: Paths, run_id: str, ok: bool, note: str = "", reason: str = "") -> dict:
    """The lead's verdict after checking the work. This is the authoritative learning signal; it overrides a
    verdict ccx drew by itself (soft). `reason` (when not ok): unfinished | wrong | overreach | other."""
    if reason and reason not in REASONS:
        raise ValueError(f"--reason must be one of {', '.join(REASONS)}")
    record = ledger.load_run(p, run_id)
    prev = record.get("verdict")
    record["verdict"] = {"ok": ok, "note": note, "reason": reason, "ts": time.time()}
    record.pop("dismissed", None)                     # a real verdict counts again (ledger._mark_dismissed too)
    learned = []
    how = record.get("learned")
    auto_ok = bool(record.get("ok") and (record.get("result") or {}).get("status") == "done")
    provisional_ok = prev.get("ok") if prev and prev.get("soft") else auto_ok
    if (how is None                                   # nothing recorded yet
            or (how in ("auto", "soft") and provisional_ok != ok)   # the provisional record was wrong: correct it
            or (how == "lead" and prev and prev.get("ok") != ok)):   # the lead changed its mind
        learned = learn.record_outcomes(p, record, final_ok=ok)
        if (record.get("route") or {}).get("b") is not None:
            record["learned"] = "lead"
    if record.get("task") and record.get("step"):
        cwd = Path(record["cwd"])
        if ok:
            learn.checkpoint(p, cwd, "done", record["task"], str(record["step"]), "--note",
                             note or f"verified ccx run {run_id}")
        else:
            learn.checkpoint(p, cwd, "fail", record["task"], str(record["step"]), "--reason", "error",
                             "--note", note or f"ccx run {run_id} failed verification")
    _write_record(p.runs / run_id, record)
    ledger.append_event(p, {"type": "verify", "run_id": run_id, "ok": ok, "reason": reason, "ts": time.time()})
    try:                                   # judged: final now (sessions.archive = after_run)
        from . import archive
        archive.after_run(p, record)
    except Exception:  # noqa: BLE001
        pass
    return {"run_id": run_id, "verdict": ok, "learned": learned, **({"reason": reason} if reason else {})}


def dismiss(p: Paths, run_id: str, note: str = "") -> dict:
    """A run that was a test, a probe or a leftover, not the person's work: kept, but neither right nor wrong.
    It leaves the 'waits for you' lists, `--sweep` skips it and routing and splitting never learn from it
    (`ledger.is_eval`). A run the person or the lead already judged keeps that verdict: dismissing it is refused.
    What a run taught routing when it ended (its provisional record) cannot be taken back; the answer says so."""
    record = ledger.load_run(p, run_id)
    if _hard_verdict(record):
        raise ValueError(f"run {run_id} already has a verdict ({'ok' if record['verdict'].get('ok') else 'not ok'}); "
                         "`ccx verify RUN --ok 0|1` changes it")
    record["dismissed"] = {"note": note, "ts": time.time()}
    _write_record(p.runs / run_id, record)
    ledger.append_event(p, {"type": "dismiss", "run_id": run_id, "note": note, "ts": time.time()})
    return {"run_id": run_id, "dismissed": True, "learned": [],
            **({"note": f"its provisional record ({record['learned']}) already in routing stays"}
               if record.get("learned") else {})}


# ---- spot checks of probable verdicts (J7) ------------------------------------------------------------------------
def sample_soft(p: Paths, n: int = 5, days: float = 7, seed: int | None = None,
                include_evals: bool = False) -> list[dict]:
    """Up to n probable verdicts (soft) of the last `days` that nobody judged since, picked at random, each with
    what changed, so the person can say ok or wrong. Their answers are what `ledger.soft_trust` counts."""
    import random
    rows = ledger.rows(p)
    runs = ledger.runs_by_id(rows)
    since = time.time() - days * 86400
    soft: dict[str, dict] = {}
    for r in rows:
        if r.get("type") != "verify" or not r.get("run_id"):
            continue
        if r.get("soft"):
            if (r.get("ts") or 0) >= since and (include_evals or not ledger.is_eval(r, runs)):
                soft.setdefault(r["run_id"], r)
        else:
            soft.pop(r["run_id"], None)                 # judged by a person or the lead since
    ids = sorted(soft)
    random.Random(seed).shuffle(ids)
    out = []
    for rid in ids[:max(n, 0)]:
        try:
            rec = ledger.load_run(p, rid)
        except (FileNotFoundError, ValueError):
            continue
        res = rec.get("result") or {}
        check = rec.get("check") or {}
        out.append({"run_id": rid, "probable": "right" if soft[rid].get("ok") else "wrong",
                    "label": rec.get("label") or "", "who": (rec.get("attempts") or [{}])[-1].get("rung") or rec.get("to"),
                    "summary": (res.get("summary") or "")[:400], "files": list(res.get("files_changed") or [])[:12],
                    "check": f"{check.get('cmd')}: {'passed' if check.get('passed') else 'failed'}" if check else None,
                    "verification": (res.get("verification") or "")[:200],
                    "why": (rec.get("verdict") or {}).get("note", "")})
    return out


def review_sample(p: Paths, picks: list[dict], ask=input, show=print) -> list[dict]:
    """Ask about each pick: ok, wrong or skip. ok/wrong become the person's verdict (`verify`)."""
    done = []
    for i, x in enumerate(picks, 1):
        show(f"\n[{i}/{len(picks)}] {x['run_id']}  {x['label']}  ({x['who']}, probably {x['probable']})")
        show(f"  {x['summary']}")
        if x["files"]:
            show("  files: " + ", ".join(x["files"]))
        if x["check"]:
            show(f"  check: {x['check']}")
        elif x["verification"]:
            show(f"  self-check: {x['verification']}")
        while True:
            try:
                a = (ask("  ok / wrong / skip [o/w/s]: ") or "").strip().lower()
            except EOFError:                            # no one at the keyboard after all: stop, judge nothing more
                return done
            if a in ("o", "ok", "w", "wrong", "s", "skip", ""):
                break
        if a in ("o", "ok", "w", "wrong"):
            ok = a.startswith("o")
            verify(p, x["run_id"], ok, note="spot check (ccx verify --sample)", reason="" if ok else "wrong")
            done.append({"run_id": x["run_id"], "ok": ok, "overturned": ok != (x["probable"] == "right")})
    return done
