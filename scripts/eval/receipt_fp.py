"""Receipt false positives: the receipt said ok/done but the hidden tests fail (issue #377). Read-only; standard library.

For every scorable result row whose ccx receipt claims success, count how often the hidden test (the row's `ok`,
bool) still failed. Reported per receipt type, as failures / n with a one-sided 95% upper bound
(Clopper-Pearson, exact binomial; docs/engineering-standards.md "Receipt false positive"). Each type also gets a
`verdict` by the bar of docs/research/2026-11-17-eval-rule-decisions.md section 2 (#411, decision 2): Pass when the
point estimate is <= 2% and the upper bound is <= 5%; Fail when the point estimate is > 2%; otherwise Unknown
(smallest passing samples 0/59, 1/93, 2/124, 4/200). `below_2pct` keeps its old meaning (upper bound <= 2%).

Receipt type, from the receipt's own fields (a row's `kind` and `status`, the ccx ledger's slim fields):
- ok               kind == "ok": the ordinary receipt the 2% bar is about.
- ok_self_checked  kind == "ok_self_checked": the check ran only tests the sub-agent wrote or changed; counted apart.
- done             no kind, status == "done": the receipt says done and carries no verification kind (older rows,
                   memory runs). A kind of check_failed / check_broken / check_baseline_failed is not an ok claim.
- UNVERIFIED       only when a row carries the lead view's `headline` (leadview.receipt_headline); no result row
                   stores one today, so this is n = 0 until a runner does. A `headline` overrides kind/status:
                   DONE -> done, SELF_CHECKED -> ok_self_checked, UNVERIFIED -> UNVERIFIED, anything else -> no claim.
- all_claims       the four above together (descriptive, not a bar).

Rows are not counted when: the run errored (`error`, `invalid`, `environment_error`, receipt status "error") or its
hidden outcome is null (`unscorable`); the receipt claims no success (`no_ok_claim`, with how many hidden tests still
passed); or the row holds no receipt (`no_receipt`: P4 rows keep only run ids, so pass the hub's ledger.jsonl with
--ledger and the unit's last non-review run is its receipt). n = 0 is Unknown: the upper bound is given as 1.0.

Examples:
  python scripts/eval/receipt_fp.py OUT_DIR_OR_RESULTS.jsonl [MORE ...] --text
  python scripts/eval/receipt_fp.py p4-results.jsonl --ledger HUB/ccx/ledger.jsonl --by arm
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import unified_summary as U

TYPES = ("ok", "ok_self_checked", "done", "UNVERIFIED")
FAIL_KINDS = ("check_failed", "check_broken", "check_baseline_failed")
HEADLINE_TYPE = {"DONE": "done", "SELF_CHECKED": "ok_self_checked", "UNVERIFIED": "UNVERIFIED"}
METHOD = "Clopper-Pearson one-sided 95% upper bound (exact binomial)"
ALPHA = 0.05
POINT_MAX_PCT = 2     # bar: point estimate <= 2 %
UPPER_MAX = 0.05      # bar: one-sided 95% upper bound <= 5 %


def cp_upper(k: int, n: int, alpha: float = ALPHA) -> float:
    """One-sided (1 - alpha) Clopper-Pearson upper bound of a binomial rate: the p with P(X <= k | n, p) = alpha.
    n = 0 gives 1.0 (no information); k = n gives 1.0."""
    if n < 0 or not 0 <= k <= n:
        raise ValueError(f"need 0 <= k <= n, got k={k}, n={n}")
    if n == 0 or k == n:
        return 1.0
    if k == 0:
        return 1 - alpha ** (1 / n)
    lo, hi = k / n, 1.0
    for _ in range(200):
        mid = (lo + hi) / 2
        # P(X <= k) = I_{1-p}(n - k, k + 1), decreasing in p
        lo, hi = (mid, hi) if U._betainc(n - k, k + 1, 1 - mid) > alpha else (lo, mid)
    return (lo + hi) / 2


def read_ledger(path: Path) -> dict[str, dict]:
    """run_id -> ledger entry, in file order (`_pos`); event rows (with a "type") are not runs."""
    entries = {}
    for pos, entry in enumerate(U.read_rows(path)):
        if not entry.get("type") and entry.get("run_id") is not None:
            entries[entry["run_id"]] = {**entry, "_pos": pos}
    return entries


def load_rows(path: Path) -> list[dict]:
    return U.strength_rows(path) if path.is_dir() else U.read_rows(path)


def receipt_type(receipt: dict) -> str | None:
    """The receipt type a record claims, or None when it does not claim success."""
    headline = receipt.get("headline")
    if headline is not None:
        return HEADLINE_TYPE.get(headline)
    kind, status = receipt.get("kind"), receipt.get("status")
    if kind in FAIL_KINDS or status == "error":
        return None
    if kind in ("ok", "ok_self_checked"):
        return kind
    # any other kind (no_answer, no_changes, review_failed, review_issues, ...) is not a success claim, whatever
    # its status: leadview.receipt_headline does not treat it as one
    return "done" if kind is None and status == "done" else None


def _receipt_of(row: dict, ledger: dict[str, dict] | None) -> dict | None:
    """The row's own receipt fields, else its unit's last non-review ledger run; None when there is no receipt."""
    if "kind" in row or "status" in row or "headline" in row:
        return row
    ids = row.get("ccx_run_ids") or ([row["run_id"]] if row.get("run_id") else [])
    runs = [ledger[i] for i in ids if ledger and i in ledger
            and not str(ledger[i].get("label") or "").startswith("review:")]
    if not runs:
        return None
    last = max(runs, key=lambda e: e["_pos"])
    # a ledger run whose own ok is false is not a success claim (a result row's ok is the hidden test, not this)
    return {**last, "status": "not_ok"} if last.get("ok") is False else last


def bar_verdict(failures: int, n: int) -> str:
    """The receipt false-positive bar (#411 decision 2): Pass when the point estimate is <= 2% and the one-sided
    95% Clopper-Pearson upper bound is <= 5%; Fail when the point estimate is > 2%; otherwise (too few receipts,
    or n = 0) Unknown. Smallest passing samples: 0/59, 1/93, 2/124, 4/200."""
    if n == 0:
        return "Unknown"
    if failures * 100 > n * POINT_MAX_PCT:       # integer compare: 1/50 is exactly 2%, not above it
        return "Fail"
    return "Pass" if cp_upper(failures, n) <= UPPER_MAX else "Unknown"


def _bound(failures: int, n: int, bar: bool = True) -> dict:
    upper = cp_upper(failures, n)
    out = {"failures": failures, "n": n, "rate": failures / n if n else None, "upper95": upper,
           "upper95_method": METHOD, "below_2pct": bool(n) and upper <= 0.02}
    if bar:
        out["verdict"] = bar_verdict(failures, n)
        out["bar"] = {"point_max": POINT_MAX_PCT / 100, "upper95_max": UPPER_MAX}
    if not bar:      # all_claims mixes types: the 2% bar is only about ordinary ok
        out.pop("below_2pct")
        out["status"] = "descriptive" if n else "Unknown"
        if not n:
            out["note"] = "n = 0 is Unknown; upper bound given as 1.0 (no information)"
    elif not n:
        out.update(status="Unknown", note="n = 0 is Unknown; upper bound given as 1.0 (no information)")
    else:
        out["status"] = "below 2%" if out["below_2pct"] else "not shown below 2%"
    return out


def summarize(rows: list[dict], ledger: dict[str, dict] | None = None, by: str | None = None) -> dict:
    """Counts and bounds per receipt type; with `by`, the same per value of that row field under "groups"."""
    U.check_outcomes(rows, "receipt")
    counts = {t: [0, 0] for t in TYPES}          # [failures, n]
    unscorable = no_claim = no_claim_pass = no_receipt = 0
    for row in rows:
        if (row.get("error") or row.get("invalid") is True or row.get("environment_error") is True
                or row.get("ok") is None):
            unscorable += 1
            continue
        receipt = _receipt_of(row, ledger)
        if receipt is None:
            no_receipt += 1
            continue
        if receipt.get("status") == "error":
            unscorable += 1
            continue
        kind = receipt_type(receipt)
        if kind is None:
            no_claim += 1
            no_claim_pass += row["ok"] is True
            continue
        counts[kind][1] += 1
        counts[kind][0] += row["ok"] is False
    types = {t: _bound(*counts[t]) for t in TYPES}
    types["all_claims"] = _bound(sum(c[0] for c in counts.values()), sum(c[1] for c in counts.values()), bar=False)
    result = {"rows": len(rows), "unscorable": unscorable, "no_ok_claim": no_claim,
              "no_ok_claim_hidden_pass": no_claim_pass, "no_receipt": no_receipt, "types": types,
              "definition": "failure = receipt claims success but the hidden test (row ok) is false"}
    if by:
        values = sorted({str(row.get(by)) for row in rows})
        result["by"] = by
        result["groups"] = {v: summarize([r for r in rows if str(r.get(by)) == v], ledger)
                            for v in values}
    return result


def _fmt(value) -> str:
    return "null" if value is None else f"{value:.4f}" if isinstance(value, float) else str(value)


def text_report(result: dict) -> str:
    def block(res: dict) -> list[str]:
        lines = [U.table(["type", "failures/n", "rate", "upper95", "status", "verdict"],
                         [[t, f"{b['failures']}/{b['n']}", _fmt(b["rate"]), _fmt(b["upper95"]), b["status"],
                           b.get("verdict", "-")]
                          for t, b in res["types"].items()]),
                 f"rows {res['rows']}: unscorable {res['unscorable']}, no ok claim {res['no_ok_claim']} "
                 f"(hidden pass {res['no_ok_claim_hidden_pass']}), no receipt {res['no_receipt']}"]
        return lines
    lines = ["false positive = " + result["definition"], "upper95 = " + METHOD + "; n = 0 -> 1.0, Unknown",
             "verdict: Pass = point <= 2% and upper95 <= 5%; Fail = point > 2%; otherwise Unknown (#411 decision 2)",
             *block(result)]
    for value, res in result.get("groups", {}).items():
        lines += ["", f"{result['by']} = {value}", *block(res)]
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("paths", nargs="+", type=Path, help="results directory (results.jsonl / report.json) or JSONL file")
    parser.add_argument("--ledger", type=Path, help="hub ccx/ledger.jsonl: receipt kind/status for rows that keep only run ids")
    parser.add_argument("--by", help="also report per value of this row field (e.g. arm, agent, task)")
    parser.add_argument("--text", action="store_true", help="print a table instead of JSON")
    args = parser.parse_args(argv)
    try:
        rows = [row for path in args.paths for row in load_rows(path)]
        result = summarize(rows, read_ledger(args.ledger) if args.ledger else None, args.by)
        output = text_report(result) if args.text else json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
