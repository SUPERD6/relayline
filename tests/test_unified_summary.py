"""Synthetic retained results only: no real model CLI or evaluation execution."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

EVAL = Path(__file__).resolve().parents[1] / "scripts/eval"
sys.path.insert(0, str(EVAL))
import unified_summary as U


def write_rows(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8", newline="")


def run_cli(tmp_path, *args):
    # Invoke the real entry point from outside the repository.
    return subprocess.run([sys.executable, str(EVAL / "unified_summary.py"), *map(str, args)],
                          cwd=tmp_path, capture_output=True, text=True, encoding="utf-8",
                          env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}, timeout=30)


def test_strength_valid_costs_and_zero_successes():
    rows = [{"arm": "on", "ok": True, "usd": 1},
            {"arm": "on", "ok": False, "usd": 2},
            {"arm": "on", "ok": True, "usd": 3, "error": "interrupted"},
            {"arm": "on", "ok": None, "usd": 4},
            {"arm": "off", "ok": False, "usd": .5}]
    result = U.strength(rows)
    assert result["valid_definition"] == U.VALID_DEFINITION
    assert result["successes_definition"] == "valid rows with ok true"
    assert result["arms"]["on"] == {"attempted": 4, "valid": 2, "successes": 1,
                                    "total_usd": 10, "known_total_usd": 10,
                                    "cost_unknown": 0, "usd_per_success": 10}
    assert result["arms"]["off"] == {"attempted": 1, "valid": 1, "successes": 0,
                                     "total_usd": .5, "known_total_usd": .5,
                                     "cost_unknown": 0, "usd_per_success": None}


def test_strength_receipt_status_error_is_invalid_not_a_failure():
    """Issue #321: a ccx receipt with status error (e.g. kind=auth, a 401) is Unknown, not a task done wrong."""
    rows = [{"task": "t", "agent": "codex", "rep": 1, "arm": "on", "ok": False, "usd": 0.0,
             "status": "error", "kind": "auth"},
            {"task": "t", "agent": "codex", "rep": 1, "arm": "off", "ok": True, "usd": .1, "status": "done"},
            {"task": "t", "agent": "codex", "rep": 2, "arm": "on", "ok": False, "usd": .1, "status": "done"},
            {"task": "t", "agent": "codex", "rep": 2, "arm": "off", "ok": False, "usd": .1}]
    assert not U.valid(rows[0]) and U.valid(rows[1]) and U.valid(rows[3])
    assert '"error"' in U.VALID_DEFINITION and "status" in U.VALID_DEFINITION
    result = U.strength(rows, pair=("on", "off"))
    assert result["arms"]["on"]["attempted"] == 2 and result["arms"]["on"]["valid"] == 1
    assert result["arms"]["on"]["total_usd"] == .1            # its cost still counts
    assert result["pair"]["n_pairs"] == 1 and (result["pair"]["b"], result["pair"]["c"]) == (0, 0)


@pytest.mark.parametrize("cost", [None, True, "1", -1, float("nan"), float("inf")])
def test_strength_unknown_cost_is_not_zero_or_valid(cost):
    result = U.strength([{"arm": "mem", "ok": True, "usd": cost},
                         {"arm": "mem", "ok": True, "usd": .2}])["arms"]["mem"]
    assert result == {"attempted": 2, "valid": 1, "successes": 1, "cost_unknown": 1,
                      "total_usd": None, "known_total_usd": .2, "usd_per_success": None}


def test_strength_pairs_agent_keys_and_invalid_side_excluded():
    rows = []
    for rep in range(1, 7):
        for arm in ("off", "on"):
            rows.append({"task": "t1-empty-mean", "agent": "codex", "rep": rep,
                         "arm": arm, "ok": arm == "off", "usd": .1})
    # Repeated task/rep across agents must remain distinct pairs.
    rows += [{"task": "t1-empty-mean", "agent": "dsh", "rep": 1,
              "arm": arm, "ok": True, "usd": .1} for arm in ("off", "on")]
    for rep, bad in ((8, {"ok": None}), (9, {"error": "Error"}), (10, {"usd": None})):
        for arm in ("off", "on"):
            rows.append({"task": "t1-empty-mean", "agent": "codex", "rep": rep, "arm": arm,
                         "ok": arm == "on", "usd": .2, **(bad if arm == "off" else {})})
    rows.append({"task": "t1-empty-mean", "agent": "codex", "rep": 11, "arm": "off", "ok": True, "usd": .1})
    pair = U.strength(rows, ("off", "on"))["pair"]
    assert pair == {"a": "off", "b_arm": "on", "keys": ["task", "agent", "rep"],
                    "n_pairs": 7, "b": 6, "c": 0, "mcnemar_p": .03125, "usd_per_success_ratio": None}
    reverse = U.strength(rows, ("on", "off"))["pair"]
    assert (reverse["b"], reverse["c"], reverse["mcnemar_p"]) == (0, 6, .03125)


