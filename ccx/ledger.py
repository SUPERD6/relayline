"""Run records and the token ledger.

Every run appends one line to <hub>/ccx/ledger.jsonl. `ccx stats` reads it so
routing can be tuned from real numbers instead of guesses.
"""
from __future__ import annotations

import json
import os
import time
from collections import defaultdict
from pathlib import Path

from .config import SUBAGENT_SWITCHES, Paths


def new_run_id(p: Paths) -> str:
    """A fresh run id (YYYYMMDD-HHMMSS-xxxx) whose folder this call created, so no other run can have it: two runs
    started in the same second drew the same 4 hex digits once in a while (1 in 65536 per pair), shared one run
    folder, and the second found the first one's final.lock (CI: 'final.lock was already taken by run')."""
    import uuid
    if getattr(p, "runs", None) is None:         # no hub paths (a caller's stand-in): an id, nothing reserved
        return time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
    p.runs.mkdir(parents=True, exist_ok=True)
    while True:
        rid = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
        try:
            (p.runs / rid).mkdir()
        except FileExistsError:
            continue
        return rid


def append_event(p: Paths, event: dict) -> None:
    """Non-run rows (e.g. the lead's verdict). Readers that aggregate runs skip rows with a 'type'."""
    p.ledger.parent.mkdir(parents=True, exist_ok=True)
    with open(p.ledger, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def append(p: Paths, record: dict) -> None:
    p.ledger.parent.mkdir(parents=True, exist_ok=True)
    with open(p.ledger, "a", encoding="utf-8") as f:
        f.write(json.dumps(_slim(record), ensure_ascii=False) + "\n")


def _slim(record: dict) -> dict:
    slim = {k: record.get(k) for k in ("run_id", "label", "to", "caller", "caller_vendor", "tier", "start_tier",
                                       "mode", "ok", "ts", "kind", "task", "step", "cwd", "session_id",
                                       "lead_session", "continue_depth", "ephemeral", "mode_source")}
    if record.get("merge_of"):        # a follow-up / spun-off run of a `ccx batch --merge` run: count it with that plan
        slim["merge_of"] = record["merge_of"]
    slim["rungs"] = [a.get("rung") for a in record["attempts"]]
    slim["sessions"] = sorted({a["session_id"] for a in record["attempts"] if a.get("session_id")})
    slim["b"] = (record.get("route") or {}).get("b")
    for k in ("trial", "bucket", "no_ab", "proposal"):  # H11: which half of a formal comparison; H12: the offer
        if (record.get("route") or {}).get(k):
            slim[k] = record["route"][k]
    tp = (record.get("route") or {}).get("policy") or {}
    if tp:                       # the whole-workflow tier (task-routing tier_plan): band, estimate, planned mode
        slim.update(policy_tier=tp.get("tier"), band=tp.get("band"), planned_mode=tp.get("mode"),
                    tier_explicit=bool(tp.get("explicit")),
                    estimate_minutes=(tp.get("signals") or {}).get("minutes"))
        if tp.get("proposal_band"):          # a pre-authorised proposal's run: the band it was authorised for
            slim["proposal_band"] = tp["proposal_band"]
    # what actually happened (this is a ccx run, so never "self"): from a person or a script, or the run of a
    # proposal the picked tier pre-authorised as direct (the lead takes the check result as it is), nobody re-checks
    # it (direct); otherwise the lead accepts it (ccx2). planned_mode "self" with actual ccx2 = the run went out
    # although the tier said self
    unchecked = record.get("caller") in (None, "user") or (tp.get("from_proposal") and tp.get("mode") == "direct")
    slim["actual_mode"] = "direct" if unchecked else "ccx2"
    if record.get("resume_chain"):
        slim["resume_chain"] = record["resume_chain"]     # follow-ups of the same task that led to this run
    changed = sorted(k for k, v in (record.get("subagent_switches") or {}).items()
                     if k in SUBAGENT_SWITCHES and v != SUBAGENT_SWITCHES[k])
    if changed:            # [subagent] switches away from today's default (absent: every one at its default)
        slim["subagent_switches"] = changed
    ae = [a["ae_usd"] for a in record["attempts"] if a.get("ae_usd") is not None]
    slim["ae_usd"] = round(sum(ae), 6) if ae else None
    by: dict[str, float] = {}
    for a in record["attempts"]:
        if a.get("ae_usd") is not None:
            by[a["agent"]] = round(by.get(a["agent"], 0.0) + a["ae_usd"], 6)
    slim["ae_by_agent"] = by
    slim["status"] = (record.get("result") or {}).get("status", "error")
    slim["usage"] = sum_usage(record["attempts"])
    u4: dict[str, int] = {}
    for a in record["attempts"]:
        for k, v in (a.get("usage") or {}).items():
            u4[k] = u4.get(k, 0) + int(v or 0)
    slim["usage4"] = u4
    slim["seconds"] = round(sum(a["seconds"] for a in record["attempts"]), 1)
    costs = [a["cost_usd"] for a in record["attempts"] if a.get("cost_usd") is not None]
    slim["cost_usd"] = round(sum(costs), 5) if costs else None
    slim["attempts"] = len(record["attempts"])
    try:                                            # requests / prefix_tokens / first_input, when an attempt recorded them
        from .reqstats import run_fields
        slim.update(run_fields(record["attempts"]))
    except Exception:  # noqa: BLE001 — a ruler; the row is written all the same
        pass
    den = [a["permission_denials"] for a in record["attempts"] if a.get("permission_denials") is not None]
    if den:                      # tool calls the CLI refused (Claude reports them); e.g. a reviewer's shell reads
        slim["permission_denials"] = sum(den)
    if record.get("check"):                         # J7: which acceptance command passed or failed it
        c = record["check"]
        slim["check"] = {"key": check_key(c.get("cmd", ""), record.get("cwd"))[0], "cmd": (c.get("cmd") or "")[:200],
                         "passed": bool(c.get("passed"))}
        if c.get("unchanged_tree"):                 # the run changed nothing: the check ran on the tree it found
            slim["check"]["unchanged_tree"] = True
        cov = c.get("covers") or {}
        if cov:                                     # P1-10: how many test files it ran; did the run change them
            slim["check"]["covers_n"] = None if cov.get("unknown") else cov.get("n_files")
            for k in ("basis_changed", "own_tests_only", "filtered", "added_to", "self_authored"):
                if cov.get(k):
                    slim["check"][k] = True
    return slim


def sum_usage(attempts: list[dict]) -> dict:
    """input = fresh + cache writes (all non-cached prompt), cached = cache reads, output."""
    tot = {"input": 0, "cache_write": 0, "cached": 0, "output": 0}
    for a in attempts:
        u = a.get("usage") or {}
        tot["input"] += int(u.get("input_tokens", 0)) + int(u.get("cache_write_tokens", 0))
        tot["cache_write"] += int(u.get("cache_write_tokens", 0))
        tot["cached"] += int(u.get("cached_input_tokens", 0))
        tot["output"] += int(u.get("output_tokens", 0))
    return tot


def chain_cost(p: Paths, run_ids: list[str]) -> dict:
    """What a chain of runs (a run and its review fix rounds) cost in all, from the ledger: their own rows plus the
    review runs ccx started for them (label review:<run id>). tokens as sum_usage; ae_usd (API-equivalent) and
    cost_usd (billed) sum the rows that know theirs, None when none does."""
    ids = list(dict.fromkeys(run_ids))
    labels = {f"review:{i}" for i in ids}
    mine = [r for r in rows(p) if not r.get("type") and (r.get("run_id") in ids or r.get("label") in labels)]
    tok = {"input": 0, "cache_write": 0, "cached": 0, "output": 0}
    for r in mine:
        for k in tok:
            tok[k] += int((r.get("usage") or {}).get(k) or 0)
    def total(key, nd):
        known = [r[key] for r in mine if r.get(key) is not None]
        return round(sum(known), nd) if known else None
    return {"runs": ids, "reviews": sum(r.get("label") in labels for r in mine), "tokens": tok,
            "ae_usd": total("ae_usd", 6), "cost_usd": total("cost_usd", 5)}


def load_run(p: Paths, run_id: str) -> dict:
    f = p.runs / run_id / "run.json"
    if not f.exists():
        raise FileNotFoundError(f"no ccx run {run_id!r} under {p.runs}")
    return read_record(f)


def read_record(f: Path) -> dict:
    """run.json, read while its run may be replacing it: on Windows the open is refused for that moment (the read
    side of write_record's retry; seen in CI on a test polling a live run)."""
    for i in range(60):
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except PermissionError:
            if i == 59:
                raise
            time.sleep(0.05)
    return {}


def spent_today(p: Paths, agent: str) -> float:
    """USD this agent's attempts cost since local midnight (for a daily cap on pay-per-token providers)."""
    t = time.localtime()
    midnight = time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1))
    return sum((r.get("ae_by_agent") or {}).get(agent, 0.0) for r in rows(p) if (r.get("ts") or 0) >= midnight)


