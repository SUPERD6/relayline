"""Ledger replay (issue #380): synthetic ledgers only, no model CLI, no network, nothing outside tmp_path read."""
import json
import math
from pathlib import Path
import subprocess
import sys

import pytest

EVAL = Path(__file__).resolve().parents[1] / "scripts/eval"
sys.path.insert(0, str(EVAL))
import ledger_replay as L

R1, R2 = "codex:gpt-6.1-sol:low", "claude:opus-5.5:high"


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8", newline="")
    return path


def run(i, task="t1", rungs=(R1,), attempts=1, usd=0.10, **extra):
    return {"run_id": f"r{i}", "label": f"eval-x:{i}", "task": task, "mode": "write", "kind": "ok", "ok": True,
            "rungs": list(rungs), "attempts": attempts, "ae_usd": usd, **extra}


def verify(i, ok, soft=False):
    return {"type": "verify", "run_id": f"r{i}", "ok": ok, **({"soft": True} if soft else {})}


def cell(report, category, rung):
    return next(c for c in report["cells"] if c["category"] == category and c["first_rung"] == rung)


def replay(tmp_path, rows, **kw):
    kw.setdefault("by", "task")                 # the tests name their categories with `task`; auto is tested apart
    return L.replay(L.load_ledger(write_jsonl(tmp_path / "ledger.jsonl", rows)), **kw)


# ---- old ledgers: no first_rung, no p ----

def test_old_fields_first_rung_is_rungs_zero_and_rates_carry_n(tmp_path):
    rows = [run(i) for i in range(4)] + [verify(0, True), verify(1, True), verify(2, True), verify(3, False)]
    rep = replay(tmp_path, rows)
    c = cell(rep, "t1", R1)
    assert c["n"] == 4 and c["n_judged"] == 4
    assert c["ok_final"]["k"] == 3 and c["ok_final"]["rate"] == 0.75
    lo, hi = c["ok_final"]["ci95"]
    assert 0 < lo < 0.75 < hi < 1
    assert c["cost"]["mean_usd"] == pytest.approx(0.10) and c["cost"]["n_known"] == 4
    assert c["calibration"] is None                          # the ledger row keeps no p
    assert "small_sample" in c["flags"]                      # n < 10
    assert rep["input"]["first_rung_source"] == {"rungs[0]": 4}


def test_ledger_ok_field_is_not_the_outcome(tmp_path):
    rep = replay(tmp_path, [run(0), run(1), verify(1, False)])      # r0 never judged, r1's own ok is True
    c = cell(rep, "t1", R1)
    assert c["n"] == 2 and c["n_judged"] == 1 and c["ok_final"]["k"] == 0


def test_last_hard_verdict_wins_and_probable_is_excluded_by_default(tmp_path):
    rows = [run(0), run(1), run(2), verify(0, False), verify(0, True),
            verify(1, True, soft=True), verify(2, True, soft=True), verify(2, False)]
    rep = replay(tmp_path, rows)
    c = cell(rep, "t1", R1)
    assert c["n_judged"] == 2 and c["ok_final"]["k"] == 1            # r0 True (last), r2 False; r1 only probable
    assert rep["input"]["probable_only"] == 1
    rep2 = replay(tmp_path, rows, include_probable=True)
    assert cell(rep2, "t1", R1)["n_judged"] == 3


def test_escalated_run_is_right_finally_but_not_on_the_first_rung(tmp_path):
    rows = [run(0, rungs=(R1, R2), attempts=2), run(1), verify(0, True), verify(1, True)]
    c = cell(replay(tmp_path, rows), "t1", R1)
    assert c["ok_final"]["k"] == 2 and c["ok_first"]["k"] == 1


