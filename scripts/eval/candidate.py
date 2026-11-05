"""Opt-in Stage 3 candidate assertions and telemetry. No product defaults change."""
from __future__ import annotations

from pathlib import Path

SWITCHES = {"delegate.user_words": True, "routing.small_self_run": True,
            "routing.strict_escalate": True, "review.mode": "read"}
SLIM_SWITCHES = {**SWITCHES, "lead.slim_small": True}


def assert_config(hub: Path, *, slim: bool = False) -> dict:
    from ccx.config import Paths, load_config
    cfg = load_config(Paths(hub))
    want = SLIM_SWITCHES if slim else SWITCHES
    got = {key: (cfg.get(key.split(".")[0]) or {}).get(key.split(".")[1]) for key in want}
    if got != want:
        name = "ccx3cand" if slim else "ccx2cand"
        raise RuntimeError(f"{name} switches not applied: {got}")
    return got


def set_slim(hub: Path) -> dict:
    from ccx.config import Paths, set_setting
    set_setting(Paths(hub), "lead.slim_small", "true")
    return assert_config(hub, slim=True)


def collect(hub: Path, events: list[dict], run_ids: list[str], record) -> dict:
    decisions = [e for e in events if e.get("type") == "small_self_run"]
    runs = []
    for rid in run_ids:
        rec = record(hub, rid)
        if rec and not str(rec.get("label") or "").startswith("review:"):
            runs.append(rec)
    attempts = [{"run_id": r["run_id"], **{k: a.get(k) for k in ("tier", "rung", "model", "effort")}}
                for r in runs for a in r.get("attempts") or []]
    return {"small_self": bool(decisions) if decisions or runs else None,
            "small_self_decisions": decisions,
            "actual_mode": "self" if decisions and not attempts else "delegated" if attempts else "Unknown",
            "actual_tiers": attempts,
            "user_words": [{"run_id": r["run_id"], **(r.get("user_words") or {"source": None, "chars": 0})}
                           for r in runs],
            "prompt_changed": "ccx2small guidance plus required --files estimate"}
