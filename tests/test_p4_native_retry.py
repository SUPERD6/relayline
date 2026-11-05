"""Opt-in P4 controls: temporary repositories and fake CLIs, no paid calls."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/eval"))
import p4_long_session as P
import p4_check_overlap as O
from ccx.config import Paths, load_config
from test_p4_long_session import fake_engine


def test_final_native_three_arm_dry_run_outside_repository(tmp_path):
    run = subprocess.run([sys.executable, str(ROOT / "scripts/eval/p4_long_session.py"),
                          "--dry-run", "--split", "final", "--native-checkout", "--focused-retry",
                          "--arms", "self,ccxlong,ccxlongcheap", "--out", str(tmp_path / "unused.jsonl")],
                         cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert run.returncode == 0, run.stderr
    plan = json.loads(run.stdout)
    assert plan["checkout_policy"] == P.LE.POLICY and plan["focused_retry"] is True
    assert plan["available_tasks"] == 8 and len(plan["units"]) == 24
    assert set(plan["arms"]) == {"self", "ccxlong", "ccxlongcheap"}
    assert not plan["run"] and not (tmp_path / "unused.jsonl").exists()


def test_controls_default_off_and_p5_keeps_native_policy():
    args = P.parser().parse_args([])
    assert not args.focused_retry and not P.native_checkout(args)
    assert P.native_checkout(P.parser().parse_args(["--split", "p5"]))


@pytest.mark.parametrize("failed", [False, True])
def test_final_native_gate_before_fake_model_and_matching_scoring(fake_engine, monkeypatch, failed):
    args, tasks, log = fake_engine
    args.split, args.native_checkout, args.rounds = "final", True, 1
    audit_calls = []
    def audit(ts, *a):
        audit_calls.append(ts)
        return {"excluded": [ts[0]["commit"]] if failed else []}
    monkeypatch.setattr(P.LE, "audit", audit)
    original_score = P.score
    def score(repo, task, material, python, native=False):
        assert native
        return original_score(repo, task, material, python, native)
    monkeypatch.setattr(P, "score", score)
    assert P.run_experiment(args, tasks, P.schedule(tasks)) == (2 if failed else 0)
    assert audit_calls == [tasks]
    assert log.exists() is (not failed)
    if not failed:
        assert all(row["checkout_evidence"]["policy"] == P.LE.POLICY for row in P.read_jsonl(args.out))


@pytest.mark.parametrize("enabled", [False, True])
def test_focused_retry_isolated_hub_configuration(fake_engine, monkeypatch, enabled):
    args, tasks, log = fake_engine
    args.focused_retry = enabled
    original = P.PF.run
    seen = []
    def run(argv, **kwargs):
        if "--session-id" in argv or "--resume" in argv:
            hub = Path(kwargs["cwd"]).with_name(Path(kwargs["cwd"]).name.replace("repo-", "hub-", 1))
            value = load_config(Paths(hub))["defaults"]["focused_retry"]
            assert value is enabled
            seen.append(value)
        return original(argv, **kwargs)
    monkeypatch.setattr(P.PF, "run", run)
    assert P.run_experiment(args, tasks, P.schedule(tasks, arms=("self", "ccxlong", "ccxlongcheap"))) == 0
    assert len(seen) == 12
    assert all(r["focused_retry"] is enabled for r in P.read_jsonl(args.out))


def test_offline_native_validation_reports_failed_baseline_without_models(monkeypatch, tmp_path):
    ts = P.selected_tasks("final")
    monkeypatch.setattr(P.LE, "audit", lambda tasks, *a: {"excluded": [ts[0]["commit"]], "checked": tasks})
    monkeypatch.setattr(P, "run_experiment", lambda *a: pytest.fail("model engine called"))
    out = tmp_path / "audit.json"
    assert P.main(["--validate-native", "--native-checkout", "--split", "final", "--ext-cache", str(tmp_path),
                   "--audit-output", str(out)]) == 1
    assert len(json.loads(out.read_text())["checked"]) == 8


def test_overlap_missing_timing_is_unknown_and_deduplicates_receipts(tmp_path):
    stream = tmp_path / "artifacts" / "unit" / "streams"
    child = stream / "subagents" / "run"
    child.mkdir(parents=True)
    receipt = {"run_id": "run", "check": {"cmd": "python -m pytest -q", "exit": 0}}
    (stream / "lead.jsonl").write_text(json.dumps({"content": json.dumps(receipt)}) + "\n" + json.dumps(receipt) + "\n")
    event = {"type": "item.completed", "item": {"type": "command_execution", "command": "python -m pytest -q",
             "exit_code": 0, "aggregated_output": "3 passed in 0.42s"}}
    (child / "events.0.log").write_text(json.dumps(event) + "\n")
    results = tmp_path / "rows.jsonl"
    results.write_text(json.dumps({"task": "fake", "arm": "ccxlong", "streams": {"dir": "unit"}, "wall_s": 10}) + "\n")
    report = O.analyze(results, tmp_path / "artifacts")
    assert report["controller_unknown_timing"] == 1 and report["controller_known_fraction_of_wall"] is None
    assert report["command_exit_candidates"] == 1 and report["candidate_pytest_reported_seconds"] == .42
    assert report["potential_savings_seconds"] == "Unknown" and report["safe_reusable_seconds"] == 0