def test_missing_fields_do_not_crash(tmp_path):
    rows = [{"run_id": "a", "label": "x"}, {"run_id": "b", "rungs": [], "task": "t1"},
            {"run_id": "c", "rungs": [R1], "task": "t1", "attempts": None}, verify("a", True)]
    rep = replay(tmp_path, rows)
    assert rep["input"]["no_first_rung"] == 2
    c = cell(rep, "t1", R1)
    assert c["n"] == 1 and c["n_judged"] == 0 and c["ok_final"]["rate"] is None
    assert c["cost"]["mean_usd"] is None
    assert "no_judged_runs" in c["flags"]


def test_dismissed_and_nonrun_rows_are_left_out(tmp_path):
    rows = [run(0), run(1), verify(0, True), verify(1, True), {"type": "dismiss", "run_id": "r1"},
            {"type": "selfrun", "run_id": "s"}]
    rep = replay(tmp_path, rows)
    assert cell(rep, "t1", R1)["n"] == 1 and rep["input"]["dismissed"] == 1


def test_only_filter_splits_eval_from_real_use(tmp_path):
    real = {**run(1), "label": "fix the parser"}
    rows = [run(0), real, verify(0, True), verify(1, True)]
    assert cell(replay(tmp_path, rows, only="eval"), "t1", R1)["n"] == 1
    assert cell(replay(tmp_path, rows, only="real"), "t1", R1)["n"] == 1
    assert cell(replay(tmp_path, rows, only="all"), "t1", R1)["n"] == 2


def test_category_fallback_chain(tmp_path):
    rows = [run(0, task=None, category="cat"), run(1, task=None, role="build"), run(2, task=None, mode="read"),
            run(3, task=None, mode=None)]
    cats = {c["category"] for c in replay(tmp_path, rows, by="auto")["cells"]}
    assert cats == {"cat", "role:build", "mode:read", "unknown"}


def test_auto_does_not_cut_by_task(tmp_path):
    rows = [run(0, task="x1", mode="write"), run(1, task="x2", mode="write")]
    assert [c["category"] for c in replay(tmp_path, rows, by="auto")["cells"]] == ["mode:write"]
    assert {c["category"] for c in replay(tmp_path, rows, by="task")["cells"]} == {"x1", "x2"}


# ---- new fields (#379): planned_first_rung / actual_first_rung / rung_why ----

def test_new_fields_win_over_rungs_and_planned_difference_is_counted(tmp_path):
    rows = [run(0, rungs=(R2,), planned_first_rung=R1, actual_first_rung=R2, rung_why={"first_rung": R2}),
            run(1, rungs=(R1,), planned_first_rung=R1, actual_first_rung=R1), verify(0, True), verify(1, True)]
    rep = replay(tmp_path, rows)
    assert cell(rep, "t1", R2)["n"] == 1 and cell(rep, "t1", R1)["n"] == 1
    assert rep["input"]["first_rung_source"] == {"actual_first_rung": 2}
    assert rep["input"]["planned_differs"] == 1 and rep["input"]["planned_known"] == 2


def test_actual_first_rung_null_falls_back_to_first_rung_then_rungs(tmp_path):
    rows = [run(0, rungs=(R1,), actual_first_rung=None, first_rung=R2), run(1, rungs=(R1,), actual_first_rung=None)]
    src = replay(tmp_path, rows)["input"]["first_rung_source"]
    assert src == {"first_rung": 1, "rungs[0]": 1}


def test_cheap_first_dispatch_first_rung_is_used_when_nothing_newer(tmp_path):
    rows = [run(0, rungs=(R1,), dispatch={"cheap_first": True, "first_rung": R2})]
    assert replay(tmp_path, rows)["input"]["first_rung_source"] == {"dispatch.first_rung": 1}


# ---- calibration: p from the row or its run.json ----

