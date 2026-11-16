"""Read-only summaries of retained strength/P4 results; standard library, no model calls.

Strength/P4 valid = no error, ccx receipt status is not "error" (a run that failed
itself, e.g. kind=auth, is Unknown, not a task failure), ok is not None, and usd is
known (finite, nonnegative number, not bool). P4 rows carry no top-level status, so
the status rule leaves them unchanged. Outcomes must be bool or None. Successes count valid True
outcomes. Costs include every attempt, including failures and errors; total_usd
and usd_per_success are null if any cost is unknown. usd_per_success is also null
when there are zero successes. known_total_usd retains the known partial cost.
results.jsonl is authoritative, including interrupted runs; report.json's rows
are a fallback only when results.jsonl is absent (never combine both).

--pair A,B defines b = A right and B wrong, c = A wrong and B right. Strength's
usd_per_success_ratio is A's usd_per_success / B's usd_per_success (first arm /
second arm); it is null if either value is null or the denominator is zero,
including when B has zero successes.

--subset settled uses shared_context_ab.TASKS' existing neutral flags: the
known non-neutral tasks, excluding t7-neutral and unknown task IDs. A row
that carries its own boolean "neutral" (rows of a frozen --tasks file, issue
#345) is classified by that flag instead; --subset neutral is the complement
(neutral tasks only). A row with a boolean "invalid" (the runner's own
classification under --on-invalid continue) is valid when invalid is false,
ok is not None and usd is known. P4 ratios
are B/A of known costs and median wall times, for all and env_clean separately;
cost_unknown remains visible, so a partial cost ratio is not a complete-cost claim.
This script reports observations only, without deciding preregistered gates.

Strength pairs also report effect_rate = (b - c) / n_pairs (null when n_pairs is 0).

p4 --paired (round-2 pre-registration, section 4) adds a task-level "paired" block
to each subset. Rows pair by (round, episode, task); only pairs valid on both sides
count, where --paired also treats p4's round-2 invalid rows as invalid (invalid_reason,
receipt_error or environment_error set; pre-registration section 0). b = A right and B wrong, c = A wrong and B right; difference =
(c - b) / n = p(B right) - p(A right).
- tango_lower_95: one-sided 95% lower bound of that difference, i.e. the lower end
  of Tango's (1998, Stat Med 17:891) asymptotic score interval at z = z(0.95), in
  the form given by Fagerland, Lydersen & Laake (2014, Stat Med 33:2850): with
  n12 = c, n21 = b, Z(d) = (n12 - n21 - n d) / sqrt(n (2 q + d (1 - d))), q the
  restricted MLE of p21 = (sqrt(B^2 - 4AC) - B) / (2A), A = 2n,
  B = -n12 - n21 + (2n - n12 + n21) d, C = -n21 d (1 - d); the bound is the d
  where Z(d) = z (Z decreases in d), -1 when every pair is b.
- cost / claude_cost: per pair r = ln(B usd / A usd); gmr = exp(mean r);
  gmr_upper_95 = exp(mean + t(0.95, n-1) sd / sqrt(n)) (one-sided, paired t on log
  ratios), gmr_ci95 = two-sided 95% (unadjusted, descriptive). Null when n = 0, any
  cost in the pairs is unknown, or any is zero (log undefined; zero_cost_pairs
  counts them); the bounds also need n >= 2. total_ratio = sum B / sum A (point
  rule).
- Claude's own spend per row = p5_costs.costs(row)["claude_side_usd"]: the lead plus
  every ledger entry on the Claude side (Claude sub-agents, Claude reviewers); null
  when that row's side_cost_status is not Pass.
- wall: median_ratio = median B wall / median A wall (round 1's rule);
  per_task_ratio_median = median of per-pair B/A wall ratios.
- cap_hits per arm: rows with cap_hit true or a Claude subtype error_max_budget*;
  vendor_usd per arm: p5_costs.aggregate over all the arm's rows (descriptive).
- first_rung per arm: every delegation's first rung (model:effort; the row's
  first_rungs from p4, else the ledger), counted; mismatches = units where any of
  them differs from --expected-first-rung (or the rows' default_first_rung) or p4's
  first_rung_matches_default is false; units without one count as no_dispatch.
- strata by row "source" and "repo"; all_rows (secondary): every complete pair, an
  invalid row counted as wrong; a known cost as recorded, an unknown one at
  max(known_usd, reserved_usd or --reserve-usd).
`holm P1 P2 ...` is Holm's (1979, Scand J Stat 6:65) step-down adjustment:
sorted p(1..m), adjusted p(i) = max over j <= i of min(1, (m - j + 1) p(j)).
"unknown" or "null" counts as p = 1 (round-2 pre-registration: an Unknown group).

Examples:
  python scripts/eval/unified_summary.py strength OUT --pair on,off --subset settled
  python scripts/eval/unified_summary.py p4 --tag RUN --out DIR --pair self,ccxlong --text
  python scripts/eval/unified_summary.py p4 --tag RUN --out DIR --pair self,v2 --paired --reserve-usd 1.5
  python scripts/eval/unified_summary.py holm 0.003 unknown
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import statistics
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import p4_long_session as P4
import p5_costs
from p5_costs import money
from seven_ab import mcnemar_p
from shared_context_ab import TASKS

VALID_DEFINITION = ("no error, ccx receipt status is not \"error\", ok is not None, "
                    "usd is known (finite nonnegative number, not bool)")
SETTLED_TASKS = {task["id"] for task in TASKS if not task["neutral"]}
NEUTRAL_TASKS = {task["id"] for task in TASKS if task["neutral"]}


def in_subset(row: dict, subset: str) -> bool:
    """A row's own boolean "neutral" (a frozen task file's flag, #345) wins; else the built-in TASKS flags."""
    if type(row.get("neutral")) is bool:
        return row["neutral"] is (subset == "neutral")
    return row.get("task") in (NEUTRAL_TASKS if subset == "neutral" else SETTLED_TASKS)


