"""Offline replay of router rules and the oracle upper bound (issue #544, T3-1). Starts no agent CLI, costs $0.

Input: any rows file (JSON list, {rows: [...]} or JSONL) that holds, per task, one row for the "self" arm and one for
a delegate arm (default arms: `self` vs `ccxcheapfirst2`, the round-2 group B names). Each row needs `task`, `arm`,
`ok` (bool), `usd`, `wall_s`. Several rows of one task+arm (episodes, repeats) are averaged.

What it prints, per rule: n tasks, correct (sum of the chosen arm's ok rate), total usd, total wall seconds.
  always_self / always_delegate   the two fixed rules (the router v0 is always_self);
  threshold rules                 "delegate when FEATURE >= t" (or "<= t"), where FEATURE is a column of the
                                  self-arm row (default `context_first`); t is tuned on one half of the tasks and
                                  scored on the other (2-fold, deterministic split by task name hash), so a rule is
                                  never scored on the tasks it was tuned on;
  oracle                          per task the better arm (more correct, then cheaper, then self). It is the ceiling
                                  of any router on these rows. If the oracle barely beats always_self, this cell is
                                  not worth routing (verdict line; the 5% bar is provisional).
Rows with a known problem (invalid_reason, receipt_error, environment_error, unknown ok/usd) are dropped by default,
and a task needs a valid row on both sides; --include-invalid keeps rows whose ok and usd are known (use it to see how
a delegate arm that always failed looks, never for a result). `--label` is copied into the output, e.g. "exercise
only: stopped run".

Usage: python scripts/eval/router_replay.py ROWS.jsonl [--delegate-arm A] [--feature F] [--label TEXT] [--json]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import result_rows  # noqa: E402

SELF_ARM = "self"
MIN_TASKS = 10  # below this the verdict carries a "too few tasks" note
MIN_GAIN = 0.05  # provisional bar: oracle must beat always_self by this share of correct or cost


def _bad(row: dict) -> bool:
    return bool(row.get("invalid_reason") or row.get("receipt_error") or row.get("environment_error"))


def _usable(row: dict, include_invalid: bool) -> bool:
    if not include_invalid and _bad(row):
        return False
    return isinstance(row.get("ok"), bool) and result_rows.cost(row) is not None and result_rows.number(row.get("wall_s")) is not None


def _mean(xs):
    return sum(xs) / len(xs)


def pair_tasks(rows: list[dict], delegate_arm: str, feature: str, include_invalid: bool = False,
               self_arm: str = SELF_ARM) -> tuple[list[dict], dict]:
    """One record per task with valid rows in both arms: {task, feature, self:{ok,usd,wall}, delegate:{...}}."""
    by: dict[tuple[str, str], list[dict]] = {}
    seen = set()
    for r in rows:
        if r.get("arm") not in (self_arm, delegate_arm) or not r.get("task"):
            continue
        seen.add(r["task"])
        if _usable(r, include_invalid):
            by.setdefault((r["task"], r["arm"]), []).append(r)
    tasks, dropped = [], []
    for t in sorted(seen):
        s, d = by.get((t, self_arm)), by.get((t, delegate_arm))
        if not s or not d:
            dropped.append(t)
            continue
        def agg(rs):
            return {"ok": _mean([1.0 if x["ok"] else 0.0 for x in rs]), "usd": _mean([result_rows.cost(x) for x in rs]),
                    "wall": _mean([result_rows.number(x["wall_s"]) for x in rs])}
        f = next((result_rows.number(x.get(feature)) for x in s if result_rows.number(x.get(feature)) is not None), None)
        tasks.append({"task": t, "feature": f, "self": agg(s), "delegate": agg(d)})
    return tasks, {"tasks_seen": len(seen), "tasks_dropped": len(dropped), "dropped": dropped}


def better(rec: dict) -> str:
    """Oracle choice: more correct, then cheaper, then self."""
    s, d = rec["self"], rec["delegate"]
    if d["ok"] != s["ok"]:
        return "delegate" if d["ok"] > s["ok"] else "self"
    return "delegate" if d["usd"] < s["usd"] else "self"


def score(tasks: list[dict], choose) -> dict:
    out = {"n": len(tasks), "correct": 0.0, "usd": 0.0, "wall_s": 0.0, "delegated": 0}
    for rec in tasks:
        c = choose(rec)
        a = rec[c]
        out["correct"] += a["ok"]
        out["usd"] += a["usd"]
        out["wall_s"] += a["wall"]
        out["delegated"] += c == "delegate"
    return {k: (round(v, 6) if isinstance(v, float) else v) for k, v in out.items()}


def half_of(task: str) -> int:
    return int(hashlib.sha1(task.encode("utf-8")).hexdigest(), 16) % 2


def _objective(sc: dict) -> tuple:
    return (-sc["correct"], sc["usd"], sc["delegated"])  # smaller is better; ties lean to fewer delegations


def tune_threshold(train: list[dict], direction: str):
    """Best t for 'delegate when feature >=/<= t' on train; None when no task has the feature."""
    vals = sorted({r["feature"] for r in train if r["feature"] is not None})
    if not vals:
        return None
    cands = [-math.inf if direction == "ge" else math.inf] + vals + [math.inf if direction == "ge" else -math.inf]

    def mk(t):
        def choose(rec):
            f = rec["feature"]
            if f is None:
                return "self"  # missing input -> do it yourself
            return "delegate" if (f >= t if direction == "ge" else f <= t) else "self"
        return choose
    best = min(cands, key=lambda t: (_objective(score(train, mk(t))), abs(t) if math.isfinite(t) else math.inf))
    return best, mk(best)


def threshold_rule(tasks: list[dict], direction: str) -> dict:
    """2-fold: tune on one half, score on the other; the two scored halves add up to a score over every task once."""
    halves = [[r for r in tasks if half_of(r["task"]) == k] for k in (0, 1)]
    total = {"n": 0, "correct": 0.0, "usd": 0.0, "wall_s": 0.0, "delegated": 0}
    chosen = []
    for k in (0, 1):
        train, test = halves[1 - k], halves[k]
        tuned = tune_threshold(train, direction)
        if tuned is None or not test:
            t, choose = None, (lambda rec: "self")
        else:
            t, choose = tuned
        chosen.append(None if t is None or not math.isfinite(t) else t)
        sc = score(test, choose)
        for key in total:
            total[key] += sc[key]
    total = {k: (round(v, 6) if isinstance(v, float) else v) for k, v in total.items()}
    total["thresholds_tuned_on_other_half"] = chosen
    return total


def replay(rows: list[dict], delegate_arm: str = "ccxcheapfirst2", feature: str = "context_first",
           include_invalid: bool = False, label: str = "") -> dict:
    tasks, info = pair_tasks(rows, delegate_arm, feature, include_invalid)
    rules = {
        "always_self": score(tasks, lambda r: "self"),
        "always_delegate": score(tasks, lambda r: "delegate"),
        f"delegate_if_{feature}_ge": threshold_rule(tasks, "ge"),
        f"delegate_if_{feature}_le": threshold_rule(tasks, "le"),
        "oracle": score(tasks, better),
    }
    base, orc = rules["always_self"], rules["oracle"]
    gain_correct = (orc["correct"] - base["correct"]) / base["n"] if base["n"] else None
    gain_cost = (base["usd"] - orc["usd"]) / base["usd"] if base["usd"] else None
    if not tasks:
        verdict = "Unknown: no task has valid rows on both arms"
    elif (gain_correct or 0) < MIN_GAIN and (gain_cost or 0) < MIN_GAIN:
        verdict = (f"oracle gain over always_self is under {MIN_GAIN:.0%} in both correctness and cost: "
                   "not worth routing this cell (provisional bar)")
    else:
        verdict = "oracle headroom exists: the ceiling is above the provisional bar; it says nothing about a real rule"
    if tasks and len(tasks) < MIN_TASKS:
        verdict += f" (only {len(tasks)} tasks, under {MIN_TASKS}: too few to read; the oracle also picks run-to-run noise)"
    return {"label": label, "delegate_arm": delegate_arm, "self_arm": SELF_ARM, "feature": feature,
            "include_invalid": include_invalid, "pairing": info, "rules": rules,
            "oracle_gain": {"correct_share": gain_correct, "cost_share": gain_cost},
            "oracle_picks_delegate": sum(better(r) == "delegate" for r in tasks), "verdict": verdict}


def render(rep: dict) -> str:
    lines = []
    if rep["label"]:
        lines.append(f"[{rep['label']}]")
    p = rep["pairing"]
    lines.append(f"arms: {rep['self_arm']} vs {rep['delegate_arm']}; feature: {rep['feature']}; "
                 f"tasks paired {p['tasks_seen'] - p['tasks_dropped']}/{p['tasks_seen']}"
                 + ("; invalid rows kept" if rep["include_invalid"] else ""))
    lines.append(f"{'rule':34} {'n':>4} {'correct':>8} {'usd':>10} {'wall_s':>9} {'delegated':>9}")
    for name, s in rep["rules"].items():
        lines.append(f"{name:34} {s['n']:>4} {s['correct']:>8.2f} {s['usd']:>10.4f} {s['wall_s']:>9.1f} {s['delegated']:>9}")
    lines.append("verdict: " + rep["verdict"])
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("rows", type=Path)
    ap.add_argument("--delegate-arm", default="ccxcheapfirst2")
    ap.add_argument("--feature", default="context_first")
    ap.add_argument("--include-invalid", action="store_true")
    ap.add_argument("--label", default="")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    rep = replay(result_rows.rows(a.rows), a.delegate_arm, a.feature, a.include_invalid, a.label)
    print(json.dumps(rep, indent=2, sort_keys=True, ensure_ascii=False) if a.json else render(rep))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