def test_calibration_uses_p_of_the_actual_first_rung(tmp_path):
    rows = [run(i, route={"p": 0.8, "chain_p": 0.9, "rung": R1}) for i in range(5)]
    rows += [verify(i, i != 0) for i in range(5)]               # 4 of 5 right on the first rung
    cal = cell(replay(tmp_path, rows), "t1", R1)["calibration"]
    assert cal["n"] == 5 and cal["mean_p"] == pytest.approx(0.8) and cal["actual"] == pytest.approx(0.8)
    assert cal["gap"] == pytest.approx(0.0)
    assert cal["brier"] == pytest.approx((4 * 0.04 + 0.64) / 5)
    assert cal["chain"]["mean_p"] == pytest.approx(0.9)


def test_p_of_another_rung_is_not_used(tmp_path):
    # routing picked R1 (p=.9) but the run started on R2: that p says nothing about R2
    rows = [run(0, rungs=(R2,), route={"p": 0.9, "rung": R1}, planned_first_rung=R1, actual_first_rung=R2),
            run(1, rungs=(R2,), route={"p": 0.7}), verify(0, True), verify(1, True)]
    rep = replay(tmp_path, rows)
    assert cell(rep, "t1", R2)["calibration"] is None
    assert rep["input"]["p_other_rung_judged"] == 1 and rep["input"]["p_rung_unknown_judged"] == 1


def test_run_json_enriches_old_rows(tmp_path):
    runs = tmp_path / "runs"
    for i in range(3):
        d = runs / f"r{i}"
        d.mkdir(parents=True)
        (d / "run.json").write_text(json.dumps({"run_id": f"r{i}", "first_rung": R1,
                                                "route": {"p": 0.6, "chain_p": 0.7, "rung": R1}}), encoding="utf-8")
    (runs / "bad").mkdir()
    (runs / "bad" / "run.json").write_text("{not json", encoding="utf-8")
    rows = [{k: v for k, v in run(i).items() if k != "rungs"} for i in range(3)] + [verify(i, True) for i in range(3)]
    rep = replay(tmp_path, rows, run_records=L.load_runs(runs))
    c = cell(rep, "t1", R1)
    assert rep["input"]["first_rung_source"] == {"first_rung": 3} and rep["input"]["run_json_matched"] == 3
    assert c["calibration"]["n"] == 3 and c["calibration"]["mean_p"] == pytest.approx(0.6)


def test_overall_calibration_pools_all_cells(tmp_path):
    rows = [run(0, route={"p": 0.9, "rung": R1}), run(1, rungs=(R2,), route={"p": 0.5, "rung": R2}),
            verify(0, True), verify(1, False)]
    ov = replay(tmp_path, rows)["calibration_overall"]
    assert ov["n"] == 2 and ov["mean_p"] == pytest.approx(0.7) and ov["actual"] == pytest.approx(0.5)


# ---- result rows ----

def test_result_rows_give_the_outcome_by_label_and_win_over_verify(tmp_path):
    rows = [run(0), run(1), run(2), verify(0, False)]
    results = [{"label": "eval-x:0", "ok": True}, {"label": "eval-x:1", "ok": False},
               {"label": "eval-x:2", "ok": None}, {"label": "eval-x:99", "ok": True}]
    rep = replay(tmp_path, rows, results=L.index_results(results))
    c = cell(rep, "t1", R1)
    assert c["n_judged"] == 2 and c["ok_final"]["k"] == 1            # r0 from the result row (True), r1 False
    assert rep["input"]["results_unmatched"] == 1
    assert rep["input"]["outcome_source"] == {"result": 2}


def test_result_rows_with_environment_faults_are_not_outcomes(tmp_path):
    rows = [run(i) for i in range(6)] + [verify(5, True)]
    results = [{"label": "eval-x:0", "ok": False, "error": "timeout"},
               {"label": "eval-x:1", "ok": False, "invalid": True},
               {"label": "eval-x:2", "ok": False, "environment_error": True},
               {"label": "eval-x:3", "ok": False, "status": "error"},
               {"label": "eval-x:4", "ok": False, "invalid": False},
               {"label": "eval-x:5", "ok": False, "receipt_error": True}]
    rep = replay(tmp_path, rows, results=L.index_results(results))
    c = cell(rep, "t1", R1)
    assert rep["input"]["results_unscorable"] == 5
    assert c["n_judged"] == 2 and c["ok_final"]["k"] == 1            # r4 scored wrong; r5 falls back to its verdict
    assert rep["input"]["outcome_source"] == {"result": 1, "verify": 1}