EVAL_PREFIX = "eval-"                       # runs an evaluation script made (scripts/eval, A/B rounds)
SELFTEST_LABELS = ("selftest", "quota-probe", "startup-probe", "two-way-")   # ccx's own probes: say nothing
                                                                            # about how good a rung is


def is_eval(row: dict, runs: dict[str, dict] | None = None) -> bool:
    """True for a run that measured ccx rather than did the person's work: label `eval-...`, started with
    `--no-ab`, one of ccx's own probes, or dismissed (`ccx verify RUN --dismiss`: a test or leftover that counts
    neither way). Statistics that learn or judge from real use leave these out.
    A verdict row has no label of its own: pass `runs` (run_id -> run row, see `runs_by_id`) to judge it by
    the run it points at."""
    if row.get("type") and runs is not None:
        row = runs.get(row.get("run_id") or "", row)
    label = row.get("label") or ""
    return bool(row.get("no_ab") or row.get("dismissed")) or label.startswith(EVAL_PREFIX)         or label.startswith(SELFTEST_LABELS)


def runs_by_id(rows_: list[dict]) -> dict[str, dict]:
    """run_id -> run row (rows without a 'type'), for `is_eval` on the verdict rows that point at them."""
    return {r["run_id"]: r for r in rows_ if not r.get("type") and r.get("run_id")}


