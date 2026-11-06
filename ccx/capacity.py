"""Bounded model-capacity recovery, independent of exhausted subscription quota."""
from __future__ import annotations

from .quota_signals import identify, terminal_error

MAX_SWITCHES = 2


def signal(cfg: dict, outcome, stdout: str, stderr: str) -> dict | None:
    if (cfg.get("defaults") or {}).get("capacity_fallback", True) is not True:
        return None
    if outcome.ok or outcome.auth_problem or outcome.kind not in ("error", "ok", "capacity"):
        return None
    # A final unknown error still supersedes an earlier capacity error and stderr prose.
    evidence = terminal_error(stdout)
    if evidence is None:
        lines = stderr.strip().splitlines()
        evidence = identify(lines[-1]) if lines else {"kind": "unknown"}
    return evidence if evidence["kind"] == "capacity" else None


def transition(failed: dict, target: dict | None, cfg: dict | None = None) -> dict:
    """Expose configured tier changes; unknown rung ranks or prices remain unknown."""
    from .config import TIER_ORDER
    from .agents import same_vendor

    before, after = failed.get("tier"), (target or {}).get("tier")
    same = bool(target and same_vendor(failed["agent"], target["agent"], cfg))
    raised = (TIER_ORDER.index(after) > TIER_ORDER.index(before)
              if same and before in TIER_ORDER and after in TIER_ORDER else None)
    return {"same_vendor": same, "from_tier": before, "to_tier": after,
            "tier_upgrade": raised, "cost_increase": None}


def next_plan(req, p, cfg: dict, plan: list[dict], index: int, attempts: list[dict],
              fallback_used: bool) -> tuple[list[dict], dict | None, bool]:
    """Skip every effort of failed models; keep existing ladder and budget constraints."""
    from .plan import _fallback_plan, _provider_envs, _usable, _within_budget

    if sum(a.get("kind") == "capacity" for a in attempts) > MAX_SWITCHES:
        return [], None, fallback_used
    seen = {(a["agent"], a["model"]) for a in attempts}
    remaining = [s for s in plan[index + 1:] if (s["agent"], s["model"]) not in seen]
    if remaining:
        return remaining, None, fallback_used
    if not req.fallback or fallback_used:
        return [], None, fallback_used
    fb = _fallback_plan(req, p, cfg, plan[index])
    if not fb:
        return [], None, fallback_used
    fb = _usable(p, fb)
    if (fb["agent"], fb["model"]) in seen:
        return [], None, fallback_used
    try:
        envs = _provider_envs(cfg, [fb])
        _within_budget(p, cfg, [fb])
    except ValueError:
        return [], None, fallback_used
    return [fb], envs, True