def read_rows(path: Path) -> list[dict]:
    """Strict JSONL: never silently drop a malformed or interrupted record."""
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").split("\n") if line.strip()]
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError("result rows must be JSON objects")
    return rows


def strength_rows(out: Path) -> list[dict]:
    if (out / "results.jsonl").is_file():
        return read_rows(out / "results.jsonl")
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    rows = report["rows"]
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("report rows must be a list of JSON objects")
    return rows


def valid(row: dict) -> bool:
    if type(row.get("invalid")) is bool:
        # A row the runner classified itself (--on-invalid continue, #345): a sub-agent's own timeout/cap with a
        # known cost is valid with ok false although its receipt status is "error"
        return not row["invalid"] and row.get("ok") is not None and money(row.get("usd")) is not None
    return (not row.get("error") and row.get("status") != "error" and row.get("ok") is not None
            and money(row.get("usd")) is not None)


def check_outcomes(rows: list[dict], scope: str) -> None:
    for index, row in enumerate(rows, 1):
        if row.get("ok") is not None and type(row["ok"]) is not bool:
            raise ValueError(f"{scope} ok must be bool or null: row {index}, "
                             f"arm={row.get('arm')!r}, task={row.get('task')!r}, rep={row.get('rep')!r}")


def strength(rows: list[dict], pair: tuple[str, str] | None = None, subset: str | None = None) -> dict:
    if subset not in (None, "settled", "neutral"):
        raise ValueError("unknown strength subset")
    check_outcomes(rows, "strength")
    selected = [row for row in rows if subset is None or in_subset(row, subset)]
    arms = {}
    for arm in sorted({row["arm"] for row in selected} | set(pair or ())):
        group = [row for row in selected if row["arm"] == arm]
        successes = sum(valid(row) and row["ok"] is True for row in group)
        unknown = sum(money(row.get("usd")) is None for row in group)
        known = round(sum(money(row.get("usd")) or 0 for row in group), 8)
        total = None if unknown else known
        arms[arm] = {"attempted": len(group), "valid": sum(map(valid, group)), "successes": successes,
                     "total_usd": total, "known_total_usd": known, "cost_unknown": unknown,
                     "usd_per_success": total / successes if successes and total is not None else None}
    result = {"command": "strength", "subset": subset or "all", "valid_definition": VALID_DEFINITION,
              "successes_definition": "valid rows with ok true",
              "cost_definition": "all attempts; total_usd is null when any cost is unknown",
              "arms": arms}
    if pair:
        pair_rows = [row for row in selected if row["arm"] in pair]
        with_agent = any("agent" in row for row in pair_rows)
        keys = ("task", "agent", "rep") if with_agent else ("task", "rep")
        paired = {}
        for row in pair_rows:
            if any(row.get(key) is None for key in keys):
                raise ValueError("missing pairing key: " + ", ".join(keys))
            entry = paired.setdefault(tuple(row[key] for key in keys), {})
            if row["arm"] in entry:
                raise ValueError("duplicate strength arm/pair key")
            entry[row["arm"]] = row
        a, b_arm = pair
        pairs = [entry for entry in paired.values() if a in entry and b_arm in entry
                 and valid(entry[a]) and valid(entry[b_arm])]
        b = sum(entry[a]["ok"] and not entry[b_arm]["ok"] for entry in pairs)
        c = sum(not entry[a]["ok"] and entry[b_arm]["ok"] for entry in pairs)
        a_cost, b_cost = (arms[arm]["usd_per_success"] for arm in pair)
        result["pair"] = {"a": a, "b_arm": b_arm, "keys": list(keys), "n_pairs": len(pairs),
                          "b": b, "c": c, "mcnemar_p": mcnemar_p(b, c),
                          "usd_per_success_ratio": a_cost / b_cost if a_cost is not None and b_cost else None,
                          "effect_rate": (b - c) / len(pairs) if pairs else None}
    return result


