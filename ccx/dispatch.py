"""Experimental cheap first attempt, gated by caller-supplied acceptance checks."""
from __future__ import annotations

from .config import tier_spec


def cheap_first(cfg: dict) -> bool:
    return (cfg.get("dispatch") or {}).get("cheap_first") is True


def prepare(req, cfg: dict, plan: list[dict], max_escalations: int) -> tuple[list[dict], bool]:
    """Keep explicit model pins/resumes and escalation limits; no task-size heuristics."""
    route = req.route or {}
    explicit = req.model and route.get("source") != "task-routing"
    if (not cheap_first(cfg) or not req.check or req.mode != "write" or req.resume_run
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
    """Unknown comparisons cannot prove a new task failure. Keep original check verdicts."""
    return (not check.get("passed") and not check.get("broken") and not self_checked
            and check.get("baseline_comparison") in ("baseline_passed", "new_failures"))


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
