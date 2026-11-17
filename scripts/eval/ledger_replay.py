"""Offline ledger replay (issue #380): how each first rung did per task category, and what a candidate rule would
have done on that history. Read-only, standard library; no model CLI, no network. Changes no default.

Inputs (explicit files only; a path under `eval-codex-home` is refused):
  --ledger FILE   ccx ledger.jsonl (repeatable);  --hub DIR = DIR/ccx/ledger.jsonl + DIR/ccx/runs
  --runs DIR      DIR/<run id>/run.json: adds what the slim ledger row does not keep (route.p, route.chain_p,
                  route.rung, first_rung). A key the ledger row has is never overwritten.
  --results FILE  scored result rows (JSON/JSONL, repeatable), joined to ledger rows by `label`; a row's boolean
                  `ok` (hidden tests) is the strongest outcome.

Per run:
- first rung: actual_first_rung (#379), else first_rung (run.json), else dispatch.first_rung (cheap-first), else
  rungs[0] (the first attempt actually made). The source counts are in input.first_rung_source.
- category (--by auto): category, task_type, task, `role:<role>`, `mode:<mode>`, else unknown.
- outcome: a result row's `ok`, else the last non-probable `verify` event of the run. The ledger row's own `ok` only
  says the run finished, never that the work was right. A probable (soft) verdict counts only with
  --include-probable. Runs without an outcome are in n, not in n_judged.
- ok_final: judged right in the end. ok_first: right and attempts <= 1 (an escalated or retried run missed on its
  first rung; a lower bound, because attempts also counts same-rung retries and vendor fallbacks).
- cost: the ledger row's ae_usd (API-equivalent, all attempts, so escalation spend is in the first rung's cost).

Calibration: p (and chain_p) of the routing pick vs the observed rate. p is the pick's own success chance, so it is
compared with ok_first, and chain_p (with escalation) with ok_final. It is used only when the pick's rung
(planned_first_rung, else route.rung) is the rung the run started on; p of another rung is not evidence for
this one (p_other_rung / p_rung_unknown count the rows left out). gap = mean_p - actual (positive = over-confident),
brier = mean (p - outcome)^2.

--rule (JSON file or literal {...}): {"name": "...", "default": RUNG, "by_category": {CATEGORY: RUNG}}. Per category,
the estimate is that (category, rung) cell's observed ok_final rate and mean cost when the cell has at least
--min-n judged runs; otherwise the category is `unsupported` and stays out of the totals (coverage says how much of
the history that leaves). It is not a forecast: history was not randomized (routing chose each rung for the task it
saw), so a cell's rate describes the tasks it got, not the tasks the rule would send there.

Examples:
  python scripts/eval/ledger_replay.py --hub ~/.ccx-hub --text
  python scripts/eval/ledger_replay.py --ledger ledger.jsonl --runs hub/ccx/runs --results results.jsonl --only eval
  python scripts/eval/ledger_replay.py --ledger ledger.jsonl --rule '{"default": "codex:gpt-6.1-sol:low"}' --text
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from ccx import ledger as _ledger

FORBIDDEN = "eval-codex-home"
MIN_N = 10
Z95 = 1.959964


def wilson(k: int, n: int, z: float = Z95):
    """Two-sided 95% Wilson score interval of k/n; None when n = 0."""
    if n <= 0:
        return None
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, centre - half), min(1.0, centre + half)


def rate(k: int, n: int) -> dict:
    ci = wilson(k, n)
    return {"k": k, "n": n, "rate": k / n if n else None,
            "ci95": None if ci is None else [round(ci[0], 4), round(ci[1], 4)]}


def _check_path(path) -> Path:
    path = Path(path)
    if FORBIDDEN in (part.lower() for part in path.parts):
        raise SystemExit(f"refusing to read {path}: paths under {FORBIDDEN} are not inputs of this script")
    return path


def _jsonl(path: Path) -> list:
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except ValueError:
                pass                                   # an interrupted last line
    return out


def load_ledger(path) -> list[dict]:
    """Ledger rows in file order, probable-verdict and dismissal bookkeeping left to replay()."""
    return [r for r in _jsonl(_check_path(path)) if isinstance(r, dict)]


def load_runs(runs_dir) -> dict[str, dict]:
    """run id -> run.json (unreadable files skipped)."""
    out = {}
    for f in sorted(_check_path(runs_dir).glob("*/run.json")):
        try:
            rec = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(rec, dict):
            out[rec.get("run_id") or f.parent.name] = rec
    return out


def index_results(rows: list[dict]) -> dict[str, dict]:
    """label -> scored row (the last one when a label was scored twice)."""
    return {r["label"]: r for r in rows if isinstance(r, dict) and r.get("label")}


def load_results(path) -> list[dict]:
    path = _check_path(path)
    text = path.read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except ValueError:
        data = _jsonl(path)
    if isinstance(data, dict):
        data = data.get("rows", data.get("results", [data]))
    return [r for r in data if isinstance(r, dict)] if isinstance(data, list) else []


def first_rung(row: dict) -> tuple[str | None, str | None]:
    for key, value in (("actual_first_rung", row.get("actual_first_rung")), ("first_rung", row.get("first_rung")),
                       ("dispatch.first_rung", (row.get("dispatch") or {}).get("first_rung"))):
        if value:
            return value, key
    rungs = row.get("rungs") or []
    return (rungs[0], "rungs[0]") if rungs and rungs[0] else (None, None)


def category(row: dict, by: str = "auto") -> str:
    fields = {"category": row.get("category"), "task_type": row.get("task_type"), "task": row.get("task"),
              "role": row.get("role") and f"role:{row['role']}", "mode": row.get("mode") and f"mode:{row['mode']}"}
    if by == "auto":
        return next((str(fields[k]) for k in ("category", "task_type", "task", "role", "mode") if fields[k]), "unknown")
    return str(fields[by]) if fields.get(by) else "unknown"


def _num(x):
    return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) and x >= 0 else None


def _p(x):
    return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) and 0 <= x <= 1 else None


def outcomes(rows: list[dict], results: dict[str, dict] | None, include_probable: bool) -> dict[str, tuple]:
    """run id -> (ok, source). Result row > last hard verify > (opt in) last probable verify."""
    hard, soft = {}, {}
    for r in rows:
        if r.get("type") == "verify" and r.get("run_id") and isinstance(r.get("ok"), bool):
            (soft if r.get("soft") else hard)[r["run_id"]] = r["ok"]
    out = {}
    for r in rows:
        rid = r.get("run_id")
        if r.get("type") or rid is None:
            continue
        res = (results or {}).get(r.get("label"))
        if res is not None and isinstance(res.get("ok"), bool):
            out[rid] = (res["ok"], "result")
        elif rid in hard:
            out[rid] = (hard[rid], "verify")
        elif include_probable and rid in soft:
            out[rid] = (soft[rid], "probable")
    return out


def replay(rows: list[dict], run_records: dict[str, dict] | None = None, results: dict[str, dict] | None = None,
           only: str = "all", by: str = "auto", include_probable: bool = False, min_n: int = MIN_N,
           rule: dict | None = None) -> dict:
    run_records = run_records or {}
    rows = _ledger._mark_dismissed([dict(r) for r in rows])
    outs = outcomes(rows, results, include_probable)
    probable_only = len({r["run_id"] for r in rows if r.get("type") == "verify" and r.get("soft")
                         and r.get("run_id")} - {r["run_id"] for r in rows if r.get("type") == "verify"
                                                  and not r.get("soft") and r.get("run_id")})
    inp = Counter()
    sources, osrc = Counter(), Counter()
    cells: dict[tuple, dict] = {}
    seen_labels = set()
    for r in rows:
        if r.get("type") or r.get("run_id") is None:
            continue
        inp["ledger_runs"] += 1
        if r.get("dismissed"):
            inp["dismissed"] += 1
            continue
        if only != "all" and _ledger.is_eval(r) != (only == "eval"):
            inp["filtered_out"] += 1
            continue
        rec = run_records.get(r["run_id"])
        if rec is not None:
            inp["run_json_matched"] += 1
            r = {**{k: v for k, v in rec.items() if k not in r or r[k] is None}, **{k: v for k, v in r.items()
                                                                                   if v is not None}}
        rung, src = first_rung(r)
        if rung is None:
            inp["no_first_rung"] += 1
            continue
        sources[src] += 1
        seen_labels.add(r.get("label"))
        cat = category(r, by)
        c = cells.setdefault((cat, rung), {"category": cat, "first_rung": rung, "n": 0, "judged": 0, "final": 0,
                                           "first": 0, "usd": [], "cal": [], "chain": []})
        c["n"] += 1
        attempts = r.get("attempts") if isinstance(r.get("attempts"), int) else None
        if (usd := _num(r.get("ae_usd"))) is not None:
            c["usd"].append((usd, r["run_id"]))
        ok = outs.get(r["run_id"])
        if ok is None:
            c.setdefault("rows", []).append((r["run_id"], None))
        else:
            osrc[ok[1]] += 1
            c["judged"] += 1
            c["final"] += ok[0]
            first_ok = ok[0] and (attempts or 1) <= 1
            c["first"] += first_ok
            c.setdefault("rows", []).append((r["run_id"], ok[0]))
            c["judged_usd"] = c.get("judged_usd", []) + ([usd] if usd is not None else [None])
            route = r.get("route") if isinstance(r.get("route"), dict) else {}
            p, chain = _p(route.get("p", r.get("p"))), _p(route.get("chain_p", r.get("chain_p")))
            planned = r.get("planned_first_rung")
            if planned:
                inp["planned_known"] += 1
                inp["planned_differs"] += planned != rung
            if p is not None or chain is not None:
                pick = planned or route.get("rung")
                if pick is None:
                    inp["p_rung_unknown"] += 1
                elif pick != rung:
                    inp["p_other_rung"] += 1
                else:
                    if p is not None:
                        c["cal"].append((p, 1.0 if first_ok else 0.0))
                    if chain is not None:
                        c["chain"].append((chain, 1.0 if ok[0] else 0.0))
    inp["results_unmatched"] = sum(1 for lab in (results or {}) if lab not in seen_labels)
    table = [_cell_report(c, min_n) for _, c in sorted(cells.items())]
    cal_all = [x for c in cells.values() for x in c["cal"]]
    chain_all = [x for c in cells.values() for x in c["chain"]]
    report = {
        "input": {**{k: inp.get(k, 0) for k in ("ledger_runs", "dismissed", "filtered_out", "no_first_rung",
                                                 "run_json_matched", "planned_known", "planned_differs",
                                                 "p_other_rung", "p_rung_unknown", "results_unmatched")},
                  "probable_only": probable_only, "first_rung_source": dict(sources), "outcome_source": dict(osrc),
                  "only": only, "by": by, "min_n": min_n, "include_probable": include_probable},
        "cells": table,
        "calibration_overall": _calibration(cal_all, chain_all),
        "limitations": LIMITATIONS,
    }
    if rule is not None:
        report["rule"] = apply_rule(cells, check_rule(rule), min_n)
    return report


LIMITATIONS = [
    "History was not randomized: routing chose each rung for the task it saw, so cells are not comparable "
    "with each other and a rate is not a rung's strength.",
    "Rates and costs describe runs judged by a person, the lead or a scored result row; unjudged runs are in n only.",
    "ok_first counts an escalated, retried or fallen-back run as a miss on its first rung (a lower bound).",
    "Cost is the whole run's ae_usd (escalation spend included), not the first attempt's alone.",
    "p is compared only for rows whose routing pick is the rung the run started on; old ledger rows keep no p.",
]


def _cell_report(c: dict, min_n: int) -> dict:
    judged_usd = c.get("judged_usd", [])
    known = [u for u in judged_usd if u is not None]
    allk = [u for u, _ in c["usd"]]
    flags = []
    if not c["judged"]:
        flags.append("no_judged_runs")
    elif c["judged"] < min_n:
        flags.append("small_sample")
    if c["judged"] and len(known) < c["judged"]:
        flags.append("cost_unknown_for_some_judged_runs")
    return {"category": c["category"], "first_rung": c["first_rung"], "n": c["n"], "n_judged": c["judged"],
            "ok_final": rate(c["final"], c["judged"]), "ok_first": rate(c["first"], c["judged"]),
            "cost": {"n_known": len(allk), "mean_usd": round(sum(allk) / len(allk), 6) if allk else None,
                     "judged_known": len(known),
                     "usd_per_success": round(sum(known) / c["final"], 6)
                     if c["final"] and len(known) == c["judged"] else None},
            "calibration": _calibration(c["cal"], c["chain"], bare=True), "flags": flags}


def _calibration(cal: list, chain: list, bare: bool = False):
    if not cal and not chain:
        return None

    def stats(xs):
        if not xs:
            return None
        n = len(xs)
        mp = sum(p for p, _ in xs) / n
        act = sum(o for _, o in xs) / n
        return {"n": n, "mean_p": round(mp, 4), "actual": round(act, 4), "gap": round(mp - act, 4),
                "brier": round(sum((p - o) ** 2 for p, o in xs) / n, 4),
                "flags": ["small_sample"] if n < MIN_N else []}
    first = stats(cal)
    out = dict(first) if first else {"n": 0}
    out["chain"] = stats(chain)
    return out


def check_rule(rule) -> dict:
    if not isinstance(rule, dict) or not (rule.get("default") or rule.get("by_category")):
        raise ValueError('rule must be an object with "default" and/or "by_category"')
    if "default" in rule and not (isinstance(rule["default"], str) and rule["default"]):
        raise ValueError('rule "default" must be a rung string')
    by = rule.get("by_category", {})
    if not isinstance(by, dict) or any(not (isinstance(v, str) and v) for v in by.values()):
        raise ValueError('rule "by_category" must map category -> rung string')
    return rule


def apply_rule(cells: dict, rule: dict, min_n: int) -> dict:
    cats = sorted({cat for cat, _ in cells})
    out, sup_runs, tot_runs = [], 0, 0
    tot_ok = tot_usd = base_n = base_ok = 0.0
    usd_den = 0.0
    for cat in cats:
        rungs = {r: c for (k, r), c in cells.items() if k == cat}
        weight = sum(c["judged"] for c in rungs.values())
        tot_runs += weight
        chosen = (rule.get("by_category") or {}).get(cat, rule.get("default"))
        row = {"category": cat, "rung": chosen, "history_judged": weight, "supported": False}
        cell = rungs.get(chosen) if chosen else None
        if chosen is None:
            row["reason"] = "no rule for this category"
        elif cell is None or not cell["judged"]:
            row["reason"] = f"no history: nothing judged for {chosen} in this category"
        elif cell["judged"] < min_n:
            row["reason"] = f"cell n={cell['judged']} < min_n {min_n}"
        else:
            known = [u for u in cell.get("judged_usd", []) if u is not None]
            row.update(supported=True, cell_n=cell["judged"], est_ok_final=cell["final"] / cell["judged"],
                       est_cost_usd=round(sum(known) / len(known), 6) if known else None,
                       cell_cost_known=len(known))
            sup_runs += weight
            tot_ok += weight * row["est_ok_final"]
            if row["est_cost_usd"] is not None:
                tot_usd += weight * row["est_cost_usd"]
                usd_den += weight
            base_n += weight
            base_ok += sum(c["final"] for c in rungs.values())
            row["history_ok_final"] = sum(c["final"] for c in rungs.values()) / weight
        out.append(row)
    base_usd = [u for (k, _), c in cells.items() if k in {r["category"] for r in out if r["supported"]}
                for u in c.get("judged_usd", []) if u is not None]
    return {
        "rule": {k: v for k, v in rule.items()},
        "categories": out,
        "coverage": {"supported_runs": int(sup_runs), "total_runs": int(tot_runs),
                     "share": round(sup_runs / tot_runs, 4) if tot_runs else None,
                     "supported_categories": sum(r["supported"] for r in out), "categories": len(out)},
        "est_ok_final": round(tot_ok / sup_runs, 4) if sup_runs else None,
        "est_cost_per_run_usd": round(tot_usd / usd_den, 6) if usd_den else None,
        "history_same_categories": {"n": int(base_n), "ok_final": round(base_ok / base_n, 4) if base_n else None,
                                    "mean_cost_usd": round(sum(base_usd) / len(base_usd), 6) if base_usd else None},
        "caveats": ["history was not randomized: a cell's rate describes the tasks it received, not the tasks "
                    "this rule would send there (not an out-of-sample forecast)",
                    "only categories with a cell of at least min_n judged runs are estimated; the rest are "
                    "unsupported, not guessed",
                    "ok_final is end-to-end (escalation included); cost is mean ae_usd of the cell's runs"],
    }


def _pct(x):
    return "-" if x is None else f"{x:.0%}"


def text(report: dict) -> str:
    i = report["input"]
    lines = [f"ledger runs {i['ledger_runs']}  (dismissed {i['dismissed']}, filtered {i['filtered_out']}, "
             f"no first rung {i['no_first_rung']}, probable-only {i['probable_only']})",
             f"first rung from {i['first_rung_source']}; outcome from {i['outcome_source']}", ""]
    lines.append("category / first rung: n judged/n  right(final) [95%]  right(first)  $/run  calibration")
    for c in report["cells"]:
        f, ci = c["ok_final"], c["ok_final"]["ci95"]
        cal = c["calibration"]
        calt = (f"p {cal['mean_p']:.2f} vs {cal['actual']:.2f} (gap {cal['gap']:+.2f}, n={cal['n']})"
                if cal and cal.get("n") else "no p")
        usd = c["cost"]["mean_usd"]
        lines.append(f"{c['category']} / {c['first_rung']}: {c['n_judged']}/{c['n']}  {_pct(f['rate'])} "
                     f"[{'-' if ci is None else f'{ci[0]:.0%}-{ci[1]:.0%}'}] (k={f['k']}, n={f['n']})  "
                     f"{_pct(c['ok_first']['rate'])}  {'-' if usd is None else f'${usd:.3f}'}  {calt}"
                     + (f"  !{','.join(c['flags'])}" if c["flags"] else ""))
    ov = report["calibration_overall"]
    if ov and ov.get("n"):
        lines += ["", f"calibration overall: p {ov['mean_p']:.2f} vs actual {ov['actual']:.2f} "
                      f"(gap {ov['gap']:+.2f}, brier {ov['brier']:.3f}, n={ov['n']})"]
    if "rule" in report:
        r = report["rule"]
        cov = r["coverage"]
        lines += ["", f"rule {r['rule']}: estimated right {_pct(r['est_ok_final'])}, "
                      f"${r['est_cost_per_run_usd'] if r['est_cost_per_run_usd'] is not None else '-'}/run, "
                      f"covering {cov['supported_runs']}/{cov['total_runs']} judged runs "
                      f"({cov['supported_categories']}/{cov['categories']} categories)",
                  f"  history on the same categories: {r['history_same_categories']}"]
        lines += [f"  unsupported {c['category']}: {c['reason']}" for c in r["categories"] if not c["supported"]]
        lines += [f"  note: {c}" for c in r["caveats"]]
    lines += ["", *[f"limit: {s}" for s in report["limitations"]]]
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ledger", action="append", type=Path, default=[], help="ledger.jsonl (repeatable)")
    p.add_argument("--hub", type=Path, help="a hub folder: its ccx/ledger.jsonl and ccx/runs")
    p.add_argument("--runs", action="append", type=Path, default=[], help="folder of <run id>/run.json")
    p.add_argument("--results", action="append", type=Path, default=[], help="scored result rows, joined by label")
    p.add_argument("--only", choices=("all", "eval", "real"), default="all",
                   help="evaluation runs (label eval-..., --no-ab, probes) vs real use")
    p.add_argument("--by", choices=("auto", "category", "task_type", "task", "role", "mode"), default="auto")
    p.add_argument("--include-probable", action="store_true", help="count probable (soft) verdicts as outcomes")
    p.add_argument("--min-n", type=int, default=MIN_N, help="judged runs below this are flagged small_sample and "
                   "cannot support a rule estimate (default %(default)s)")
    p.add_argument("--rule", help="candidate first-rung rule: a JSON file or a literal JSON object")
    p.add_argument("--text", action="store_true", help="a readable table instead of JSON")
    a = p.parse_args(argv)
    ledgers, runs = list(a.ledger), list(a.runs)
    if a.hub:
        ledgers.append(a.hub / "ccx" / "ledger.jsonl")
        if (a.hub / "ccx" / "runs").is_dir():
            runs.append(a.hub / "ccx" / "runs")
    if not ledgers:
        p.error("give --ledger FILE or --hub DIR")
    for f in ledgers:
        if not _check_path(f).is_file():
            raise SystemExit(f"ledger not found: {f}")
    for d in runs:
        if not _check_path(d).is_dir():
            raise SystemExit(f"runs folder not found: {d}")
    rows = [r for f in ledgers for r in load_ledger(f)]
    records = {k: v for d in runs for k, v in load_runs(d).items()}
    results = index_results([r for f in a.results for r in load_results(f)])
    rule = None
    if a.rule:
        s = a.rule.strip()
        try:
            rule = json.loads(s if s.startswith("{") else _check_path(s).read_text(encoding="utf-8"))
            check_rule(rule)
        except (OSError, ValueError) as e:
            raise SystemExit(f"bad --rule: {e}")
    report = replay(rows, records, results, a.only, a.by, a.include_probable, a.min_n, rule)
    sys.stdout.write(text(report) if a.text else json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
