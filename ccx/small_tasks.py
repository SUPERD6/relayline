"""Experimental run-time small-task gate; disabled unless explicitly configured."""
from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace


def enabled(cfg: dict, key: str) -> bool:
    return str((cfg.get("routing") or {}).get(key, False)).strip().lower() in ("true", "on", "yes", "1")


def run_advice(p, cfg: dict, a, text: str, caller: str, small_self) -> dict | None:
    """Reuse the advisory rule, including its tier/context/quota exceptions, before --bg detaches."""
    if (not enabled(cfg, "small_self_run") or a.force or caller in ("user", "unknown")
            or os.environ.get("CCX_ROLE") == "subagent" or int(os.environ.get("CCX_DEPTH", "0") or 0) > 0
            or getattr(a, "mode", None) == "read"):
        return None
    from .signals import measure
    from .modes import resolve_mode
    if resolve_mode(getattr(a, "mode", None), text)["mode"] == "read":
        return None
    route = {"objective": measure(text, Path(a.cwd or os.getcwd()))}
    args = SimpleNamespace(**vars(a))
    args.lead = caller
    args.needs = "worktree" if getattr(a, "worktree", False) else ""
    local = {**cfg, "routing": {**(cfg.get("routing") or {}), "small_self": True}}
    small_self(p, local, route, args, 0, delegates=True)
    if not (route.get("small_self") or {}).get("applied"):
        return None
    route["advice"] = "do-it-yourself: small task; the lead should implement and check it itself"
    return {"state": "small_self", "delegated": False, "small_self": route["small_self"],
            "advice": route["advice"], "hint": "do it yourself, or add --force to delegate anyway"}
