"""Offline vendor-side accounting and opt-in Stage 5 gates (no model calls)."""
from __future__ import annotations

import math
import re
import statistics


def money(value):
    return (float(value) if isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and value >= 0 else None)


def side(vendor="", model=""):
    """Only explicit vendor/model evidence; provider/CLI names are not vendors."""
    vendor, model = str(vendor or "").lower(), str(model or "").lower()
    v = {"anthropic": "claude", "openai": "codex"}.get(vendor)
    m = ("claude" if model.startswith("claude-") or model in ("sonnet", "opus", "haiku")
         else "codex" if model.startswith(("gpt-", "codex-")) or re.match(r"^o[134](?:-|$)", model) else None)
    if v and m and v != m:
        return "unknown"
    return v or m or "unknown"


def ledger_side(row):
    sides = ({side(row.get("vendor"), row.get("model"))}
             if row.get("vendor") or row.get("model") else set())
    for rung in row.get("rungs") or []:
        parts = str(rung).split(":")
        sides.add(side(model=parts[1]) if len(parts) >= 2 else "unknown")
    return sides.pop() if len(sides) == 1 else "unknown"


def costs(row, ledger=None):
    """Known amounts remain visible when attribution is Unknown. Never infer old child vendors."""
    ledger = row.get("side_ledger") if ledger is None else ledger
    lead, child = money(row.get("lead_usd")), money(row.get("ccx_usd"))
    totals = {s: 0.0 for s in ("claude", "codex", "unknown")}
    totals["claude"] = lead or 0.0  # p4's native Claude lead, including native sub-agents
    complete = lead is not None and child is not None
    if child is None and money(row.get("known_usd")) is not None:
        child = money(row["known_usd"] - (lead or 0))
    attributed = 0.0
    for entry in ledger or []:
        if entry.get("type"):
            continue
        amount = money(entry.get("ae_usd"))
        if amount is None:
            complete = False
            continue
        totals[ledger_side(entry)] += amount
        attributed += amount
    if child is not None and not math.isclose(child, attributed, abs_tol=0.000002):
        # Missing or mismatched ledger: put the entire known child cost in Unknown.
        totals = {"claude": lead or 0.0, "codex": 0.0, "unknown": child}
        complete = False
    complete = complete and totals["unknown"] == 0
    return {**{s + "_side_usd": round(v, 6) for s, v in totals.items()},
            "side_cost_status": "Pass" if complete else "Unknown"}


def aggregate(rows):
    classified = [{**r, **costs(r)} for r in rows]
    return {**{s + "_side_usd": round(sum(r[s + "_side_usd"] for r in classified), 6)
               for s in ("claude", "codex", "unknown")},
            "side_cost_status": "Pass" if classified and all(r["side_cost_status"] == "Pass" for r in classified) else "Unknown"}


def arm_summary(rows):
    wall = [r["wall_s"] for r in rows if money(r.get("wall_s")) is not None]
    return {**aggregate(rows), "attempted": len(rows), "right": sum(r.get("ok") is True for r in rows),
            "env_clean": sum(r.get("env_clean") is True for r in rows),
            "total_known_usd": round(sum(money(r.get("usd")) or money(r.get("known_usd")) or 0 for r in rows), 6),
            "wall_median_s": statistics.median(wall) if wall else None}


def gates(rows, expected=8, candidate="ccxlong"):
    """P5: 16 attempted rows, >=12 clean (>=6/arm), every four-turn session finished."""
    arms = ("self", candidate)
    rows = [r for r in rows if r.get("arm") in arms]
    groups = {a: [r for r in rows if r.get("arm") == a] for a in arms}
    clean = {a: [r for r in rs if r.get("env_clean") is True] for a, rs in groups.items()}
    stats = {a: aggregate(rs) for a, rs in groups.items()}
    keys = [{(r.get("tag"), r.get("round"), r.get("episode"), r.get("task")) for r in groups[a]} for a in arms]
    episodes = {}
    for r in rows:
        episodes.setdefault(tuple(r.get(k) for k in ("tag", "round", "episode", "arm")), []).append(r)
    finished = bool(episodes) and all(len(rs) == 4 and {r.get("turn") for r in rs} == {1, 2, 3, 4}
                                    and len({r.get("session_id") for r in rs}) == 1
                                    and bool(rs[0].get("session_id"))
                                    and all(r.get("rc") == 0 and r.get("subtype") == "success"
                                            and not r.get("error") and r.get("session_match") is True
                                            for r in rs) for rs in episodes.values())
    complete = (expected == 8 and len(rows) == 16 and all(len(groups[a]) == expected for a in arms)
                and keys[0] == keys[1] and len(keys[0]) == expected and finished
                and sum(map(len, clean.values())) >= 12 and all(len(clean[a]) >= 6 for a in arms)
                and all(r.get("cost_complete") is True and money(r.get("usd")) is not None
                        and type(r.get("ok")) is bool for r in rows)
                and all(s["side_cost_status"] == "Pass" for s in stats.values()))

    def ratio(values):
        return values[1] / values[0] if all(v is not None for v in values) and values[0] > 0 else None

    side_known = all(s["side_cost_status"] == "Pass" for s in stats.values())
    total_known = all(r.get("cost_complete") is True and money(r.get("usd")) is not None for r in rows)
    claude_ratio = ratio([stats[a]["claude_side_usd"] for a in arms]) if side_known else None
    total_ratio = ratio([sum(r.get("usd") or 0 for r in groups[a]) for a in arms]) if total_known else None
    walls = [[r["wall_s"] for r in groups[a] if money(r.get("wall_s")) is not None] for a in arms]
    wall_ratio = ratio([statistics.median(v) if v else None for v in walls])
    right = {a: sum(r.get("ok") is True for r in groups[a]) for a in arms}
    conditions = {"claude_cost": claude_ratio is not None and claude_ratio <= .5,
                  "right": right[candidate] >= right["self"]}
    return {"verdict": "Unknown" if not complete or claude_ratio is None else
            ("Pass" if all(conditions.values()) else "Fail"), "arms": stats,
            "right": right, "env_clean": {a: len(clean[a]) for a in arms}, "episodes_finished": finished,
            "claude_cost_ratio": claude_ratio, "total_cost_ratio": total_ratio,
            "wall_median_ratio": wall_ratio,
            "thresholds": {"claude_cost_ratio": .5, "right": f"{candidate} >= self",
                           "env_clean": 12, "env_clean_per_arm": 6, "rows": 16}}
