"""Receipt false-positive statistics (issue #377): synthetic rows only, no model CLI, no network."""
import json
import math
import os
from pathlib import Path
import subprocess
import sys

import pytest

EVAL = Path(__file__).resolve().parents[1] / "scripts/eval"
sys.path.insert(0, str(EVAL))
import receipt_fp as R


def write_rows(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8", newline="")


def row(kind=None, status="done", ok=True, **extra):
    return {"arm": "a", "task": "t", "kind": kind, "status": status, "ok": ok, **extra}


def binom_cdf(k, n, p):
    return sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k + 1))


# ---- Clopper-Pearson upper bound ----

def test_upper_zero_failures_matches_closed_form():
    # 0/n: 1 - 0.05 ** (1 / n); the standards' "about 15%" for 0/19
    assert R.cp_upper(0, 19) == pytest.approx(1 - 0.05 ** (1 / 19), abs=1e-9)
    assert round(R.cp_upper(0, 19), 3) == 0.146


@pytest.mark.parametrize("k,n", [(1, 10), (8, 209), (3, 50), (5, 6)])
def test_upper_solves_the_binomial_tail(k, n):
    u = R.cp_upper(k, n)
    assert binom_cdf(k, n, u) == pytest.approx(0.05, abs=1e-8)
    assert k / n < u <= 1


def test_upper_all_failures_is_one_and_zero_denominator_is_one():
    assert R.cp_upper(4, 4) == 1.0
    assert R.cp_upper(0, 0) == 1.0


def test_upper_rejects_bad_counts():
    for k, n in ((-1, 5), (6, 5)):
        with pytest.raises(ValueError):
            R.cp_upper(k, n)


# ---- classification ----

def test_receipt_type_uses_real_kinds_and_status():
    assert R.receipt_type(row("ok")) == "ok"
    assert R.receipt_type(row("ok_self_checked")) == "ok_self_checked"
    assert R.receipt_type(row(None, "done")) == "done"
    assert R.receipt_type(row("check_broken", "done")) is None   # the receipt itself says the check is broken
    assert R.receipt_type(row("check_failed", "done")) is None
    for kind in ("no_changes", "no_answer", "review_failed", "review_issues", "some_new_kind"):
        assert R.receipt_type(row(kind, "done")) is None      # status done, but not a success claim
    assert R.receipt_type(row(None, "partial")) is None
    assert R.receipt_type(row(None, "blocked", ok=False)) is None
    assert R.receipt_type(row(None, "error")) is None


def test_receipt_type_headline_wins_when_a_row_carries_one():
    assert R.receipt_type(row("ok", headline="UNVERIFIED")) == "UNVERIFIED"
    assert R.receipt_type(row(None, headline="DONE")) == "done"
    assert R.receipt_type(row(None, headline="SELF_CHECKED")) == "ok_self_checked"
    assert R.receipt_type(row("ok", headline="CHECK_FAILED")) is None


# ---- summary ----

def test_empty_input_is_unknown_not_zero():
    out = R.summarize([])
    assert out["rows"] == 0
    assert all(t["n"] == 0 and t["rate"] is None and t["upper95"] == 1.0 and t["status"] == "Unknown"
               for t in out["types"].values())
    assert out["types"]["ok"]["note"].startswith("n = 0")


def test_all_correct_gives_zero_numerator_with_upper_bound():
    out = R.summarize([row("ok") for _ in range(19)])
    t = out["types"]["ok"]
    assert (t["failures"], t["n"], t["rate"]) == (0, 19, 0.0)
    assert t["upper95"] == pytest.approx(0.14587, abs=1e-4)
    assert t["upper95_method"].startswith("Clopper-Pearson one-sided")
    assert t["below_2pct"] is False and t["status"] == "not shown below 2%"


def test_false_positives_split_by_type():
    rows = ([row("ok") for _ in range(6)] + [row("ok", ok=False)] +
            [row("ok_self_checked", ok=False), row("ok_self_checked")] +
            [row(None, "done"), row(None, "done", ok=False), row(None, "done", ok=False)])
    out = R.summarize(rows)["types"]
    assert (out["ok"]["failures"], out["ok"]["n"]) == (1, 7)
    assert (out["ok_self_checked"]["failures"], out["ok_self_checked"]["n"]) == (1, 2)
    assert (out["done"]["failures"], out["done"]["n"]) == (2, 3)
    assert out["UNVERIFIED"]["n"] == 0
    assert out["ok"]["rate"] == pytest.approx(1 / 7)
    assert out["all_claims"]["n"] == 12 and out["all_claims"]["failures"] == 4
    assert out["all_claims"]["status"] == "descriptive" and "below_2pct" not in out["all_claims"]


def test_enough_clean_receipts_clear_the_two_percent_bar():
    out = R.summarize([row("ok") for _ in range(149)])["types"]["ok"]
    assert out["upper95"] < 0.02 and out["below_2pct"] is True and out["status"] == "below 2%"