def test_result_rows_link_by_ccx_run_ids_and_count_only_once(tmp_path):
    rows = [run(0, label="eval-x:u1"), run(1, label="eval-x:u1"), run(2, label="review:r1"),
            run(3, label="eval-x:u2")]
    results = [{"label": "u1-unit", "ok": True, "ccx_run_ids": ["r0", "r1", "r2"]},   # resumed unit + its review run
               {"label": "other", "ok": False, "run_id": "r3"},
               {"label": "ghost", "ok": True, "ccx_run_ids": ["nope"]}]
    rep = replay(tmp_path, rows, results=L.index_results(results))
    c = cell(rep, "t1", R1)
    assert c["n"] == 4 and c["n_judged"] == 2 and c["ok_final"]["k"] == 1     # r1 (last) right, r3 wrong
    assert rep["input"]["results_multi_run"] == 1 and rep["input"]["results_unmatched"] == 1


def test_same_label_runs_get_the_result_once(tmp_path):
    rows = [run(0, label="eval-x:u"), run(1, label="eval-x:u")]
    rep = replay(tmp_path, rows, results=L.index_results([{"label": "eval-x:u", "ok": True}]))
    assert cell(rep, "t1", R1)["n_judged"] == 1 and rep["input"]["results_multi_run"] == 1


# ---- attempts ----

def test_attempts_list_from_run_json_counts_its_length(tmp_path):
    runs = tmp_path / "runs"
    for i, atts in enumerate(([{}, {}], [{}], [])):
        d = runs / f"r{i}"
        d.mkdir(parents=True)
        (d / "run.json").write_text(json.dumps({"run_id": f"r{i}", "attempts": atts}), encoding="utf-8")
    rows = [{k: v for k, v in run(i).items() if k != "attempts"} for i in range(3)]
    rows.append({k: v for k, v in run(3, rungs=(R1, R2)).items() if k != "attempts"})        # no run.json: len(rungs)
    rows += [verify(i, True) for i in range(4)]
    c = cell(replay(tmp_path, rows, run_records=L.load_runs(runs)), "t1", R1)
    assert c["ok_final"]["k"] == 4 and c["ok_first"]["k"] == 2         # r0 two attempts, r3 two rungs: not first-rung


def test_attempts_helper():
    assert L._attempts({"attempts": [1, 2, 3]}) == 3 and L._attempts({"attempts": []}) == 1
    assert L._attempts({"attempts": 2}) == 2 and L._attempts({"rungs": ["a", "b"]}) == 2
    assert L._attempts({}) == 1 and L._attempts({"attempts": True, "rungs": ["a"]}) == 1


def test_route_rung_wins_over_planned_for_the_pick(tmp_path):
    rows = [run(0, route={"p": 0.9, "rung": R1}, planned_first_rung=R2), verify(0, True)]
    assert cell(replay(tmp_path, rows), "t1", R1)["calibration"]["n"] == 1


def test_calibration_small_sample_follows_min_n(tmp_path):
    rows = [run(i, route={"p": 0.8, "rung": R1}) for i in range(4)] + [verify(i, True) for i in range(4)]
    assert cell(replay(tmp_path, rows, min_n=3), "t1", R1)["calibration"]["flags"] == []
    assert cell(replay(tmp_path, rows, min_n=5), "t1", R1)["calibration"]["flags"] == ["small_sample"]


def test_planned_counts_cover_all_kept_rows_not_only_judged(tmp_path):
    rows = [run(0, planned_first_rung=R2, actual_first_rung=R1)]               # not judged
    inp = replay(tmp_path, rows)["input"]
    assert inp["planned_known"] == 1 and inp["planned_differs"] == 1


