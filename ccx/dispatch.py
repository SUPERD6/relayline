"""Experimental cheap first attempt, gated by caller-supplied acceptance checks."""
from __future__ import annotations

import re
import shlex

from .config import tier_spec


def baseline_capable(cmd: str) -> bool:
    """Recognize direct pytest/unittest invocations; opaque scripts keep the ordinary route."""
    from .coverage import _parts
    try:
        lexer = shlex.shlex(cmd.replace("\\", "/"), posix=True, punctuation_chars="&|;<>")
        lexer.whitespace_split = True
        if any(token and set(token) <= set("&|;<>") and token != "&&" for token in lexer):
            return False
    except ValueError:
        return False
    found = False
    for tokens in _parts(cmd):
        if tokens[0] == "cd" and len(tokens) == 2 and not found:
            continue
        executable = tokens[0].rsplit("/", 1)[-1].lower().removesuffix(".exe")
        if executable in ("pytest", "py.test"):
            found = True
            continue
        if not re.fullmatch(r"python(?:\d+(?:\.\d+)*)?|py", executable):
            return False
        args = tokens[1:]
        while args and args[0] in ("-X", "-W", "-u", "-B", "-I", "-S", "-s", "-E"):
            count = 2 if args[0] in ("-X", "-W") else 1
            args = args[count:]
        if len(args) < 2 or args[0] != "-m" or args[1] not in ("pytest", "unittest"):
            return False
        found = True
    return found


def tainted(covers: dict) -> bool:
    """Any worker-written part of the acceptance basis invalidates its independence."""
    return any(covers.get(k) for k in ("self_authored", "edited", "written", "added_to", "basis_changed"))


def retry_cli(ok: bool, kind: str) -> bool:
    """Cheap-dispatch CLI failures/timeouts can use the next authorized rung; auth/env cannot."""
    return not ok and kind in ("error", "timeout")


def cheap_first(cfg: dict) -> bool:
    return (cfg.get("dispatch") or {}).get("cheap_first") is True


def prepare(req, cfg: dict, plan: list[dict], max_escalations: int) -> tuple[list[dict], bool]:
    """Keep explicit model pins/resumes and escalation limits; no task-size heuristics."""
    route = req.route or {}
    explicit = req.model and route.get("source") != "task-routing"
    if (not cheap_first(cfg) or not req.check or not baseline_capable(req.check) or req.mode != "write" or req.resume_run
            or explicit or route.get("role_fixed_model") or max_escalations < 1):
        return plan, False
    spec = (cfg.get("tiers", {}).get("T1", {}).get(req.to))
    if not spec:
        return plan, False
    spec = tier_spec(cfg, "T1", req.to)
    first = {"agent": req.to, "model": spec["model"], "effort": spec["effort"],
             "lean": bool(spec.get("lean", False)), "tier": "T1",
             "rung": f"{req.to}:{spec['model']}:{spec['effort']}"}
    if first["rung"] == plan[0]["rung"]:
        return plan, True
    return [first, *plan[:max_escalations]], True


def check_config(cfg: dict, active: bool) -> dict:
    # Enabling dispatch also enables the existing baseline comparison for this run.
    return {**cfg, "check": {**(cfg.get("check") or {}), "baseline": "on_fail"}} if active else cfg


def may_escalate(check: dict, self_checked: bool = False) -> bool:
    """Unknown baselines do not block an authorized retry; known baseline-only failures do."""
    return (not check.get("passed") and not check.get("broken") and not self_checked
            and check.get("baseline_comparison") in (None, "Unknown", "baseline_passed", "new_failures"))


def receipt(record: dict) -> None:
    """Add phase costs and a rate numerator/denominator without changing old fields."""
    if "dispatch" not in record:
        return
    attempts = record.get("attempts") or []
    def cost(rows):
        return (round(sum(a["ae_usd"] for a in rows), 6)
                if all(a.get("ae_usd") is not None for a in rows) else None)
    escalated = any(a.get("dispatch_phase") == "escalation" for a in attempts)
    record["dispatch"].update(
        attempted=int(bool(attempts)), escalated=int(escalated),
        escalation_rate=float(escalated) if attempts else None,
        first_usd=cost([a for a in attempts if a.get("dispatch_phase") == "first"]),
        escalation_usd=cost([a for a in attempts if a.get("dispatch_phase") == "escalation"]),
        recovery_usd=cost([a for a in attempts if a.get("dispatch_phase") == "recovery"]))
