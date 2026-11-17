"""Routing calibration (issue #429): synthetic ledgers only, no model CLI, no network, nothing outside tmp_path."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

EVAL = Path(__file__).resolve().parents[1] / "scripts/eval"
sys.path.insert(0, str(EVAL))
import routing_calibration as C

R1 = "codex:gpt-6.1-sol:low"


def write_jsonl(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8", newline="")
    return path


def run(rid, label="", b=None, usd=0.1, seconds=60.0, **extra):
    return {"run_id": rid, "label": label, "mode": "write", "kind": "ok", "ok": True, "rungs": [R1], "attempts": 1,
            "ae_usd": usd, "seconds": seconds, "b": b, **extra}


def verify(rid, ok, soft=False):
    return {"type": "verify", "run_id": rid, "ok": ok, **({"soft": True} if soft else {})}


def selfrun(ok=True, b=None, usd=0.5, seconds=30.0, **extra):
    return {"type": "selfrun", "ok": ok, "b": b, "ae_usd": usd, "seconds": seconds, **extra}


def many(prefix, n, ok_count, label="", **kw):
    """n delegated runs with a verdict, ok_count of them right."""
    rows = []
    for i in range(n):
        rid = f"{prefix}{i}"
        rows += [run(rid, label=label, **kw), verify(rid, i < ok_count)]
    return rows


def bucket(rep, stratum, signal, name):
    return next(b for b in rep["strata"][stratum]["signals"][signal]["buckets"] if b["bucket"] == name)


def test_wilson_and_newcombe_basics():
    lo, hi = C.newcombe(10, 10, 5, 10)
    assert lo > 0 and hi > 0.5 and hi <= 1.0           # 100% vs 50% on n=10: clearly positive but wide
    assert C.newcombe(0, 0, 1, 1) is None
    lo, hi = C.newcombe(5, 10, 5, 10)
    assert lo < 0 < hi                                  # equal rates: interval straddles 0


def test_buckets_both_arms_rates_cost_and_wallclock():
    rows = (many("d", 12, 9, b=2.5, usd=0.2, seconds=100)           # delegated, b 2-3: 9/12 right
            + [selfrun(ok=i < 11, b=2.4, usd=0.4, seconds=50) for i in range(12)])   # self: 11/12 right
    rep = C.calibrate(rows, min_n=10)
    b = bucket(rep, "real", "b", "2-3")
    assert b["delegated"]["right"]["k"] == 9 and b["delegated"]["right"]["n"] == 12
    assert b["self"]["right"]["k"] == 11 and b["self"]["right"]["n"] == 12
    lo, hi = b["self"]["right"]["ci95"]
    assert 0.6 < lo < 11 / 12 < hi < 1
    assert b["delegated"]["cost_usd"]["mean"] == pytest.approx(0.2)
    assert b["self"]["cost_usd"]["mean"] == pytest.approx(0.4)
    assert b["delegated"]["seconds"]["median"] == 100 and b["self"]["seconds"]["mean"] == 50
    assert b["delegated"]["cost_usd"]["usd_per_right"] == pytest.approx(12 * 0.2 / 9, abs=1e-3)
    assert b["self"]["outcome_source"] == {"selfrun_ok": 12}
    assert b["delegated"]["outcome_source"] == {"verify": 12}
    assert b["compare"]["verdict"] in ("self_not_worse", "unresolved")      # never delegate_better here
    assert b["compare"]["margin"] == 0.10


def test_small_sample_buckets_are_flagged_and_insufficient():
    rows = many("d", 4, 4, b=4.5) + [selfrun(b=4.4) for _ in range(3)]
    rep = C.calibrate(rows, min_n=10)
    b = bucket(rep, "real", "b", "4-5")
    assert b["compare"]["verdict"] == "insufficient"
    assert "small_sample_self" in b["flags"] and "small_sample_delegated" in b["flags"]
    t = rep["strata"]["real"]["signals"]["b"]["threshold"]
    assert t["self_ok_up_to"] is None and t["delegate_better_from"] is None and t["status"] == "undetermined"
    assert t["buckets_insufficient"] == ["4-5"]


def test_missing_signal_is_its_own_bucket_and_never_guessed():
    rows = many("d", 5, 5, b=None) + many("e", 5, 5, b=3.2)
    rep = C.calibrate(rows)
    assert bucket(rep, "real", "b", C.MISSING)["delegated"]["n"] == 5
    assert bucket(rep, "real", "b", "3-4")["delegated"]["n"] == 5
    assert rep["strata"]["real"]["with_signal"]["b"] == 5
    assert rep["strata"]["real"]["with_signal"]["files"] == 0
    # a bucket with no signal can never give a threshold
    assert rep["strata"]["real"]["signals"]["b"]["threshold"]["self_ok_up_to"] is None


def test_eval_and_real_are_separate_strata():
    rows = many("r", 3, 3, b=4.1) + many("e", 4, 2, label="eval-x", b=4.1)
    rep = C.calibrate(rows)
    assert bucket(rep, "real", "b", "4-5")["delegated"]["n"] == 3
    assert bucket(rep, "eval", "b", "4-5")["delegated"]["n"] == 4
    assert rep["strata"]["real"]["n_delegated"] == 3 and rep["strata"]["eval"]["n_delegated"] == 4


def test_outcome_rule_matches_replay_not_the_row_ok():
    rows = [run("a", b=2.1), run("b", b=2.1), verify("b", False), run("c", b=2.1), verify("c", True, soft=True),
            run("d", label="review:a", b=2.1), run("e", b=2.1), {"type": "dismiss", "run_id": "e"}]
    rep = C.calibrate(rows)
    d = bucket(rep, "real", "b", "2-3")["delegated"]
    # a: never judged; b: hard verify false; c: only probable (not counted); review run and dismissed run left out
    assert d["n"] == 3 and d["n_judged"] == 1 and d["right"]["k"] == 0
    assert rep["input"]["review_runs"] == 1 and rep["input"]["dismissed"] == 1
    assert C.calibrate(rows, include_probable=True)["strata"]["real"]["signals"]["b"]["buckets"][0][
        "delegated"]["n_judged"] == 2


def test_result_row_ok_wins_over_verify():
    rows = [run("a", label="t1", b=2.1), verify("a", True)]
    res = [{"label": "t1", "ok": False}]
    rep = C.calibrate(rows, results=res)
    assert bucket(rep, "real", "b", "2-3")["delegated"]["right"]["k"] == 0
    assert bucket(rep, "real", "b", "2-3")["delegated"]["outcome_source"] == {"result": 1}


def test_threshold_candidate_interval_from_ordered_buckets():
    # delegated far better at >=3; n = 20 per arm only shows non-inferiority within a wide margin
    rows = []
    for ok_self, ok_del, files in ((19, 18, 1), (18, 18, 2), (4, 19, 3)):
        sig = {"route": {"policy": {"signals": {"files": files}}}}
        rows += many(f"d{files}-", 20, ok_del, **sig)
        rows += [selfrun(ok=i < ok_self, **sig) for i in range(20)]
    tab = C.calibrate(rows, min_n=10, margin=0.30)["strata"]["real"]["signals"]["files"]
    t = tab["threshold"]
    assert [b["bucket"] for b in tab["buckets"]] == ["1", "2", ">=3"]
    # at the default 10-point margin the same data cannot show self_not_worse: unresolved, not guessed
    assert C.calibrate(rows, min_n=10)["strata"]["real"]["signals"]["files"]["threshold"]["self_ok_up_to"] is None
    assert t["self_ok_up_to"] == "2" and t["delegate_better_from"] == ">=3" and t["status"] == "partial"


def test_signals_from_run_json_and_band_and_rubric():
    run_json = {"route": {"b": 4.2, "policy": {"band": "large", "signals": {"minutes": 50, "files": 3}},
                          "rubric": {"coupling": "cross", "clarity": "goal"}}}
    rows = [run("x", b=None), verify("x", True)]
    rep = C.calibrate(rows, run_records={"x": run_json})
    for sig, name in (("b", "4-5"), ("minutes", ">=45"), ("files", ">=3"), ("band", "large"),
                      ("coupling", "cross"), ("clarity", "goal")):
        assert bucket(rep, "real", sig, name)["delegated"]["n"] == 1
    # the ledger row's own value is never overwritten by run.json
    rows = [run("y", b=1.0), verify("y", True)]
    assert bucket(C.calibrate(rows, run_records={"y": run_json}), "real", "b", "<2")["delegated"]["n"] == 1


def test_selfrun_without_ok_flag_is_not_judged():
    rep = C.calibrate([selfrun(ok=None, b=2.2), selfrun(ok=True, b=2.2)])
    s = bucket(rep, "real", "b", "2-3")["self"]
    assert s["n"] == 2 and s["n_judged"] == 1


def test_empty_ledger_is_all_unknown():
    rep = C.calibrate([])
    assert rep["strata"]["real"]["n_delegated"] == 0
    assert rep["strata"]["real"]["signals"]["b"]["buckets"] == []
    assert rep["strata"]["real"]["signals"]["b"]["threshold"]["status"] == "undetermined"


def test_cli_json_text_and_refuses_eval_codex_home(tmp_path):
    led = write_jsonl(tmp_path / "ledger.jsonl", many("d", 3, 2, b=2.5) + [selfrun(b=2.5)])
    script = str(EVAL / "routing_calibration.py")
    out = subprocess.run([sys.executable, script, "--ledger", str(led)], capture_output=True, text=True, check=True)
    assert json.loads(out.stdout)["strata"]["real"]["n_delegated"] == 3
    txt = subprocess.run([sys.executable, script, "--ledger", str(led), "--text"], capture_output=True, text=True,
                         check=True)
    assert "[b]" in txt.stdout and "limit:" in txt.stdout
    bad = tmp_path / "eval-codex-home"
    bad.mkdir()
    write_jsonl(bad / "ledger.jsonl", [])
    res = subprocess.run([sys.executable, script, "--ledger", str(bad / "ledger.jsonl")], capture_output=True, text=True)
    assert res.returncode != 0 and "eval-codex-home" in res.stderr
