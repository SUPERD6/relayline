"""Offline routing calibration (issue #429): by task-size signal, how often doing a task yourself and delegating it
came out right, what each cost and how long each took, and where the `small_self` / band thresholds could sit.
Read-only, standard library; no model CLI, no network. Changes no default. Output is an input to the stage-4
pre-registration, not a result to extrapolate. Reuses scripts/eval/ledger_replay.py (inputs, first-hand outcome rule).

Inputs (explicit files only; a path under `eval-codex-home` is refused): --ledger FILE (repeatable), --hub DIR
(DIR/ccx/ledger.jsonl + DIR/ccx/runs), --runs DIR (run.json adds signals the slim ledger row lacks), --results FILE
(scored result rows joined by label, as ledger_replay).

Arms (what "self" and "delegated" are in the ledger):
- delegated: ledger run rows (not `review:` runs, not dismissed). Outcome as ledger_replay / receipt_fp: a scorable
  result row's `ok`, else the last non-probable `verify`. The run row's own `ok` only says it finished. Cost = ae_usd
  (sub-agent attempts only: the lead's brief, wait and acceptance are NOT in it), seconds = the run's wall time.
- self: `selfrun` event rows (`ccx ab` closed samples: the lead's own work on a task). Their outcome is the person's
  `ok` flag on that row (there is no hidden test or verify for them; counted apart in outcome_source). Cost = the
  lead's whole usage window priced, seconds = the sample's wall time. `type` rows other than selfrun are not tasks.
  Proposals answered "no" (the lead did it itself) leave no outcome, so they are not in this arm.

Size signals (the ones plan.py / task_routing.py use; each is a separate table, a run can lack any of them, and a
missing signal is its own bucket "(missing)", never guessed): b (difficulty from files, coupling, clarity, risk,
novelty), files (the lead's estimate, else rubric, else files named in the brief), minutes (the lead's estimate),
band (small/medium/large from files, minutes, brief words: task_routing.size_band), coupling, clarity. Signals come
from the ledger row, then run.json (route.b, route.policy.signals, route.rubric, route.objective.files_named).
`words` (the third band input) and the self_first conditions (lead quota, context, explicit assignment, independent
parts) are not stored per run, so they cannot be calibrated from a ledger.

Strata are never mixed: `real` (use by the person) and `eval` (ledger.is_eval: eval- label, --no-ab, ccx probes).

Per bucket and arm: n (runs), n_judged, right = k/n with its Wilson 95% interval, cost and seconds (mean, median
over the judged runs with a known value, with how many are known), usd per right result. Per bucket the arms are
compared by Newcombe's score interval of (self - delegated) in right rate, only when both arms have at least
--min-n judged runs; otherwise verdict "insufficient". Verdict: delegate_better (the whole interval < 0),
self_not_worse (interval lower bound >= -margin, default 0.10), else unresolved.
Threshold candidate per ordered signal (b, files, minutes, band, coupling, clarity): from the smallest bucket up, the
longest run of self_not_worse buckets ends at `self_ok_up_to`; the first delegate_better bucket starts at
`delegate_better_from`. The interval between them is unresolved; with no such bucket the end is null (Unknown).

Examples:
  python scripts/eval/routing_calibration.py --hub ~/.ccx-hub --text
  python scripts/eval/routing_calibration.py --ledger ledger.jsonl --runs hub/ccx/runs --margin 0.15 --min-n 8
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import math
from pathlib import Path
import statistics
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import ledger_replay as R
from ccx import ledger as _ledger

MISSING = "(missing)"
MARGIN = 0.10
# bucket edges follow the shipped cut points so that candidates are comparable with them: files 2 / 3 are the
# band edges (task_routing DEFAULT_POLICY bands medium_files / large_files), minutes 15 / 45 likewise
SIGNALS: dict[str, dict] = {
    "b": {"kind": "num", "edges": [2, 3, 4, 5], "labels": ["<2", "2-3", "3-4", "4-5", ">=5"]},
    "files": {"kind": "num", "edges": [2, 3], "labels": ["1", "2", ">=3"]},
    "minutes": {"kind": "num", "edges": [15, 45], "labels": ["<15", "15-45", ">=45"]},
    "band": {"kind": "cat", "labels": ["small", "medium", "large"]},
    "coupling": {"kind": "cat", "labels": ["one", "cross", "system"]},
    "clarity": {"kind": "cat", "labels": ["spec", "goal", "unknown"]},
}
CURRENT = {"routing.small_self_files": 1, "bands.medium_files": 2, "bands.large_files": 3,
           "bands.medium_minutes": 15, "bands.large_minutes": 45,
           "note": "shipped defaults for reference (ccx/commands/delegation.py _small_self, skills/task-routing); "
                   "this report does not change them"}
LIMITATIONS = [
    "History was not randomized: routing and the person chose who did each task, so an arm's rate describes the "
    "tasks it got, not what the other arm would have done on them; a bucket is not a controlled comparison.",
    "The self arm is the ccx ab self-run samples only (their outcome is the person's own ok flag); tasks done "
    "yourself without a sample leave no row, so most 'self' work is invisible here.",
    "Delegated cost is the sub-agent's ae_usd and leaves out the lead's brief, wait and acceptance; self cost is the "
    "lead's whole usage window. Costs are not directly comparable; seconds likewise.",
    "Signals are the lead's estimates (or ledger-kept ones) and many runs have none: buckets cover the runs that "
    "carry the signal, and (missing) is reported, not imputed.",
    "Eval and real use are separate strata; neither is extrapolated to the other.",
    "Small judged samples give wide intervals; a bucket below --min-n in either arm is marked insufficient.",
    "self_first conditions (lead quota, context size, explicit assignment, independent parts) are not recorded per "
    "run and are not size-based: they are not calibrated here.",
]


def newcombe(k1: int, n1: int, k2: int, n2: int):
    """Newcombe hybrid-score 95% interval of p1 - p2 (Wilson intervals of both); None when either n is 0."""
    if n1 <= 0 or n2 <= 0:
        return None
    p1, p2 = k1 / n1, k2 / n2
    l1, u1 = R.wilson(k1, n1)
    l2, u2 = R.wilson(k2, n2)
    d = p1 - p2
    return (max(-1.0, d - math.sqrt((p1 - l1) ** 2 + (u2 - p2) ** 2)),
            min(1.0, d + math.sqrt((u1 - p1) ** 2 + (p2 - l2) ** 2)))


def _dig(d, *keys):
    for k in keys:
        d = d.get(k) if isinstance(d, dict) else None
    return d


def signals_of(r: dict) -> dict:
    """The size signals a run (ledger row, run.json fields filled in) carries; absent ones are not in the dict."""
    route = r.get("route") if isinstance(r.get("route"), dict) else {}
    out = {}
    b = R._num(r["b"] if r.get("b") is not None else route.get("b"))
    if b is not None:
        out["b"] = b
    minutes = next((m for m in (R._num(r.get("estimate_minutes")), R._num(_dig(route, "policy", "signals", "minutes")),
                                R._num(route.get("minutes"))) if m), None)
    if minutes:
        out["minutes"] = minutes
    files = next((f for f in (R._num(_dig(route, "policy", "signals", "files")), R._num(_dig(route, "rubric", "files")),
                              R._num(_dig(route, "objective", "files_named")), R._num(r.get("estimate_files"))) if f),
                 None)
    if files:
        out["files"] = files
    band = r.get("band") or _dig(route, "policy", "band")
    if band in SIGNALS["band"]["labels"]:
        out["band"] = band
    for k in ("coupling", "clarity"):
        v = _dig(route, "rubric", k)
        if v in SIGNALS[k]["labels"]:
            out[k] = v
    return out


def bucket_of(signal: str, sig: dict) -> str:
    spec = SIGNALS[signal]
    v = sig.get(signal)
    if v is None:
        return MISSING
    if spec["kind"] == "cat":
        return v
    return spec["labels"][sum(v >= e for e in spec["edges"])]


def cohort(rows: list[dict], run_records: dict | None = None, results: list[dict] | None = None,
           include_probable: bool = False) -> tuple[list[dict], dict]:
    """One record per task attempt: arm, stratum, outcome (bool | None), cost, seconds, signals. And input counters."""
    run_records = run_records or {}
    rows = _ledger._mark_dismissed([dict(r) for r in rows])
    outs, res_n = R.outcomes(rows, results, include_probable)
    inp = Counter()
    recs = []
    for r in rows:
        t = r.get("type")
        if t == "selfrun":
            inp["selfruns"] += 1
            ok = r.get("ok")
            recs.append({"arm": "self", "stratum": "eval" if _ledger.is_eval(r) else "real",
                         "ok": ok if type(ok) is bool else None, "osrc": "selfrun_ok" if type(ok) is bool else None,
                         "usd": R._num(r.get("ae_usd")), "seconds": R._num(r.get("seconds")),
                         "sig": signals_of(r), "trial": bool(r.get("trial"))})
            continue
        if t or r.get("run_id") is None:
            continue
        inp["ledger_runs"] += 1
        if r.get("dismissed"):
            inp["dismissed"] += 1
            continue
        if str(r.get("label") or "").startswith("review:"):
            inp["review_runs"] += 1
            continue
        rec = run_records.get(r["run_id"])
        if rec is not None:
            inp["run_json_matched"] += 1
            r = {**{k: v for k, v in rec.items() if k not in r or r[k] is None},
                 **{k: v for k, v in r.items() if v is not None}}
        o = outs.get(r["run_id"])
        recs.append({"arm": "delegated", "stratum": "eval" if _ledger.is_eval(r) else "real",
                     "ok": o[0] if o else None, "osrc": o[1] if o else None, "usd": R._num(r.get("ae_usd")),
                     "seconds": R._num(r.get("seconds")), "sig": signals_of(r), "trial": bool(r.get("trial"))})
    inp.update({k: res_n.get(k, 0) for k in ("results_unscorable", "results_unmatched", "results_multi_run")})
    return recs, dict(inp)


def _stat(xs: list[float]) -> dict:
    return {"n_known": len(xs), "mean": round(sum(xs) / len(xs), 4) if xs else None,
            "median": round(statistics.median(xs), 4) if xs else None}


def arm_cell(recs: list[dict]) -> dict:
    judged = [x for x in recs if x["ok"] is not None]
    k = sum(x["ok"] for x in judged)
    usd = [x["usd"] for x in judged if x["usd"] is not None]
    secs = [x["seconds"] for x in judged if x["seconds"] is not None]
    cost = _stat(usd)
    cost["usd_per_right"] = round(sum(usd) / k, 4) if k and len(usd) == len(judged) else None
    return {"n": len(recs), "n_judged": len(judged), "right": R.rate(k, len(judged)), "cost_usd": cost,
            "seconds": _stat(secs), "outcome_source": dict(Counter(x["osrc"] for x in judged)),
            "trial_runs": sum(x["trial"] for x in recs)}


def compare(selfc: dict, delc: dict, min_n: int, margin: float) -> dict:
    ks, ns, kd, nd = selfc["right"]["k"], selfc["right"]["n"], delc["right"]["k"], delc["right"]["n"]
    if ns < min_n or nd < min_n:
        why = f"judged self {ns}, delegated {nd}; need at least {min_n} in each arm"
        return {"verdict": "insufficient", "why": why}
    lo, hi = newcombe(ks, ns, kd, nd)
    d = ks / ns - kd / nd
    verdict = "delegate_better" if hi < 0 else "self_not_worse" if lo >= -margin else "unresolved"
    return {"verdict": verdict, "diff_self_minus_delegated": round(d, 4), "ci95": [round(lo, 4), round(hi, 4)],
            "margin": margin}


def threshold(signal: str, buckets: list[dict]) -> dict:
    """From the smallest bucket up: where the self_not_worse run ends, and the first delegate_better bucket."""
    ordered = [b for b in buckets if b["bucket"] != MISSING]
    up_to = None
    for b in ordered:
        if b["compare"]["verdict"] != "self_not_worse":
            break
        up_to = b["bucket"]
    first_bad = next((b["bucket"] for b in ordered if b["compare"]["verdict"] == "delegate_better"), None)
    decided = [b["bucket"] for b in ordered if b["compare"]["verdict"] != "insufficient"]
    if up_to is None and first_bad is None:
        status = "undetermined"
    else:
        status = "partial"
    return {"signal": signal, "status": status, "self_ok_up_to": up_to, "delegate_better_from": first_bad,
            "buckets_compared": decided, "buckets_insufficient": [b["bucket"] for b in ordered if
                                                                  b["compare"]["verdict"] == "insufficient"],
            "note": "buckets between self_ok_up_to and delegate_better_from are unresolved; null = Unknown, "
                    "not 'no threshold'"}


def signal_table(recs: list[dict], signal: str, min_n: int, margin: float) -> dict:
    labels = SIGNALS[signal]["labels"] + [MISSING]
    buckets = []
    for label in labels:
        here = [x for x in recs if bucket_of(signal, x["sig"]) == label]
        if not here:
            continue
        s = arm_cell([x for x in here if x["arm"] == "self"])
        d = arm_cell([x for x in here if x["arm"] == "delegated"])
        flags = []
        for name, c in (("self", s), ("delegated", d)):
            if not c["n"]:
                flags.append(f"no_{name}_runs")
            elif c["n_judged"] < min_n:
                flags.append(f"small_sample_{name}")
        buckets.append({"bucket": label, "self": s, "delegated": d, "compare": compare(s, d, min_n, margin),
                        "flags": flags})
    return {"buckets": buckets, "threshold": threshold(signal, buckets)}


def calibrate(rows: list[dict], run_records: dict | None = None, results: list[dict] | None = None,
              include_probable: bool = False, min_n: int = R.MIN_N, margin: float = MARGIN) -> dict:
    recs, inp = cohort(rows, run_records, results, include_probable)
    strata = {}
    for st in ("real", "eval"):
        part = [x for x in recs if x["stratum"] == st]
        strata[st] = {"n_self": sum(x["arm"] == "self" for x in part),
                      "n_delegated": sum(x["arm"] == "delegated" for x in part),
                      "n_judged_self": sum(x["arm"] == "self" and x["ok"] is not None for x in part),
                      "n_judged_delegated": sum(x["arm"] == "delegated" and x["ok"] is not None for x in part),
                      "with_signal": {s: sum(s in x["sig"] for x in part) for s in SIGNALS},
                      "signals": {s: signal_table(part, s, min_n, margin) for s in SIGNALS}}
    return {"input": {**inp, "min_n": min_n, "margin": margin, "include_probable": include_probable},
            "current_defaults": CURRENT, "strata": strata, "limitations": LIMITATIONS}


def _pct(x):
    return "-" if x is None else f"{x:.0%}"


def _arm_text(c: dict) -> str:
    r = c["right"]
    ci = r["ci95"]
    usd, sec = c["cost_usd"]["mean"], c["seconds"]["mean"]
    return (f"{r['k']}/{r['n']} {_pct(r['rate'])}" + ("" if ci is None else f" [{ci[0]:.0%}-{ci[1]:.0%}]")
            + f" (runs {c['n']})  ${'-' if usd is None else f'{usd:.2f}'}  {'-' if sec is None else f'{sec:.0f}s'}")


def text(report: dict) -> str:
    i = report["input"]
    lines = [f"input: {i}", ""]
    for st, s in report["strata"].items():
        lines.append(f"== {st}: self {s['n_self']} (judged {s['n_judged_self']}), delegated {s['n_delegated']} "
                     f"(judged {s['n_judged_delegated']}); runs with signal {s['with_signal']}")
        for sig, tab in s["signals"].items():
            if not tab["buckets"]:
                continue
            t = tab["threshold"]
            lines.append(f"  [{sig}] threshold: self ok up to {t['self_ok_up_to']}, delegate better from "
                         f"{t['delegate_better_from']} ({t['status']})")
            for b in tab["buckets"]:
                c = b["compare"]
                lines.append(f"    {b['bucket']:>8}  self {_arm_text(b['self'])} | deleg {_arm_text(b['delegated'])} | "
                             f"{c['verdict']}" + (f" diff {c['diff_self_minus_delegated']:+.2f} "
                                                  f"[{c['ci95'][0]:+.2f},{c['ci95'][1]:+.2f}]" if "ci95" in c else "")
                             + (f"  !{','.join(b['flags'])}" if b["flags"] else ""))
        lines.append("")
    lines += [f"current defaults: {report['current_defaults']}", ""]
    lines += [f"limit: {x}" for x in report["limitations"]]
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ledger", action="append", type=Path, default=[], help="ledger.jsonl (repeatable)")
    p.add_argument("--hub", type=Path, help="a hub folder: its ccx/ledger.jsonl and ccx/runs")
    p.add_argument("--runs", action="append", type=Path, default=[], help="folder of <run id>/run.json")
    p.add_argument("--results", action="append", type=Path, default=[], help="scored result rows, joined by label")
    p.add_argument("--include-probable", action="store_true", help="count probable (soft) verdicts as outcomes")
    p.add_argument("--min-n", type=int, default=R.MIN_N, help="judged runs per arm below this: bucket insufficient")
    p.add_argument("--margin", type=float, default=MARGIN, help="self_not_worse: interval lower bound >= -margin")
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
        if not R._check_path(f).is_file():
            raise SystemExit(f"ledger not found: {f}")
    for d in runs:
        if not R._check_path(d).is_dir():
            raise SystemExit(f"runs folder not found: {d}")
    rows = [r for f in ledgers for r in R.load_ledger(f)]
    records = {k: v for d in runs for k, v in R.load_runs(d).items()}
    results = R.index_results([r for f in a.results for r in R.load_results(f)])
    report = calibrate(rows, records, results, a.include_probable, a.min_n, a.margin)
    sys.stdout.write(text(report) if a.text else json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