def test_strength_pairs_without_agent_and_no_discordance():
    rows = [{"arm": arm, "task": "memory-case", "rep": 1, "ok": True, "usd": 0} for arm in ("nomem", "hubstart")]
    pair = U.strength(rows, ("nomem", "hubstart"))["pair"]
    assert pair["keys"] == ["task", "rep"] and pair["n_pairs"] == 1
    assert (pair["b"], pair["c"], pair["mcnemar_p"]) == (0, 0, None)
    assert U.strength(rows[:1], ("nomem", "hubstart"))["pair"]["n_pairs"] == 0
    with pytest.raises(ValueError, match="duplicate"):
        U.strength(rows + rows[:1], ("nomem", "hubstart"))
    with pytest.raises(ValueError, match="missing pairing key"):
        U.strength(rows + [{**rows[0], "agent": "codex", "rep": 2}], ("nomem", "hubstart"))


def test_settled_reuses_existing_tasks_not_scenario_or_unknown_ids():
    rows = [{"task": task["id"], "scenario": "favourable", "arm": "on", "ok": True, "usd": 1} for task in U.TASKS]
    rows.append({"task": "unregistered", "arm": "on", "ok": True, "usd": 10})
    result = U.strength(rows, subset="settled")
    assert result["subset"] == "settled"
    assert result["arms"]["on"]["attempted"] == 6
    assert result["arms"]["on"]["total_usd"] == 6


def test_strength_cli_json_text_report_fallback_and_read_only(tmp_path):
    out = tmp_path / "strength"
    rows = [{"arm": "mem", "task": "memory", "rep": 1, "ok": False, "usd": 1},
            {"arm": "nomem", "task": "memory", "rep": 1, "ok": True, "usd": 2}]
    write_rows(out / "results.jsonl", rows)
    (out / "report.json").write_text(json.dumps({"rows": []}), encoding="utf-8")
    before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in out.iterdir()}
    result = run_cli(tmp_path, "strength", out, "--pair", "nomem,mem")
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["pair"]["n_pairs"] == 1 and data["pair"]["b"] == 1
    assert data["arms"]["mem"]["usd_per_success"] is None
    text = run_cli(tmp_path, "--text", "strength", out, "--pair", "nomem,mem")
    assert text.returncode == 0, text.stderr
    assert "valid = no error" in text.stdout and "usd_per_success" in text.stdout
    assert "null" in text.stdout and "mcnemar_p" in text.stdout and "pair keys = task, rep" in text.stdout
    assert before == {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in out.iterdir()}
    fallback = tmp_path / "fallback"
    fallback.mkdir()
    (fallback / "report.json").write_text(json.dumps({"rows": rows}), encoding="utf-8")
    result = run_cli(tmp_path, "strength", fallback)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["arms"] == data["arms"]


def p4_row(arm, cost, wall, clean=True, ok=True, **extra):
    return {"arm": arm, "tag": "synthetic", "round": 1, "episode": 1, "task": "case", "ok": ok,
            "usd": cost, "known_usd": cost or 0, "cost_complete": cost is not None,
            "wall_s": wall, "env_clean": clean, **extra}