# ---- candidate rule ----

def rule_rows(tmp_path):
    rows = []
    for i in range(10):                                              # A on R1: 10 runs, 6 right, $0.10
        rows.append(run(i, task="A", usd=0.10))
    for i in range(10, 20):                                          # A on R2: 10 runs, 9 right, $0.40
        rows.append(run(i, task="A", rungs=(R2,), usd=0.40))
    for i in range(20, 30):                                          # B on R1 only: 10 runs, 2 right
        rows.append(run(i, task="B", usd=0.10))
    for i in range(30, 33):                                          # C on R2: 3 runs (too few)
        rows.append(run(i, task="C", rungs=(R2,), usd=0.40))
    ok = [i < 6 for i in range(10)] + [i < 9 for i in range(10)] + [i < 2 for i in range(10)] + [True] * 3
    return rows + [verify(i, o) for i, o in enumerate(ok)]


def test_rule_estimates_only_where_history_supports_it(tmp_path):
    rule = {"name": "A->R2, B->R1, C->R2", "by_category": {"A": R2, "B": R1, "C": R2}}
    rep = replay(tmp_path, rule_rows(tmp_path), rule=rule)
    r = rep["rule"]
    cats = {c["category"]: c for c in r["categories"]}
    assert cats["A"]["supported"] and cats["A"]["est_ok_final"] == pytest.approx(0.9)
    assert cats["A"]["est_cost_usd"] == pytest.approx(0.40) and cats["A"]["cell_n"] == 10
    assert not cats["C"]["supported"] and "n=3" in cats["C"]["reason"]
    assert r["coverage"]["supported_runs"] == 30 and r["coverage"]["total_runs"] == 33
    assert r["est_ok_final"] == pytest.approx((0.9 * 20 + 0.2 * 10) / 30, abs=1e-3)
    assert r["est_cost_per_run_usd"] == pytest.approx((0.4 * 20 + 0.1 * 10) / 30, abs=1e-3)
    base = r["history_same_categories"]                              # what history actually did there
    assert base["n"] == 30 and base["ok_final"] == pytest.approx((6 + 9 + 2) / 30, abs=1e-3)
    assert any("not randomized" in s for s in r["caveats"])
    lo, hi = cats["A"]["est_ci95"]
    assert lo == pytest.approx(L.wilson(9, 10)[0], abs=1e-3) and hi == pytest.approx(L.wilson(9, 10)[1], abs=1e-3)
    assert r["categories_without_history"] == []
    assert "est_ci95" not in cats["C"]


def test_rule_ten_of_ten_still_has_a_wide_interval_and_lists_unknown_categories(tmp_path):
    rows = [run(i, task="A") for i in range(10)] + [verify(i, True) for i in range(10)]
    rep = replay(tmp_path, rows, rule={"by_category": {"A": R1, "Z": R2}})
    a = rep["rule"]["categories"][0]
    assert a["est_ok_final"] == 1.0 and a["est_ci95"][0] == pytest.approx(0.7225, abs=1e-3)
    assert rep["rule"]["categories_without_history"] == ["Z"]
    assert "72%" in L.text(rep) and "Z" in L.text(rep)


def test_rule_cost_is_over_the_judged_runs_like_the_rate(tmp_path):
    rows = [run(i, usd=0.1) for i in range(10)] + [run(10, usd=5.0)] + [verify(i, True) for i in range(10)]
    rep = replay(tmp_path, rows, rule={"default": R1})
    c = cell(rep, "t1", R1)
    assert c["cost"]["judged_mean_usd"] == pytest.approx(0.1) and c["cost"]["mean_usd"] > 0.4
    assert rep["rule"]["categories"][0]["est_cost_usd"] == pytest.approx(0.1)