SOFT_MAX_OVERTURN = 0.2    # J7: above this share of overturned probable verdicts they stop feeding routing ...
SOFT_MIN_RECHECKED = 5      # ... once at least this many were judged again by the person or the lead


def soft_trust(rows_: list[dict]) -> dict:
    """How often a probable verdict ccx drew by itself (H13, `soft`) was later judged the other way by the person
    or the lead. Too often, and a weak check is passing wrong work as right: probable verdicts then stop teaching."""
    soft: dict[str, bool] = {}
    rechecked = overturned = 0
    for r in rows_:                                     # the ledger is in time order
        if r.get("type") != "verify" or not r.get("run_id"):
            continue
        rid = r["run_id"]
        if r.get("soft"):
            soft.setdefault(rid, bool(r.get("ok")))
        elif rid in soft:
            rechecked += 1
            overturned += bool(r.get("ok")) != soft.pop(rid)
    n_soft = rechecked + len(soft)
    rate = overturned / rechecked if rechecked else None
    learn_ok = not (rechecked >= SOFT_MIN_RECHECKED and rate > SOFT_MAX_OVERTURN)
    return {"soft": n_soft, "rechecked": rechecked, "overturned": overturned,
            "overturn_rate": None if rate is None else round(rate, 3), "learn": learn_ok}


CHECK_MIN_JUDGED = 3        # J7: a check command that passed this many runs judged by a person or the lead ...
CHECK_MAX_WRONG = 0.2       # ... of which more than this share were wrong lets wrong work through


def check_key(cmd: str, cwd: str | None) -> tuple[str, str, str]:
    """(key, command, place) of an acceptance check. The same command means different things in different
    projects, so the place counts: the folder's name, numbers collapsed (round-1 / round-2 copies of a task
    are one place) and a ccx worktree counted as its repository."""
    import hashlib
    import re
    norm = " ".join((cmd or "").split())
    parts = [x for x in re.split(r"[\\/]+", (cwd or "").lower()) if x]
    if len(parts) >= 3 and parts[-3] == ".ccx-worktrees":
        parts = parts[:-1]
    place = re.sub(r"\d+", "#", parts[-1]) if parts else ""
    return hashlib.sha1(f"{norm}\0{place}".encode("utf-8")).hexdigest()[:12], norm, place