def test_p4_arbitrary_pair_all_clean_and_ratios_reuse_p4():
    rows = [p4_row("alpha", 2, 10), p4_row("alpha", 4, 30, False, False),
            p4_row("beta", 1, 20), p4_row("beta", None, None, False, False, known_usd=.5),
            p4_row("self", 1000, 500), p4_row("beta", 1000, 500, tag="other")]
    result = U.p4(rows, "synthetic", ("alpha", "beta"))
    assert result["ratio_direction"] == "B/A"
    a, b = (result["all"]["arms"][arm] for arm in ("alpha", "beta"))
    assert a == {"attempted": 2, "env_clean": 1, "right": 1, "cost_known_usd": 6,
                 "cost_unknown": 0, "wall_median_s": 20, "valid": 2}
    assert b == {"attempted": 2, "env_clean": 1, "right": 1, "cost_known_usd": 1.5,
                 "cost_unknown": 1, "wall_median_s": 20, "valid": 1}
    for arm in ("alpha", "beta"):
        existing = U.P4.summary([r for r in rows if r["tag"] == "synthetic"], 2)["all"]["arms"][arm]
        assert all(result["all"]["arms"][arm][key] == existing[key] for key in existing if key in a)
    assert result["all"]["ratios"] == {
        "cost": {"numerator": 1.5, "denominator": 6, "ratio": .25},
        "wall_median": {"numerator": 20, "denominator": 20, "ratio": 1}}
    assert result["env_clean"]["arms"]["beta"]["cost_unknown"] == 0
    assert result["env_clean"]["arms"]["alpha"]["attempted"] == 1
    assert result["env_clean"]["ratios"]["cost"]["ratio"] == .5
    assert result["env_clean"]["ratios"]["wall_median"]["ratio"] == 2
    reverse = U.p4(rows, "synthetic", ("beta", "alpha"))
    assert reverse["all"]["ratios"]["cost"]["ratio"] == 4


def test_p4_empty_and_zero_denominators(tmp_path):
    rows = [p4_row("a", 0, 0)]
    with pytest.raises(ValueError, match="arm='b'"):
        U.p4(rows, "synthetic", ("a", "b"))
    write_rows(tmp_path / "results.jsonl", rows)
    missing = run_cli(tmp_path, "p4", "--tag", "synthetic", "--out", tmp_path, "--pair", "a,b")
    assert missing.returncode == 2 and "arm='b'" in missing.stderr
    result = U.p4(rows + [p4_row("b", 0, 0)], "synthetic", ("a", "b"))
    assert all(value["ratio"] is None for value in result["all"]["ratios"].values())


def test_p4_dispatch_metrics_and_stop_reason_by_subset(tmp_path):
    arm = U.P4.DE.ARM
    def dispatch(escalated):
        return [{"dispatch": {"cheap_first": True, "attempted": 1, "escalated": escalated,
                               "first_usd": .1, "escalation_usd": .2 if escalated else 0}}]
    rows = [p4_row("ccxlongcheap", 2, 10),
            p4_row(arm, 1, 20, side_ledger=dispatch(0), dispatch_observed=True),
            p4_row(arm, 1, 40, False, side_ledger=dispatch(1), dispatch_observed=True)]
    out = tmp_path / "p4"
    write_rows(out / "results.jsonl", rows)
    before = (out / "results.jsonl").read_bytes()
    result = run_cli(tmp_path, "p4", "--tag", "synthetic", "--out", out, "--pair", f"ccxlongcheap,{arm}")
    assert result.returncode == 0, result.stderr
    result = json.loads(result.stdout)
    dispatch_all = result["all"]["arms"][arm]["dispatch"]
    assert dispatch_all == {"attempted": 2, "escalated": 1, "escalation_rate": .5,
                            "first_usd": .2, "escalation_usd": .2, "status": "Pass",
                            "stop_reason": "escalation_rate_above_30_percent"}
    assert result["env_clean"]["arms"][arm]["dispatch"]["escalation_rate"] == 0
    assert result["env_clean"]["arms"][arm]["dispatch"]["stop_reason"] is None
    text = run_cli(tmp_path, "p4", "--tag", "synthetic", "--out", out / "results.jsonl",
                   "--pair", f"ccxlongcheap,{arm}", "--text")
    assert text.returncode == 0, text.stderr
    assert all(label in text.stdout for label in ("all", "env_clean", "cost_known_usd", "wall_median_s",
                                                  "B/A", "escalated", "escalation_rate", "stop_reason"))
    assert (out / "results.jsonl").read_bytes() == before
    incomplete = [p4_row(arm, None, None)]
    write_rows(out / "results.jsonl", incomplete)
    missing = run_cli(tmp_path, "p4", "--tag", "synthetic", "--out", out, "--pair", f"self,{arm}")
    assert missing.returncode == 2 and "arm='self'" in missing.stderr
    unknown = U.p4([p4_row("self", 1, 1), *incomplete], "synthetic", ("self", arm))["all"]["arms"][arm]["dispatch"]
    assert unknown["status"] == "Unknown" and unknown["escalation_rate"] is None
    assert unknown["stop_reason"] == "dispatch_evidence_unknown"


