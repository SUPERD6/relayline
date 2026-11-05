"""Stage 3 descriptive statistics, including failed/interrupted attempts and missing evidence."""
from __future__ import annotations

import math

from common import completion_cost_summary


def right(row: dict) -> bool | None:
    return row.get("ok") if isinstance(row.get("ok"), bool) and not row.get("error") else None


def metrics(rows: list[dict]) -> dict:
    cost = completion_cost_summary(rows, right=right)["batch_cost"]
    n_right = sum(right(r) is True for r in rows)
    walls = sorted(float(r["wall_s"]) for r in rows if isinstance(r.get("wall_s"), (float, int))
                   and not isinstance(r["wall_s"], bool) and math.isfinite(r["wall_s"]) and r["wall_s"] >= 0)
    return {**cost, "right": n_right, "unknown": sum(right(r) is None for r in rows),
            "cost_per_success": round(cost["spend_all_started"] / n_right, 6)
            if n_right and cost["spend_complete"] else None,
            "wall_median": walls[len(walls) // 2] if walls else None,
            "wall_total": round(sum(walls), 6) if walls else None,
            "wall_missing": len(rows) - len(walls)}


def summarize(rows: list[dict], arm_of, *, taskset="fresh", candidate="ccx2cand") -> dict | None:
    rows = [r for r in rows if r.get("taskset") == taskset]
    if not rows:
        return None

    def scope(rs):
        groups = {a: metrics([r for r in rs if arm_of(r) == a]) for a in sorted({arm_of(r) for r in rs})}
        pairs = {}
        # Pair only equal lead suffixes, never across different models or settings.
        for base in [a for a in groups if a == "self" or a.startswith("self@")]:
            cand = candidate + base[len("self"):]
            if cand not in groups:
                continue
            def index(arm):
                return {(r.get("tag"), r.get("round"), r.get("task")): r for r in rs if arm_of(r) == arm}
            a, b = index(base), index(cand)
            keys = sorted(a.keys() & b.keys(), key=str)
            xs, ys = [a[k] for k in keys], [b[k] for k in keys]
            valid = [k for k in keys if right(a[k]) is not None and right(b[k]) is not None]
            am, bm = metrics(xs), metrics(ys)
            def diff(key):
                return round(bm[key] - am[key], 6) if am[key] is not None and bm[key] is not None else None
            pairs[f"{base} vs {cand}"] = {
                "pairs": len(keys), "scored_pairs": len(valid), "unknown_pairs": len(keys) - len(valid),
                "unpaired": {base: len(a) - len(keys), cand: len(b) - len(keys)},
                "diff_is": f"{cand} - {base}",
                "right_diff": sum(int(right(b[k])) - int(right(a[k])) for k in valid) if valid else None,
                "cost_per_success_diff": diff("cost_per_success"),
                "wall_median_diff": diff("wall_median"), "wall_total_diff": diff("wall_total"),
            }
        return {"arms": groups, "paired": pairs}

    return {"all": scope(rows), "clean": scope([r for r in rows if r.get("env_clean") is True]),
            "note": "Descriptive engineering output; all includes failed/interrupted attempts and their spend. "
                    "Unknown scores and incomplete costs remain unknown; no Stage 3 verdict is inferred."}
