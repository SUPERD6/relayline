"""Offline report arithmetic and evidence boundaries; no CLI/model dependency."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/eval/optimize_summary.py"
spec = importlib.util.spec_from_file_location("optimize_summary", SCRIPT)
summary = importlib.util.module_from_spec(spec)
spec.loader.exec_module(summary)


def short_rows():
    return [{"arm": arm, "task": str(i), "round": 1, "ok": i != 0,
             "usd": cost, "lead_usd": cost, "wall_s": i + 1, "env_clean": True}
            for arm, cost in (("self", 1), ("ccx3cand", 1.27)) for i in range(30)]


def test_failed_attempt_cost_included_and_true_median():
    result = summary.summarize(short_rows(), "short")
    assert result["verdict"] == "Fail"
    arm = result["all"]["arms"]["self"]
    assert arm["right"] == 29
    assert arm["cost_per_success"] == 30 / 29
    assert arm["wall_median_s"] == 15.5
    assert arm["wall_total_s"] == 465


def test_missing_cost_zero_success_and_unclean_remain_unknown():
    rows = short_rows()
    rows[0]["usd"] = None
    assert summary.summarize(rows, "short")["verdict"] == "Unknown"
    assert summary.aggregate([{"ok": False, "usd": 1}])["cost_per_success"] is None
    assert summary.aggregate([{"ok": True, "usd": 1, "cost_complete": False}])["usd"] is None
    rows = short_rows()
    for row in rows[:7]:
        row["env_clean"] = False
    assert summary.summarize(rows, "short")["verdict"] == "Unknown"


def test_incomplete_duplicate_or_missing_outcome_not_a_pass():
    rows = short_rows()
    assert summary.summarize(rows[:-1], "short")["verdict"] == "Unknown"
    rows[0]["task"] = rows[1]["task"]
    assert summary.summarize(rows, "short")["verdict"] == "Unknown"
    rows = short_rows()
    rows[0].pop("ok")
    assert summary.summarize(rows, "short")["verdict"] == "Unknown"


def review_rows():
    return [{"hidden_ok": False, "verdict": "unknown", "usd": .1} for _ in range(15)] + [
        {"hidden_ok": True, "verdict": "pass", "usd": .1} for _ in range(14)]


def test_review_unknown_bounds_and_zero_denominator():
    rows = review_rows()
    result = summary.summarize(rows, "review")
    assert result["verdict"] == "Unknown"
    assert result["worst"]["caught"] == 0
    assert result["best"]["caught"] == 15
    for row in rows[:8]:
        row["verdict"] = "issues"
    assert summary.summarize(rows, "review")["verdict"] == "Pass"
    for row in rows[:15]:
        row["verdict"] = "pass"
    assert summary.summarize(rows, "review")["verdict"] == "Fail"
    assert summary.summarize([], "review")["verdict"] == "Unknown"


def test_long_episode_completion_and_environment_error():
    rows = [{"arm": arm, "round": 1, "episode": episode, "turn": turn,
             "task": f"{episode}-{turn}", "usd": usd, "ok": True, "wall_s": wall,
             "env_clean": True, "cost_complete": True}
            for arm, usd, wall in (("self", 1, 10), ("ccxlong", .7, 15))
            for episode in (1, 2) for turn in (1, 2, 3, 4)]
    assert summary.summarize(rows, "long")["verdict"] == "Pass"
    rows[0]["environment_error"] = True
    assert summary.summarize(rows, "long")["verdict"] == "Unknown"
    rows[0].pop("environment_error")
    rows[0]["episode"] = 2
    assert summary.summarize(rows, "long")["verdict"] == "Unknown"


def test_cli_from_outside_repo_emits_no_raw_paths_or_mutation(tmp_path):
    source = tmp_path / "short.jsonl"
    source.write_text("\n".join(json.dumps({**r, "private": "DO_NOT_PUBLISH"}) for r in short_rows()),
                      encoding="utf-8")
    before = source.read_bytes()
    result = subprocess.run([sys.executable, str(SCRIPT), "--short", str(source)],
                            cwd=tmp_path, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert output["short"]["verdict"] == "Fail"
    assert "DO_NOT_PUBLISH" not in result.stdout
    assert str(tmp_path) not in result.stdout
    assert source.read_bytes() == before
