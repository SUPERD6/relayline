"""Experimental self-first gate around the existing routing/model policies."""
from __future__ import annotations

import math

from . import context, quota


def decision(p, cfg: dict, spec: dict, caller: str) -> dict | None:
    """Permission to consider delegation, not an instruction or authorization to launch it."""
    if str((cfg.get("routing") or {}).get("default", "auto")).strip().lower() != "self_first":
        return None
    from .commands.common import lead_session_id

    lead = (spec.get("lead") or caller).split(":")[0]
    ctx = spec.get("lead_ctx")
    if ctx is None and lead in ("claude", "codex", "dsh"):
        try:
            ctx = context.lead_now(lead, lead_session_id(lead))
        except (OSError, ValueError):
            ctx = None
    ctx_limit = int(((cfg.get("policy") or {}).get("bands") or {}).get("lead_ctx_large", 150000))
    limit = float((cfg.get("quota") or {}).get("avoid_above", 0.8))
    try:
        pressure = quota.pressure(p, spec.get("quota"))
    except (OSError, ValueError):
        pressure = {}
    given = spec.get("quota") or {}
    windows = (pressure.get("pace") or {}).get(lead) or {}
    if lead in given:
        windows = {"given": {"used": given[lead], "projected": given[lead]}}
    known = [w for w in windows.values() if isinstance(w.get("used"), (int, float))
             and math.isfinite(w["used"])]
    missing = sorted(name for name, window in windows.items()
                     if not isinstance(window.get("used"), (int, float)) or not math.isfinite(window["used"]))
    tight = any(w["used"] > limit or (w.get("projected") or 0) > 1 for w in known)
    queue_request = spec.get("_self_first_request_source") == "queue"
    explicit = (queue_request or spec.get("to") not in (None, "", "auto") or
                bool(spec.get("model") or spec.get("provider") or spec.get("role")))
    checks = {"quota_tight": tight if known else "Unknown",
              "quota_missing": missing,
              "large_context": ctx >= ctx_limit if ctx is not None else "Unknown",
              "explicit_request": explicit, "parallel": bool(spec.get("independent_parts"))}
    if queue_request:
        checks["explicit_request_source"] = "queue"
    matched = [key for key, value in checks.items() if value is True]
    # Only the positive CLI marker counts; internal force values retain their ordinary routing meaning.
    forced = spec.get("_user_force") is True
    eligible = bool(matched) or forced
    why = ("routing.default=self_first: " + ("eligible via " + ", ".join(matched) if matched else
           "--force override" if forced else "do it yourself; no delegation condition matched"))
    if queue_request:
        why += " (explicit_request source=queue)"
    return {"applied": not eligible, "eligible": eligible, "checks": checks, "matched": matched,
            "forced": forced, "lead": lead, "lead_ctx_tokens": ctx, "lead_ctx_large": ctx_limit,
            "quota_avoid_above": limit, "quota_windows": windows, "why": why}


def advise(p, cfg: dict, route: dict, spec: dict, caller: str) -> None:
    """Preserve picks/cost estimates, but veto offers and pre-authorization without a condition."""
    if route.get("routing_mode") == "off":
        return
    gate = decision(p, cfg, spec, caller)
    if gate is None:
        return
    route["self_first"] = gate
    if not gate["applied"]:
        return
    route["advice"] = "do-it-yourself: " + gate["why"]
    for key in ("choice", "self_vs_delegate"):
        choice = route.get(key)
        if isinstance(choice, dict):
            choice.update(recommend_before=choice.get("recommend"), recommend="self", why=gate["why"])
    policy = route.get("policy")
    if policy and policy.get("mode"):
        policy.update(mode_before=policy["mode"], mode="self", why=gate["why"])
