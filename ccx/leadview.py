"""What the lead is handed when nothing needs its eyes (P0-11 item 3): one line instead of the whole result.

A lead re-reads everything it was handed on every later request of its conversation, so the result of a run is paid
for again and again (129 passed write runs of a real hub, 2026-10: median 860 bytes whole, 509 as one line). When
the check passed and the review passed (or none ran) and nothing asks for the lead (no needs_lead, hint, kind,
edited tests, namecheck hits, policy blocks, open questions, next step, review notes, L2 merge or project answer,
a fix round;
no weak, unchanged-tree, unknown-coverage or changed-yardstick check), the lead gets one JSON line:
what was done (summary, files, diffstat), the check as it was (cmd, passed, exit, what it covers), and the recap (status, check, review, cost, `ccx show <id>` for the rest).
Everything else is as before, whole. `ccx show <id>` always gives the whole result.

Back to the whole result every time: `ccx config set output.lead full` (or CCX_LEAD_VIEW=full for one command).
"""
from __future__ import annotations

import json
import os

SUMMARY_CHARS = 300
# any of these in a result means the lead has something to look at: the whole result goes out
ATTENTION = ("needs_lead", "hint", "kind", "edited_tests", "namecheck", "policy_blocked", "cost_chain_error",
             "base", "retry_after", "open_questions", "next_step",
             "autonomy", "project",      # an L2 merge's outcome (merged, why not, undo), a project's approval rules
             "fixed_after_review_of")    # passed after a fix round: the first review's issues are worth a look


def mode(cfg: dict) -> str:
    env = (os.environ.get("CCX_LEAD_VIEW") or "").strip().lower()
    if env in ("full", "line"):
        return env
    return "full" if str((cfg.get("output") or {}).get("lead", "line")).strip().lower() == "full" else "line"


def clean(res: dict) -> bool:
    """A result that asks nothing of the lead: done, ok, its check passed on this run's own work, review passed or
    none ran."""
    complete = res.get("status") == "done" or (res.get("status") == "partial"
               and res.get("reported_status") == "done" and quota_reassigned(res))
    if not res.get("ok") or not complete or res.get("max_usd") or any(res.get(k) for k in ATTENTION):
        return False
    c = res.get("check") or {}
    if c.get("passed") is not True or c.get("weak") or c.get("status") or c.get("note") \
            or c.get("basis_changed") or c.get("covers_unknown"):
        return False
    rv = res.get("review") or {}
    if rv and (rv.get("verdict") != "pass" or rv.get("error") or rv.get("downgraded") or rv.get("notes")
               or rv.get("edited_tests")):
        return False                  # a pass with [should] / [note] items: the lead reads them
    return True                       # ordinary route details stay out; role auto evidence is retained


def quota_reassigned(res: dict) -> bool:
    fallback = res.get("quota_fallback") or {}
    return bool(fallback.get("from") and fallback.get("to") == res.get("agent"))


def review_not_run(res: dict) -> bool:
    review = res.get("review") or {}
    return bool(review.get("error") or review.get("verdict") == "not-run")


def receipt_notes(res: dict) -> list[str]:
    """Facts that must survive a compact receipt; no claim that an unstarted fallback ran."""
    notes = []
    fallback = res.get("quota_fallback") or {}
    if quota_reassigned(res):
        notes.append(f"reassigned {fallback['from']}→{fallback['to']} (quota)")
    elif res.get("substituted_for"):
        before = res["substituted_for"]
        after = f"{res.get('agent')}:{str(res.get('model') or '').replace('/', ':')}"
        if before != after:
            notes.append(f"reassigned {before}→{after} (model)")
    review = res.get("review") or {}
    cap = res.get("max_usd") or {}
    if cap:
        step = cap.get("stopped_before") or "next step"
        stopped = f"{step} not run" if review.get("verdict") in ("pass", "issues") else "review not run"
        if step != "review" and stopped == "review not run":
            stopped += f"; {step} not run"
        notes.append(f"stopped: budget ${cap['cap']:g} reached, {stopped}")
    if review_not_run(res) and not (cap and cap.get("stopped_before") == "review"):
        why = " ".join(str(review.get("error") or review.get("reason") or "all reviewers failed").split())
        why = why if len(why) <= 80 else why[:77] + "..."
        notes.append(f"review not run ({why})")
    return notes


def receipt_status(res: dict) -> str | None:
    if not res.get("ok") or res.get("status") != "done":
        return res.get("status")
    if res.get("max_usd"):
        return "stopped"
    if (quota_reassigned(res) or review_not_run(res)) and res.get("kind") != "ok_self_checked":
        return "partial"
    return res.get("status")


def receipt_outcome(res: dict) -> str:
    if not res.get("ok"):
        return "ok=false"
    if res.get("kind") != "ok_self_checked" and (
            res.get("max_usd") or quota_reassigned(res) or review_not_run(res)):
        return "ok?"
    return "ok=true"


def line(res: dict) -> dict:
    said = " ".join(str(res.get("summary") or "").split())
    if len(said) > SUMMARY_CHARS:
        said = said[: SUMMARY_CHARS - 3] + "..."
    out = {"run_id": res["run_id"], "agent": res.get("agent"), "model": res.get("model"), "ok": bool(res.get("ok")),
           "status": receipt_status(res), "summary": said, "files_changed": res.get("files_changed", [])}
    for k in ("effort", "requested_agent", "requested_model", "substituted_for", "reported_status", "diffstat", "worktree",
              "continued_from", "chain", "escalated", "quota_fallback", "role", "role_receipt"):
        if res.get(k):
            out[k] = res[k]
    if "base_behind" in res:
        out["base_behind"] = res["base_behind"]
    out["check"] = res["check"]       # as it was (cmd, passed, exit, covers): leads, scripts and the receipt read it
    if res.get("review"):
        out["review"] = {k: res["review"][k] for k in ("verdict", "by") if res["review"].get(k)}
    if (res.get("route") or {}).get("role_effort_reason"):
        out["route"] = res["route"]
    out["view"] = "line"              # the rest: `ccx show <run_id>`
    out["recap"] = res.get("recap", "")
    for note in receipt_notes(res):
        if note not in out["recap"]:
            out["recap"] += ("; " if out["recap"] else "") + note
    return out


def render(res: dict, cfg: dict) -> tuple[dict, bool]:
    """(what to print, whether it is the one line)."""
    if res.get("base_behind", 0) > 0:
        note = f"base: {res['base_behind']} behind upstream"
        recap = res.get("recap", "")
        if not recap.endswith(note):
            res = {**res, "recap": (recap + "; " if recap else "") + note}
    if mode(cfg) == "line" and clean(res):
        return line(res), True
    return res, False


def dumps(obj: dict, one_line: bool) -> str:
    if one_line:
        return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    return json.dumps(obj, ensure_ascii=False, indent=2)