def test_p4_default_input_matches_existing_parser():
    assert U.P4.parser().get_default("out") == EVAL.parents[1] / ".ccx/eval/p4/results.jsonl"


def test_no_subprocess_in_readers_or_summary(tmp_path, monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        pytest.fail("read-only summary must not start a process")
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    write_rows(tmp_path / "results.jsonl", [{"arm": "on", "ok": False, "usd": 0}])
    assert U.main(["strength", str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out)["arms"]["on"]["valid"] == 1
    write_rows(tmp_path / "results.jsonl", [p4_row("a", 1, 2)])
    with pytest.raises(SystemExit) as missing:
        U.main(["p4", "--tag", "synthetic", "--out", str(tmp_path), "--pair", "a,b"])
    assert missing.value.code == 2
    assert "arm='b'" in capsys.readouterr().err
    write_rows(tmp_path / "results.jsonl", [p4_row("a", 1, 2), p4_row("b", 1, 2)])
    assert U.main(["p4", "--tag", "synthetic", "--out", str(tmp_path), "--pair", "a,b"]) == 0
    assert json.loads(capsys.readouterr().out)["all"]["arms"]["a"]["attempted"] == 1


@pytest.mark.parametrize("pair", ["one", "same,same", "a,b,c", ",b"])
def test_bad_pair_cli_fails_without_reading_inputs(tmp_path, pair):
    result = run_cli(tmp_path, "strength", "missing", "--pair", pair)
    assert result.returncode == 2 and "two distinct nonempty arms" in result.stderr


def test_malformed_or_missing_input_is_not_an_empty_success(tmp_path):
    assert run_cli(tmp_path, "strength", tmp_path / "missing").returncode == 2
    (tmp_path / "results.jsonl").write_text('{"arm":', encoding="utf-8")
    assert run_cli(tmp_path, "strength", tmp_path).returncode == 2
    write_rows(tmp_path / "results.jsonl", [{"arm": "on", "ok": "Unknown", "usd": 0}])
    result = run_cli(tmp_path, "strength", tmp_path)
    assert result.returncode == 2 and "bool or null" in result.stderr


@pytest.mark.parametrize("a_ok,b_ok,a_usd,b_usd,expected", [
    (True, True, 2, 4, .5),
    (True, True, 0, 4, 0),
    (True, True, 2, 0, None),
    (False, True, 2, 4, None),
    (True, False, 2, 4, None),
    (True, True, None, 4, None),
    (True, True, 2, None, None),
])
def test_review_strength_cost_ratio_direction_and_nulls(a_ok, b_ok, a_usd, b_usd, expected):
    rows = [{"arm": "on", "task": "case", "rep": 1, "ok": a_ok, "usd": a_usd},
            {"arm": "off", "task": "case", "rep": 1, "ok": b_ok, "usd": b_usd}]
    result = U.strength(rows, ("on", "off"))
    assert result["pair"]["usd_per_success_ratio"] == expected
    assert "usd_per_success_ratio" in U.text_report(result)
    if expected == .5:
        assert U.strength(rows, ("off", "on"))["pair"]["usd_per_success_ratio"] == 2


def test_review_u2028_inside_json_string_is_not_a_record_boundary(tmp_path):
    rows = [{"arm": arm, "task": "name\u2028continued", "rep": 1, "ok": True, "usd": 1}
            for arm in ("on", "off")]
    path = tmp_path / "results.jsonl"
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                    encoding="utf-8", newline="")
    before = path.read_bytes()
    assert U.read_rows(path) == rows
    result = run_cli(tmp_path, "strength", tmp_path, "--pair", "on,off")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["pair"]["n_pairs"] == 1
    assert path.read_bytes() == before


def test_review_settled_with_pair_cli(tmp_path):
    rows = [{"task": task["id"], "agent": "codex", "rep": 1, "arm": arm,
             "ok": arm == "on", "usd": 1}
            for task in U.TASKS for arm in ("on", "off")]
    write_rows(tmp_path / "results.jsonl", rows)
    result = run_cli(tmp_path, "strength", tmp_path, "--pair", "on,off", "--subset", "settled")
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    expected = sum(not task["neutral"] for task in U.TASKS)
    assert data["subset"] == "settled"
    assert data["pair"]["n_pairs"] == expected
    assert (data["pair"]["b"], data["pair"]["c"]) == (expected, 0)
    assert data["pair"]["usd_per_success_ratio"] is None
    assert all(group["attempted"] == expected for group in data["arms"].values())


def test_review_p4_valid_all_clean_json_and_text(tmp_path):
    rows = [p4_row("a", 1, 1), p4_row("a", 1, 1, error="interrupted"),
            p4_row("a", 1, 1, ok=None), p4_row("a", 2, 2, False, False),
            p4_row("a", None, 2, False), p4_row("b", 1, 2)]
    write_rows(tmp_path / "results.jsonl", rows)
    result = run_cli(tmp_path, "p4", "--tag", "synthetic", "--out", tmp_path, "--pair", "a,b")
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["valid_definition"] == U.VALID_DEFINITION
    assert data["all"]["arms"]["a"]["attempted"] == 5
    assert data["all"]["arms"]["a"]["valid"] == 2
    assert data["env_clean"]["arms"]["a"]["attempted"] == 3
    assert data["env_clean"]["arms"]["a"]["valid"] == 1
    assert data["all"]["arms"]["b"]["valid"] == data["env_clean"]["arms"]["b"]["valid"] == 1
    text = run_cli(tmp_path, "p4", "--tag", "synthetic", "--out", tmp_path, "--pair", "a,b", "--text")
    assert text.returncode == 0, text.stderr
    assert "valid = " + U.VALID_DEFINITION in text.stdout
    for subset in ("all", "env_clean"):
        header = text.stdout.split("\n" + subset + "\n", 1)[1].split("\n", 1)[0]
        assert "valid" in header.split()
    # An empty env_clean subset is valid when both arms exist in the selected data.
    unclean = U.p4([p4_row(arm, 0, 0, False) for arm in ("a", "b")], "synthetic", ("a", "b"))
    assert all(group["valid"] == 0 for group in unclean["env_clean"]["arms"].values())
    assert unclean["all"]["ratios"]["cost"]["ratio"] is None


@pytest.mark.parametrize("rows,tag,message", [
    ([], "synthetic", "no P4 rows selected"),
    ([p4_row("a", 1, 1), p4_row("b", 1, 1)], "wrong-tag", "check --tag and --out"),
    ([p4_row("a", 1, 1)], "synthetic", "arm='b'"),
    ([p4_row("b", 1, 1)], "synthetic", "arm='a'"),
])
def test_review_p4_missing_selection_or_arm_is_cli_error(tmp_path, rows, tag, message):
    write_rows(tmp_path / "results.jsonl", rows)
    with pytest.raises(ValueError) as error:
        U.p4(rows, tag, ("a", "b"))
    assert message in str(error.value)
    result = run_cli(tmp_path, "p4", "--tag", tag, "--out", tmp_path, "--pair", "a,b")
    assert result.returncode == 2 and message in result.stderr
    assert not result.stdout.strip()


@pytest.mark.parametrize("command", ["strength", "p4"])
def test_review_invalid_outcome_reports_arm_and_record(tmp_path, command):
    if command == "strength":
        rows = [{"arm": "on", "ok": True, "usd": 1},
                {"arm": "off", "task": "bad-case", "rep": 2, "ok": "Unknown", "usd": 1}]
        args = ["strength", tmp_path]
    else:
        rows = [p4_row("on", 1, 1), p4_row("off", 1, 1, ok="Unknown", task="bad-case", rep=2)]
        args = ["p4", "--tag", "synthetic", "--out", tmp_path, "--pair", "on,off"]
    write_rows(tmp_path / "results.jsonl", rows)
    result = run_cli(tmp_path, *args)
    assert result.returncode == 2
    assert all(value in result.stderr for value in ("bool or null", "row 2", "arm='off'", "task='bad-case'", "rep=2"))
