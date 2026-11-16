"""Offline plan and stopping/accounting rules for the six reused dispatch tasks."""
import statistics

ARM = "ccxcheapfirst"
# Round 2 (#346): cheap first plus check.sensitivity = "escalate"; the lead writes a failing check first.
ARM2 = "ccxcheapfirst2"
ARMS = (ARM, ARM2)
SETTINGS = {ARM: "[dispatch]\ncheap_first = true\n",
            ARM2: '[dispatch]\ncheap_first = true\n\n[check]\nsensitivity = "escalate"\n'}


def schedule(tasks, rounds, arms):
    return [{"round": rd, "episode": i + 1, "turn": 1, "task": task["id"], "arm": arm}
            for rd in range(1, rounds + 1) for i, task in enumerate(tasks)
            for arm in (arms if i % 2 else arms[::-1])]


def metrics(rows, arm=ARM):
    selected = [r for r in rows if r.get("arm") == arm]
    records = [entry["dispatch"] for r in selected for entry in r.get("side_ledger", [])
               if entry.get("dispatch", {}).get("cheap_first")]
    attempted = sum(d.get("attempted", 0) for d in records)
    escalated = sum(d.get("escalated", 0) for d in records)
    complete = bool(records) and all(r.get("dispatch_observed") is True for r in selected)
    def cost(key):
        return round(sum(d[key] for d in records), 6) if records and all(d.get(key) is not None for d in records) else None
    return {"attempted": attempted, "escalated": escalated,
            "escalation_rate": escalated / attempted if attempted else None,
            "first_usd": cost("first_usd"), "escalation_usd": cost("escalation_usd"),
            "status": "Pass" if complete and attempted else "Unknown"}


def stop_reason(rows, arm=ARM, max_rate=.3, evidence=True):
    """max_rate None: no escalation stop (escalate retries more by design). evidence=False: missing dispatch
    evidence or dispatch cost is an invalid row the caller counts, not an immediate stop."""
    result = metrics(rows, arm)
    if max_rate is not None and result["escalation_rate"] is not None and result["escalation_rate"] > max_rate:
        return "escalation_rate_above_30_percent" if max_rate == .3 else "escalation_rate_above_limit"
    if not evidence:
        return None
    if any(r.get("arm") == arm and r.get("dispatch_observed") is not True for r in rows):
        return "dispatch_evidence_unknown"
    if any(r.get("arm") == arm for r in rows) and (result["first_usd"] is None or result["escalation_usd"] is None):
        return "dispatch_cost_unknown"
    return None


def configure(hub, active, arm=ARM):
    # Each arm has its own fresh hub; only the experimental arm changes these keys.
    if active:
        (hub / "ccx" / "settings.toml").write_text(SETTINGS[arm], encoding="utf-8", newline="")


def comparison(rows, expected, arm=ARM, max_rate=.3):
    """arm=ARM keeps the round-1 rules (six tasks); ARM2 takes any expected count and its own escalation limit."""
    candidate = arm
    result = {"metrics": metrics(rows, candidate), "evidence": "not run" if not rows else rows[0].get("evidence", "not run")}
    for name, subset in (("all", rows), ("env_clean", [r for r in rows if r.get("env_clean") is True])):
        groups = {arm: [r for r in subset if r.get("arm") == arm] for arm in ("self", candidate)}
        stats = {}
        for arm, group in groups.items():
            wall = [r["wall_s"] for r in group if r.get("wall_s") is not None]
            stats[arm] = {"attempted": len(group), "right": sum(r.get("ok") is True for r in group),
                          "known_usd": round(sum(r.get("usd") if r.get("usd") is not None else r.get("known_usd", 0) for r in group), 6),
                          "cost_unknown": sum(not r.get("cost_complete") for r in group),
                          "wall_total_s": sum(wall), "wall_median_s": statistics.median(wall) if wall else None}
        keys = [{(r.get("round"), r.get("episode"), r.get("task")) for r in groups[a]} for a in groups]
        s, c = stats["self"], stats[candidate]
        complete = ((expected == 6 or candidate != ARM) and keys[0] == keys[1] and len(keys[0]) == expected
                    and all(v["attempted"] == expected and not v["cost_unknown"] and v["wall_median_s"] is not None for v in stats.values())
                    and all(type(r.get("ok")) is bool and not r.get("environment_error") for r in subset)
                    and metrics(subset, candidate)["status"] == "Pass"
                    and stop_reason(subset, candidate, max_rate) is None)
        passed = (c["right"] >= s["right"] and c["known_usd"] <= .8 * s["known_usd"]
                  and c["wall_median_s"] is not None and s["wall_median_s"] is not None
                  and c["wall_median_s"] <= 2 * s["wall_median_s"])
        result[name] = {"arms": stats, "expected_per_arm": expected,
                        "verdict": ("Pass" if passed else "Fail") if complete else "Unknown"}
    return result