def test_non_success_kinds_with_done_status_are_no_claim_not_false_positives():
    rows = [row("no_changes", "done", ok=False), row("review_issues", "done", ok=False), row("ok")]
    out = R.summarize(rows)
    assert out["types"]["done"]["n"] == 0 and out["types"]["ok"]["n"] == 1
    assert out["no_ok_claim"] == 2


def test_ledger_run_with_ok_false_is_no_claim_and_pos_follows_file_order(tmp_path):
    ledger = tmp_path / "l.jsonl"
    write_rows(ledger, [{"run_id": "a", "kind": "ok", "status": "done", "ok": True},
                        {"run_id": "b", "kind": None, "status": "done", "ok": False},
                        {"run_id": "a", "kind": "ok", "status": "done", "ok": True}])   # duplicate id, later line
    entries = R.read_ledger(ledger)
    assert entries["a"]["_pos"] == 2 and entries["b"]["_pos"] == 1
    out = R.summarize([{"ok": False, "ccx_run_ids": ["b"]}, {"ok": True, "ccx_run_ids": ["b", "a"]}], entries)
    assert out["types"]["done"]["n"] == 0 and out["no_ok_claim"] == 1 and out["types"]["ok"]["n"] == 1


def test_unscorable_rows_are_counted_apart_never_as_failures():
    rows = [row("ok"), row("ok", ok=None), row("ok", error="interrupted"), row("ok", invalid=True),
            row("ok", environment_error=True), row("check_failed", ok=False), row(None, "partial", ok=True)]
    out = R.summarize(rows)
    assert (out["types"]["ok"]["n"], out["types"]["ok"]["failures"]) == (1, 0)
    assert out["unscorable"] == 4          # ok None, error, invalid, environment_error
    assert out["no_ok_claim"] == 2         # check_failed, partial
    assert out["no_ok_claim_hidden_pass"] == 1


def test_non_bool_outcome_is_rejected():
    with pytest.raises(ValueError):
        R.summarize([row("ok", ok="yes")])


def test_group_by_field():
    rows = [row("ok", arm="x"), row("ok", ok=False, arm="x"), row("ok", arm="y")]
    out = R.summarize(rows, by="arm")
    assert out["groups"]["x"]["types"]["ok"]["n"] == 2 and out["groups"]["x"]["types"]["ok"]["failures"] == 1
    assert out["groups"]["y"]["types"]["ok"]["n"] == 1


def test_ledger_supplies_kind_and_status_for_p4_style_rows(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    write_rows(ledger, [
        {"run_id": "r1", "label": "t1", "kind": "ok", "status": "done", "ok": True},
        {"run_id": "r2", "label": "review:r1", "kind": None, "status": "done", "ok": True},   # a review run
        {"run_id": "v", "type": "verify", "verdict": "right"},                                # an event
        {"run_id": "r3", "label": "t2", "kind": "ok_self_checked", "status": "done", "ok": True},
    ])
    entries = R.read_ledger(ledger)
    rows = [{"arm": "a", "ok": False, "ccx_run_ids": ["r1", "r2"]},      # review run skipped: r1 is the receipt
            {"arm": "a", "ok": True, "ccx_run_ids": ["r3"]},
            {"arm": "a", "ok": True, "ccx_run_ids": []},                 # no delegation: not a receipt
            {"arm": "a", "ok": True, "ccx_run_ids": ["nope"]}]           # unknown run id
    out = R.summarize(rows, entries)
    assert (out["types"]["ok"]["failures"], out["types"]["ok"]["n"]) == (1, 1)
    assert (out["types"]["ok_self_checked"]["failures"], out["types"]["ok_self_checked"]["n"]) == (0, 1)
    assert out["no_receipt"] == 2


# ---- loading and the entry point ----

def test_load_rows_from_a_strength_directory(tmp_path):
    write_rows(tmp_path / "res" / "results.jsonl", [row("ok"), row("ok", ok=False)])
    assert len(R.load_rows(tmp_path / "res")) == 2
    write_rows(tmp_path / "f.jsonl", [row("ok")])
    assert len(R.load_rows(tmp_path / "f.jsonl")) == 1


def test_cli_json_and_text_are_read_only(tmp_path):
    src = tmp_path / "res" / "results.jsonl"
    write_rows(src, [row("ok") for _ in range(3)] + [row("ok", ok=False)])
    before = src.read_bytes()
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    run = lambda *a: subprocess.run([sys.executable, str(EVAL / "receipt_fp.py"), *map(str, a)], cwd=tmp_path,
                                    capture_output=True, text=True, encoding="utf-8", env=env, timeout=60)
    js = run(src.parent)
    assert js.returncode == 0, js.stderr
    t = json.loads(js.stdout)["types"]["ok"]
    assert (t["failures"], t["n"]) == (1, 4)
    txt = run(src.parent, "--text")
    assert txt.returncode == 0 and "ok" in txt.stdout and "1/4" in txt.stdout
    assert src.read_bytes() == before


def test_cli_fails_cleanly_on_missing_input(tmp_path):
    p = subprocess.run([sys.executable, str(EVAL / "receipt_fp.py"), str(tmp_path / "missing")], cwd=tmp_path,
                       capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert p.returncode == 2 and "Traceback" not in p.stderr
