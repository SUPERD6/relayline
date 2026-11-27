"""Opt-in lead guidance; no extra routing call for an evidently small task."""
from __future__ import annotations


MINIMAL_CONTEXT = ("ccx is available: run `ccx -h` or load the agent-delegate skill for commands and details.\n"
                   "Load shared context on demand with `ccx mem delta --as <tool> --full`.")


def minimal_context_on(p) -> bool:
    """Experimental context suppression, independent of small-task routing guidance."""
    from .config import load_config
    try:
        return (load_config(p).get("lead") or {}).get("slim_context") is True
    except (OSError, ValueError, TypeError, AttributeError):
        return False


# Proven cells of the trade-off map: (task type, who to delegate to). v0 is empty on purpose: nothing is proven
# until the round-2 group-B offline replay (#544) says so. A cell goes in here only with that evidence.
PROVEN_CELLS: tuple[tuple[str, str], ...] = ()


def route_map_guidance(cfg: dict) -> str:
    """The trade-off map's split rule (#545), one short paragraph; '' unless lead.route_map is on.

    Self-work costs nothing: the text says not to call ccx or start a process to decide.
    """
    if (cfg.get("lead") or {}).get("route_map") is not True:
        return ""
    if PROVEN_CELLS:
        cells = "; ".join(f"{kind} -> {who}" for kind, who in PROVEN_CELLS)
    else:
        cells = "none yet"
    return ("Task split rule (v0): do the task yourself, with no ccx command and no extra process, "
            "unless the person asks for delegation or the task type is a proven cell below. "
            f"Proven cells (task type -> delegate to): {cells}. "
            "If unsure whether a task fits a cell, do it yourself. This overrides other delegation advice here.")


def guidance_for(p) -> str:
    """Optional guidance must not break existing sync/hook output on bad config."""
    from .config import load_config
    try:
        cfg = load_config(p)
        return "\n".join(t for t in (small_guidance(cfg), route_map_guidance(cfg)) if t)
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