# ---- statistics (standard library only) ----

Z95 = statistics.NormalDist().inv_cdf(0.95)


def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction of the regularized incomplete beta (modified Lentz; Numerical Recipes 6.4)."""
    tiny, qab, qap, qam = 1e-300, a + b, a + 1, a - 1
    c, d = 1.0, 1 - qab * x / qap
    d = 1 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 1000):
        m2 = 2 * m
        for aa in (m * (b - m) * x / ((qam + m2) * (a + m2)), -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))):
            d = 1 + aa * d
            d = 1 / (d if abs(d) > tiny else tiny)
            c = 1 + aa / c
            c = c if abs(c) > tiny else tiny
            h *= d * c
        if abs(d * c - 1) < 1e-15:
            break
    return h


def _betainc(a: float, b: float, x: float) -> float:
    if x <= 0 or x >= 1:
        return 0.0 if x <= 0 else 1.0
    front = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x))
    if x < (a + 1) / (a + b + 2):
        return front * _betacf(a, b, x) / a
    return 1 - front * _betacf(b, a, 1 - x) / b


def t_cdf(t: float, df: int) -> float:
    tail = 0.5 * _betainc(df / 2, 0.5, df / (df + t * t))
    return 1 - tail if t >= 0 else tail


def t_quantile(p: float, df: int) -> float:
    """Student t quantile for 0.5 < p < 1 by bisection on t_cdf."""
    lo, hi = 0.0, 1e7
    for _ in range(200):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if t_cdf(mid, df) < p else (lo, mid)
    return (lo + hi) / 2


def tango_z(n12: int, n21: int, n: int, d: float) -> float:
    """Tango's score statistic for H0: p12 - p21 = d (Fagerland et al. 2014's notation)."""
    a = 2 * n
    b = -n12 - n21 + (2 * n - n12 + n21) * d
    c = -n21 * d * (1 - d)
    q = (math.sqrt(max(b * b - 4 * a * c, 0.0)) - b) / (2 * a)
    var = n * (2 * q + d * (1 - d))
    num = n12 - n21 - n * d
    if var <= 0:
        return math.inf if num > 0 else -math.inf if num < 0 else 0.0
    return num / math.sqrt(var)


def tango_lower(b: int, c: int, n: int, z: float = Z95) -> float | None:
    """One-sided lower bound of p(B right) - p(A right); b = only A right, c = only B right."""
    if n <= 0:
        return None
    if b == n:
        return -1.0
    lo, hi = -1.0, (c - b) / n   # Z(hi) = 0 < z; Z decreases in d
    for _ in range(200):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if tango_z(c, b, n, mid) > z else (lo, mid)
    return (lo + hi) / 2


def holm(pvalues: list) -> list[float]:
    """Holm (1979) step-down adjusted p-values, in input order; None counts as 1."""
    ps = [1.0 if p is None else float(p) for p in pvalues]
    if any(not 0 <= p <= 1 for p in ps):
        raise ValueError("p-values must be in [0, 1]")
    order = sorted(range(len(ps)), key=lambda i: ps[i])
    adjusted, running = [0.0] * len(ps), 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (len(ps) - rank) * ps[i]))
        adjusted[i] = running
    return adjusted


def gmr(pairs: list[tuple]) -> dict:
    """Geometric-mean ratio B/A over (a, b) amounts with a paired t on log ratios."""
    out = {"n": len(pairs), "unknown_pairs": sum(a is None or b is None for a, b in pairs),
           "zero_cost_pairs": sum(a == 0 or b == 0 for a, b in pairs if a is not None and b is not None),
           "total_a": None, "total_b": None, "total_ratio": None,
           "gmr": None, "gmr_upper_95": None, "gmr_ci95": None}
    known = [(a, b) for a, b in pairs if a is not None and b is not None]
    out["known_total_a"] = round(sum(a for a, _ in known), 8)
    out["known_total_b"] = round(sum(b for _, b in known), 8)
    if out["unknown_pairs"] or not pairs:
        return out
    out["total_a"], out["total_b"] = out["known_total_a"], out["known_total_b"]
    out["total_ratio"] = out["total_b"] / out["total_a"] if out["total_a"] else None
    if out["zero_cost_pairs"]:
        return out
    logs = [math.log(b / a) for a, b in pairs]
    mean = statistics.fmean(logs)
    out["gmr"] = math.exp(mean)
    if len(logs) >= 2:
        se = statistics.stdev(logs) / math.sqrt(len(logs))
        out["gmr_upper_95"] = math.exp(mean + t_quantile(0.95, len(logs) - 1) * se)
        half = t_quantile(0.975, len(logs) - 1) * se
        out["gmr_ci95"] = [math.exp(mean - half), math.exp(mean + half)]
    return out


def claude_usd(row: dict):
    side = p5_costs.costs(row)
    return side["claude_side_usd"] if side["side_cost_status"] == "Pass" else None


def cap_hit(row: dict) -> bool:
    return row.get("cap_hit") is True or str(row.get("subtype") or "").startswith("error_max_budget")


def _model_effort(rung) -> str:
    return ":".join(str(rung).split(":")[-2:])


def first_rungs(row: dict) -> list[str]:
    """model:effort of every delegation's first rung in a unit. Prefers the row's first_rungs (p4, #346:
    dispatch.first_rung of each cheap-first ledger entry); older rows fall back to the ledger: cheap-first
    entries if any, else every non-review entry, each by dispatch.first_rung or its first attempted rung."""
    if isinstance(row.get("first_rungs"), list):
        return [_model_effort(r) for r in row["first_rungs"] if r]
    entries = [e for e in row.get("side_ledger") or []
               if not e.get("type") and not str(e.get("label") or "").startswith("review:")]
    entries = [e for e in entries if (e.get("dispatch") or {}).get("cheap_first")] or entries
    out = []
    for entry in entries:
        rung = (entry.get("dispatch") or {}).get("first_rung") or next((r for r in entry.get("rungs") or [] if r), None)
        if rung:
            out.append(_model_effort(rung))
    return out


def pair_valid(row: dict) -> bool:
    """valid() plus the round-2 invalid rows p4 records (#346): invalid_reason, receipt_error, environment_error
    (pre-registration section 0). Used only by --paired, so the default arms.valid counts are unchanged."""
    return (valid(row) and not row.get("invalid_reason") and row.get("receipt_error") is not True
            and row.get("environment_error") is not True)


def pair_rows(rows: list[dict], pair: tuple[str, str]) -> dict:
    keys = ("round", "episode", "task")
    paired = {}
    for row in rows:
        if any(row.get(key) is None for key in keys):
            raise ValueError("missing P4 pairing key: " + ", ".join(keys))
        entry = paired.setdefault(tuple(row[key] for key in keys), {})
        if row["arm"] in entry:
            raise ValueError(f"duplicate P4 arm/pair key: {row['arm']!r} {tuple(row[key] for key in keys)!r}")
        entry[row["arm"]] = row
    return paired


def paired_core(entries: list[dict], pair: tuple[str, str]) -> dict:
    a, b_arm = pair
    complete = [e for e in entries if a in e and b_arm in e]
    pairs = [e for e in complete if pair_valid(e[a]) and pair_valid(e[b_arm])]
    n = len(pairs)
    b = sum(e[a]["ok"] and not e[b_arm]["ok"] for e in pairs)
    c = sum(not e[a]["ok"] and e[b_arm]["ok"] for e in pairs)
    walls = [(e[a].get("wall_s"), e[b_arm].get("wall_s")) for e in pairs]
    known_walls = [(x, y) for x, y in walls if x is not None and y is not None]
    med_a = statistics.median([x for x, _ in known_walls]) if known_walls else None
    med_b = statistics.median([y for _, y in known_walls]) if known_walls else None
    per_task = [y / x for x, y in known_walls if x]
    return {"n_tasks": len(entries), "n_complete": len(complete), "n_valid_pairs": n,
            "correctness": {"a_right": sum(e[a]["ok"] is True for e in pairs),
                            "b_right": sum(e[b_arm]["ok"] is True for e in pairs),
                            "b": b, "c": c, "difference": (c - b) / n if n else None,
                            "tango_lower_95": tango_lower(b, c, n)},
            "cost": gmr([(money(e[a]["usd"]), money(e[b_arm]["usd"])) for e in pairs]),
            "claude_cost": gmr([(claude_usd(e[a]), claude_usd(e[b_arm])) for e in pairs]),
            "wall": {"n": len(known_walls), "median_a": med_a, "median_b": med_b,
                     "median_ratio": med_b / med_a if med_a else None,
                     "per_task_ratio_median": statistics.median(per_task) if per_task else None}}


def all_rows_core(entries: list[dict], pair: tuple[str, str], reserve_usd: float | None) -> dict:
    """Secondary: every complete pair; an invalid row counts as wrong. Costs: a known cost as recorded, an
    unknown one at max(known_usd, reserved_usd or --reserve-usd), as p4's budget charges it (pre-registration
    section 4 and #347: "unknown-cost units charged at their reservation")."""
    a, b_arm = pair
    complete = [e for e in entries if a in e and b_arm in e]

    def outcome(row):
        return row["ok"] is True if pair_valid(row) else False

    def cost(row):
        known = money(row.get("usd"))
        if known is not None:
            return known
        reserved = money(row.get("reserved_usd"))
        reserved = reserved if reserved is not None else reserve_usd
        return None if reserved is None else max(reserved, money(row.get("known_usd")) or 0)

    n = len(complete)
    b = sum(outcome(e[a]) and not outcome(e[b_arm]) for e in complete)
    c = sum(not outcome(e[a]) and outcome(e[b_arm]) for e in complete)
    return {"n_pairs": n, "invalid_rows": sum(not pair_valid(e[arm]) for e in complete for arm in pair),
            "reserve_usd": reserve_usd,
            "correctness": {"b": b, "c": c, "difference": (c - b) / n if n else None,
                            "tango_lower_95": tango_lower(b, c, n)},
            "cost": gmr([(cost(e[a]), cost(e[b_arm])) for e in complete])}


def paired_block(subset: list[dict], pair: tuple[str, str], reserve_usd: float | None = None,
                 expected_first_rung: str | None = None) -> dict:
    entries = list(pair_rows(subset, pair).values())
    result = {"keys": ["round", "episode", "task"], **paired_core(entries, pair)}
    arms = {}
    for arm in pair:
        group = [row for row in subset if row["arm"] == arm]
        expected = expected_first_rung or next((row["default_first_rung"] for row in group
                                                if row.get("default_first_rung")), None)
        expected = _model_effort(expected) if expected else None
        observed, no_dispatch, mismatched = {}, 0, 0
        for row in group:
            rungs = first_rungs(row)
            no_dispatch += not rungs
            for rung in rungs:
                observed[rung] = observed.get(rung, 0) + 1
            # a unit mismatches when any of its delegations started elsewhere (p4's own flag counts too)
            mismatched += (row.get("first_rung_matches_default") is False
                           or bool(expected) and any(rung != expected for rung in rungs))
        flagged = any("first_rung_matches_default" in row for row in group)
        arms[arm] = {"cap_hits": sum(map(cap_hit, group)),
                     "vendor_usd": p5_costs.aggregate(group),
                     "first_rung": {"observed": observed, "no_dispatch": no_dispatch, "expected": expected,
                                    "mismatches": mismatched if expected or flagged else None}}
    result["arms"] = arms
    for field in ("source", "repo"):
        groups = {}
        for entry in entries:
            value = next((str(row.get(field)) for row in entry.values() if row.get(field) is not None), "unknown")
            groups.setdefault(value, []).append(entry)
        result["by_" + field] = {value: paired_core(group, pair) for value, group in sorted(groups.items())}
    result["all_rows"] = all_rows_core(entries, pair, reserve_usd)
    return result


def p4(rows: list[dict], tag: str, pair: tuple[str, str], paired: bool = False,
       reserve_usd: float | None = None, expected_first_rung: str | None = None) -> dict:
    selected = [row for row in rows if row.get("tag") == tag and row.get("arm") in pair]
    if not selected:
        raise ValueError(f"no P4 rows selected for tag={tag!r} and pair={pair!r}; check --tag and --out")
    for arm in pair:
        if not any(row.get("arm") == arm for row in selected):
            raise ValueError(f"no P4 rows for arm={arm!r}, tag={tag!r}; check --pair, --tag and --out")
    check_outcomes(selected, "p4")
    result = {"command": "p4", "tag": tag, "pair": list(pair), "ratio_direction": "B/A",
              "valid_definition": VALID_DEFINITION,
              "cost_definition": "known cost only; see cost_unknown before interpreting ratios"}
    for name, subset in (("all", selected), ("env_clean", [r for r in selected if r.get("env_clean") is True])):
        arms = {}
        for arm in pair:
            group = [row for row in subset if row["arm"] == arm]
            stats = P4.arm_summary(group)
            arms[arm] = {key: stats[key] for key in
                         ("attempted", "right", "cost_known_usd", "cost_unknown", "wall_median_s")}
            arms[arm]["env_clean"] = sum(row.get("env_clean") is True for row in group)
            arms[arm]["valid"] = sum(map(valid, group))
            if arm == P4.DE.ARM:
                arms[arm]["dispatch"] = {**P4.DE.metrics(group), "stop_reason": P4.DE.stop_reason(group)}
        a, b = (arms[arm] for arm in pair)
        result[name] = {"arms": arms, "ratios": {
            "cost": P4._ratio(b["cost_known_usd"], a["cost_known_usd"]),
            "wall_median": P4._ratio(b["wall_median_s"], a["wall_median_s"])}}
        if paired:
            result[name]["paired"] = paired_block(subset, pair, reserve_usd, expected_first_rung)
    return result


def table(headers: list[str], rows: list[list]) -> str:
    cells = [headers, *[["null" if value is None else str(value) for value in row] for row in rows]]
    widths = [max(len(row[i]) for row in cells) for i in range(len(headers))]
    return "\n".join("  ".join(value.ljust(width) for value, width in zip(row, widths)) for row in cells)


def text_report(result: dict) -> str:
    if result["command"] == "strength":
        fields = ["attempted", "valid", "successes", "total_usd", "known_total_usd", "cost_unknown", "usd_per_success"]
        lines = ["valid = " + result["valid_definition"], "successes = " + result["successes_definition"],
                 result["cost_definition"], "subset = " + result["subset"],
                 table(["arm", *fields], [[arm, *[stats[key] for key in fields]] for arm, stats in result["arms"].items()])]
        if "pair" in result:
            pair = result["pair"]
            fields = ["a", "b_arm", "n_pairs", "b", "c", "mcnemar_p", "usd_per_success_ratio"]
            lines.append(table(fields, [[pair[key] for key in fields]]))
            lines.append("pair keys = " + ", ".join(pair["keys"]))
            lines.append("b = first arm right, second arm wrong; usd_per_success_ratio = first arm / second arm")
        return "\n".join(lines)
    if result["command"] == "holm":
        return table(["p", "holm_adjusted"], [[p, q] for p, q in zip(result["p"], result["adjusted"])])
    lines = ["tag = " + result["tag"], "ratios = B/A", "valid = " + result["valid_definition"],
             result["cost_definition"]]
    for subset in ("all", "env_clean"):
        lines.append(subset)
        fields = ["attempted", "valid", "env_clean", "right", "cost_known_usd", "cost_unknown", "wall_median_s"]
        lines.append(table(["arm", *fields], [[arm, *[stats[key] for key in fields]]
                                           for arm, stats in result[subset]["arms"].items()]))
        ratios = result[subset]["ratios"]
        lines.append(table(["B/A", "cost", "wall_median"], [["ratio", ratios["cost"]["ratio"], ratios["wall_median"]["ratio"]]]))
        for arm, stats in result[subset]["arms"].items():
            if "dispatch" in stats:
                dispatch = stats["dispatch"]
                lines.append(arm + " dispatch")
                lines.append(table(list(dispatch), [list(dispatch.values())]))
        if "paired" in result[subset]:
            lines.extend(paired_text(result[subset]["paired"]))
    return "\n".join(lines)


def paired_text(block: dict) -> list[str]:
    corr, wall = block["correctness"], block["wall"]
    lines = [f"paired by task (round, episode, task): {block['n_valid_pairs']} valid of {block['n_tasks']} tasks",
             table(["a_right", "b_right", "b", "c", "difference", "tango_lower_95"],
                   [[corr[k] for k in ("a_right", "b_right", "b", "c", "difference", "tango_lower_95")]])]
    fields = ["n", "total_ratio", "gmr", "gmr_upper_95", "unknown_pairs", "zero_cost_pairs"]
    lines.append(table(["B/A", *fields], [[name, *[block[name][k] for k in fields]] for name in ("cost", "claude_cost")]))
    lines.append(table(["wall", "median_ratio", "per_task_ratio_median"],
                       [["B/A", wall["median_ratio"], wall["per_task_ratio_median"]]]))
    lines.append(table(["arm", "cap_hits", "first_rung", "no_dispatch", "expected", "mismatches"],
                       [[arm, s["cap_hits"], json.dumps(s["first_rung"]["observed"], sort_keys=True),
                         s["first_rung"]["no_dispatch"], s["first_rung"]["expected"], s["first_rung"]["mismatches"]]
                        for arm, s in block["arms"].items()]))
    return lines


def parse_pair(value: str) -> tuple[str, str]:
    arms = tuple(arm.strip() for arm in value.split(","))
    if len(arms) != 2 or not all(arms) or arms[0] == arms[1]:
        raise argparse.ArgumentTypeError("pair must be two distinct nonempty arms: A,B")
    return arms


def parse_p(value: str):
    if value.strip().lower() in ("unknown", "null", "none"):
        return None
    try:
        p = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError("p-value must be a number in [0, 1] or 'unknown'") from None
    if not 0 <= p <= 1:
        raise argparse.ArgumentTypeError("p-value must be a number in [0, 1] or 'unknown'")
    return p


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--text", action="store_true", help="print a human-readable table instead of JSON")
    sub = parser.add_subparsers(dest="command", required=True)
    s = sub.add_parser("strength")
    s.add_argument("out_dir", type=Path)
    s.add_argument("--pair", type=parse_pair)
    s.add_argument("--subset", choices=("settled", "neutral"))
    p = sub.add_parser("p4")
    p.add_argument("--tag", required=True)
    p.add_argument("--out", type=Path, default=P4.parser().get_default("out"), help="results directory or JSONL file; default: P4 results.jsonl")
    p.add_argument("--pair", required=True, type=parse_pair)
    p.add_argument("--paired", action="store_true", help="add task-level paired statistics (round-2 pre-registration)")
    p.add_argument("--reserve-usd", type=float, help="with --paired: reservation charged to an unknown-cost row "
                   "without reserved_usd in the all_rows secondary analysis")
    p.add_argument("--expected-first-rung", help="with --paired: the dry-run's default_first_rung (model:effort)")
    h = sub.add_parser("holm", help="Holm-adjust p-values; 'unknown' or 'null' counts as 1")
    h.add_argument("pvalues", nargs="+", type=parse_p)
    for command in (s, p, h):
        command.add_argument("--text", action="store_true", default=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        if args.command == "strength":
            result = strength(strength_rows(args.out_dir), args.pair, args.subset)
        elif args.command == "holm":
            result = {"command": "holm", "unknown_as": 1, "p": args.pvalues, "adjusted": holm(args.pvalues)}
        else:
            if (args.reserve_usd is not None or args.expected_first_rung) and not args.paired:
                raise ValueError("--reserve-usd and --expected-first-rung need --paired")
            if args.reserve_usd is not None and money(args.reserve_usd) is None:
                raise ValueError("--reserve-usd must be a finite nonnegative number")
            path = args.out / "results.jsonl" if args.out.is_dir() else args.out
            result = p4(read_rows(path), args.tag, args.pair, args.paired, args.reserve_usd, args.expected_first_rung)
        output = text_report(result) if args.text else json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