def _run_check(row: dict, p: Paths | None) -> dict | None:
    if "check" in row:
        return row["check"]
    if p is None or not row.get("run_id"):
        return None
    try:
        c = load_run(p, row["run_id"]).get("check")
    except (FileNotFoundError, ValueError, OSError):
        return None
    if not c:
        return None
    key, _, _ = check_key(c.get("cmd", ""), row.get("cwd"))
    return {"key": key, "cmd": c.get("cmd", ""), "passed": bool(c.get("passed"))}


def check_trust(rows_: list[dict], p: Paths | None = None) -> dict[str, dict]:
    """J7: per acceptance command (and place), how often it passed work that a person or the lead then judged
    wrong. Evaluation runs count too: their verdicts come from hidden tests, the best evidence there is.
    Rows from before ccx kept the check in the ledger are read from their run.json when `p` is given."""
    final = {}
    for r in rows_:                                     # the person's or the lead's last word; not probable ones
        if r.get("type") == "verify" and r.get("run_id") and not r.get("soft"):
            final[r["run_id"]] = bool(r.get("ok"))
    out: dict[str, dict] = {}
    for r in rows_:
        if r.get("type") or r.get("run_id") not in final:
            continue
        c = _run_check(r, p)
        if not c or not c.get("passed"):
            continue
        key = c.get("key") or check_key(c.get("cmd", ""), r.get("cwd"))[0]
        _, cmd, place = check_key(c.get("cmd", ""), r.get("cwd"))
        g = out.setdefault(key, {"cmd": cmd, "place": place, "judged": 0, "wrong": 0, "runs": []})
        g["judged"] += 1
        if not final[r["run_id"]]:
            g["wrong"] += 1
            g["runs"].append(r["run_id"])
    for g in out.values():
        g["wrong_rate"] = round(g["wrong"] / g["judged"], 3)
        g["weak"] = g["judged"] >= CHECK_MIN_JUDGED and g["wrong_rate"] > CHECK_MAX_WRONG
    return out


WEAK_CHECK_NOTE = "this acceptance command has let wrong work through before: look at the change, not only the check"


def rows(p: Paths) -> list[dict]:
    if not p.ledger.exists():
        return []
    out = []
    for line in p.ledger.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return _mark_dismissed(out)


def _mark_dismissed(rows_: list[dict]) -> list[dict]:
    """Run rows of runs dismissed later (a `dismiss` row; a later verdict of the person or the lead undoes it) get
    `dismissed: True`, so `is_eval` leaves them out wherever real use is counted."""
    gone: set[str] = set()
    for r in rows_:
        if r.get("type") == "dismiss" and r.get("run_id"):
            gone.add(r["run_id"])
        elif r.get("type") == "verify" and not r.get("soft"):
            gone.discard(r.get("run_id"))
    if gone:
        for r in rows_:
            if not r.get("type") and r.get("run_id") in gone:
                r["dismissed"] = True
    return rows_


def stats(p: Paths) -> list[dict]:
    agg: dict[tuple, dict] = defaultdict(lambda: {"runs": 0, "done": 0, "escalated": 0,
                                                 "input": 0, "cached": 0, "output": 0,
                                                 "seconds": 0.0, "cost_usd": 0.0, "cost_known": 0})
    for r in rows(p):
        if r.get("type"):
            continue
        a = agg[(r["to"], r["start_tier"])]
        a["runs"] += 1
        a["done"] += r.get("status") == "done"
        a["escalated"] += r.get("attempts", 1) > 1
        for k in ("input", "cached", "output"):
            a[k] += r["usage"].get(k, 0)
        a["seconds"] += r.get("seconds", 0)
        if r.get("cost_usd") is not None:
            a["cost_usd"] += r["cost_usd"]
            a["cost_known"] += 1
    out = []
    for (agent, tier), a in sorted(agg.items()):
        n = a["runs"]
        out.append({"agent": agent, "tier": tier, "runs": n,
                    "done_rate": round(a["done"] / n, 2), "escalated": a["escalated"],
                    "avg_input": a["input"] // n, "avg_cached": a["cached"] // n,
                    "avg_output": a["output"] // n, "avg_seconds": round(a["seconds"] / n, 1),
                    "cost_usd": round(a["cost_usd"], 4) if a["cost_known"] else None})
    return out