def test_rule_default_and_missing_rung(tmp_path):
    rep = replay(tmp_path, rule_rows(tmp_path), rule={"default": R1})
    cats = {c["category"]: c for c in rep["rule"]["categories"]}
    assert cats["A"]["est_ok_final"] == pytest.approx(0.6) and cats["B"]["supported"]
    assert not cats["C"]["supported"] and "no history" in cats["C"]["reason"]
    rep = replay(tmp_path, rule_rows(tmp_path), rule={"by_category": {"A": R2}})
    cats = {c["category"]: c for c in rep["rule"]["categories"]}
    assert not cats["B"]["supported"] and "no rule" in cats["B"]["reason"]


def test_rule_with_no_supported_category_says_unknown(tmp_path):
    rep = replay(tmp_path, rule_rows(tmp_path), rule={"default": "codex:nope:low"})
    r = rep["rule"]
    assert r["est_ok_final"] is None and r["est_cost_per_run_usd"] is None and r["coverage"]["supported_runs"] == 0


def test_rule_validation():
    for bad in ({}, {"default": 3}, {"by_category": []}, {"by_category": {"A": ""}}, []):
        with pytest.raises(ValueError):
            L.check_rule(bad)


# ---- statistics ----

def test_wilson_interval():
    lo, hi = L.wilson(8, 10)
    assert lo == pytest.approx(0.4902, abs=1e-3) and hi == pytest.approx(0.9433, abs=1e-3)
    assert L.wilson(0, 0) is None
    assert L.wilson(0, 5)[0] == pytest.approx(0.0, abs=1e-12) and L.wilson(5, 5)[1] == pytest.approx(1.0)
    assert math.isfinite(L.wilson(1, 1)[0])


# ---- command line ----

def cli(*args):
    return subprocess.run([sys.executable, str(EVAL / "ledger_replay.py"), *map(str, args)], capture_output=True,
                          text=True, encoding="utf-8")


def test_cli_json_and_text_and_nothing_written(tmp_path):
    led = write_jsonl(tmp_path / "ccx" / "ledger.jsonl", [run(0), verify(0, True)])
    before = sorted(p.name for p in tmp_path.rglob("*"))
    out = cli("--ledger", led)
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout)["cells"][0]["first_rung"] == R1
    txt = cli("--hub", tmp_path, "--text")
    assert txt.returncode == 0 and R1 in txt.stdout and "n=" in txt.stdout
    assert sorted(p.name for p in tmp_path.rglob("*")) == before


def test_cli_rule_file_and_literal_json(tmp_path):
    led = write_jsonl(tmp_path / "l.jsonl", rule_rows(tmp_path))
    rf = tmp_path / "rule.json"
    rf.write_text(json.dumps({"default": R1}), encoding="utf-8")
    assert json.loads(cli("--ledger", led, "--rule", rf).stdout)["rule"]["rule"] == {"default": R1}
    assert json.loads(cli("--ledger", led, "--rule", json.dumps({"default": R2})).stdout)["rule"]["coverage"]


def test_cli_refuses_a_link_into_the_eval_codex_home(tmp_path):
    target = tmp_path / "eval-codex-home"
    write_jsonl(target / "ledger.jsonl", [run(0)])
    link = tmp_path / "innocent"
    try:
        link.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are not available here")
    out = cli("--ledger", link / "ledger.jsonl")
    assert out.returncode != 0 and "eval-codex-home" in out.stderr


def test_cli_refuses_the_eval_codex_home_and_missing_input(tmp_path):
    bad = tmp_path / ".ccx" / "eval-codex-home" / "ledger.jsonl"
    write_jsonl(bad, [run(0)])
    out = cli("--ledger", bad)
    assert out.returncode != 0 and "eval-codex-home" in out.stderr
    out = cli("--ledger", tmp_path / "none.jsonl")
    assert out.returncode != 0 and "not found" in out.stderr
    out = cli("--ledger", write_jsonl(tmp_path / "ok.jsonl", [run(0)]), "--runs", bad.parent)
    assert out.returncode != 0 and "eval-codex-home" in out.stderr
