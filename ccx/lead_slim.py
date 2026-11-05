"""Opt-in lead guidance; no extra routing call for an evidently small task."""
from __future__ import annotations


def guidance_for(p) -> str:
    """Optional guidance must not break existing sync/hook output on bad config."""
    from .config import load_config
    try:
        return small_guidance(load_config(p))
    except (OSError, ValueError, TypeError, AttributeError):
        return ""


def small_guidance(cfg: dict) -> str:
    """One source for managed context, turn hooks and the evaluation prompt.

    Cost sizing and picked tiers still need the normal routing path. Dynamic
    exceptions are left to the lead's available context, never probed here.
    """
    if (cfg.get("lead") or {}).get("slim_small") is not True:
        return ""
    routing = cfg.get("routing") or {}
    if routing.get("small_self_by", "files") != "files":
        return ""
    picked = str((cfg.get("policy") or {}).get("picked", "none")).strip().lower()
    if picked not in ("", "none"):
        return ""
    try:
        files = int(routing.get("small_self_files", 1))
        context = int(((cfg.get("policy") or {}).get("bands") or {}).get("lead_ctx_large", 150000))
        quota = float(routing.get("small_self_quota", 0.9))
    except (ValueError, TypeError, OverflowError):
        return ""
    quota = quota / 100 if quota > 1 else quota
    if files < 1 or context < 1 or not 0 <= quota <= 1:
        return ""
    return (f"If this task clearly touches at most {files} implementation file(s), do it and check it yourself: "
            "no ccx command, brief file or delegation skill load. "
            f"Use normal delegation instead if sizing is uncertain, your context is >= {context} tokens, "
            f"your known quota used is >= {quota:.0%}, or the request needs ccx worktree, undo, resume "
            "or another vendor. Otherwise follow normal delegation instructions.")