def repair(p: Paths, apply: bool = False) -> dict:
    """Re-count Codex attempts written before ccx counted only the growth of a resumed session (`codex exec
    resume` reports the session's running total). Dry run unless apply; idempotent (fixed attempts carry
    codex_total). The ledger is backed up first."""
    import os
    import time
    from . import learn
    from .agents.codex import _codex_growth, _codex_total
    recs = []
    for f in sorted(p.runs.glob("*/run.json")) if p.runs.exists() else []:
        try:
            recs.append((f, json.loads(f.read_text(encoding="utf-8"))))
        except (OSError, json.JSONDecodeError):
            continue
    recs.sort(key=lambda x: x[1].get("ts") or 0)
    seen, changed, fixed = {}, [], []
    for f, rec in recs:
        before = sum(a.get("ae_usd") or 0 for a in rec.get("attempts", []))
        touched = False
        for a in rec.get("attempts", []):
            sid, u = a.get("session_id"), a.get("usage")
            if a.get("agent") != "codex" or not sid or not u:
                continue
            if a.get("codex_total"):                       # counted correctly already
                seen[sid] = a["codex_total"]
                continue
            total = _codex_total(u)
            if sid in seen and all(total[k] >= seen[sid].get(k, 0) for k in total):
                a["usage"] = _codex_growth(total, seen[sid])
                ae = learn.price_usd(p, "codex", a.get("model"), a["usage"])
                a["ae_usd"] = round(ae, 6) if ae is not None else None
                touched = True
            a["codex_total"] = total
            seen[sid] = total
        if touched:
            after = sum(a.get("ae_usd") or 0 for a in rec["attempts"])
            changed.append({"run_id": rec["run_id"], "ae_before": round(before, 5), "ae_after": round(after, 5)})
            fixed.append((f, rec))
    out = {"applied": apply, "runs_fixed": len(changed), "runs": changed,
           "ae_before": round(sum(c["ae_before"] for c in changed), 5),
           "ae_after": round(sum(c["ae_after"] for c in changed), 5)}
    if not apply or not fixed:
        out["note"] = "dry run: add --apply" if not apply else "nothing to fix"
        return out
    for f, rec in fixed:
        tmp = f.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, f)
    if p.ledger.exists():
        by_id = {rec["run_id"]: rec for _, rec in fixed}
        lines = p.ledger.read_text(encoding="utf-8").splitlines()
        bak = p.ledger.with_name(f"ledger.jsonl.bak-{time.strftime('%Y%m%d%H%M%S')}")
        bak.write_text("\n".join(lines) + "\n", encoding="utf-8")
        new = []
        for line in lines:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                new.append(line)
                continue
            rid = row.get("run_id")
            new.append(json.dumps(_slim(by_id[rid]), ensure_ascii=False)
                       if not row.get("type") and rid in by_id else line)
        tmp = p.ledger.with_suffix(".jsonl.tmp")
        tmp.write_text("\n".join(new) + "\n", encoding="utf-8")
        os.replace(tmp, p.ledger)
        out["ledger_backup"] = str(bak)
    return out


def claim_final(run_dir: Path, by: str) -> bool:
    """Only one writer closes a run (its own ccx process, or `ccx stop` when that process is gone): the first to
    create final.lock writes the final state and the ledger row; the other leaves both alone."""
    try:
        fd = os.open(run_dir / "final.lock", os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(json.dumps({"by": by, "pid": os.getpid(), "ts": time.time()}))
    return True


def write_record(run_dir: Path, record: dict) -> None:
    tmp = run_dir / "run.json.tmp"
    tmp.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    replace(tmp, run_dir / "run.json")      # ccx's own file: atomic replace is fine here


def replace(tmp: Path, dst: Path) -> None:
    """os.replace that waits up to 3 s for a reader. Windows refuses to replace a file another process has open for
    reading (`ccx stop` / `ccx show` / the ui polling it) for that moment. Lost there, a run's final state stayed
    `running` (CI, PR #37) and a background discussion's state write failed (CI, PR #67)."""
    for i in range(60):
        try:
            os.replace(tmp, dst)
            return
        except PermissionError:
            if i == 59:
                raise
            time.sleep(0.05)
