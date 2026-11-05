"""Dispatch experiment plans and early stopping; no paid models or tool homes."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from test_p4_long_session import fake_engine  # noqa: F401

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "eval"))
import p4_long_session as P
import dispatch_eval as D


def row(escalated, task="t", **overrides):
    return {"arm": D.ARM, "task": task, "dispatch_observed": True,
            "side_ledger": [{"dispatch": {"cheap_first": True, "attempted": 1,
                              "escalated": escalated, "first_usd": .01, "escalation_usd": .1 * escalated}}], **overrides}


def test_six_reused_tasks_and_paired_single_task_sessions():
    ts = P.selected_tasks("dispatch")
    assert ts == P.TASKS.T[:6] and len(ts) == 6
    assert {t["split"] for t in ts} == {"dev", "final"}
    units = P.schedule(ts, arms=("self", D.ARM))
    assert len(units) == 12
    for i in range(0, 12, 2):
        assert units[i]["task"] == units[i + 1]["task"]
        assert {units[i]["arm"], units[i + 1]["arm"]} == {"self", D.ARM}
        assert units[i]["turn"] == units[i + 1]["turn"] == 1


def test_stop_above_30_percent_and_missing_evidence():
    assert D.stop_reason([row(1)]) == "escalation_rate_above_30_percent"
    assert D.stop_reason([row(1), row(0), row(0), row(0)]) is None
    assert D.stop_reason([row(0, dispatch_observed=False)]) == "dispatch_evidence_unknown"
    assert D.metrics([])["escalation_rate"] is None
    assert D.metrics([row(0, side_ledger=[{"dispatch": {"cheap_first": True, "attempted": 1,
                                                   "escalated": 0, "first_usd": None}}])])["first_usd"] is None
    assert D.stop_reason([row(0, side_ledger=[{"dispatch": {"cheap_first": True, "attempted": 1,
                                                     "escalated": 0, "first_usd": None}}])]) == "dispatch_cost_unknown"


def test_dry_run_outside_repository(tmp_path):
    script = Path(P.__file__).resolve()
    result = subprocess.run([sys.executable, str(script), "--dry-run", "--split", "dispatch", "--arms", "self,ccxcheapfirst",
                             "--budget", "6.5", "--lead-budget", ".25", "--child-budget", ".5",
                             "--out", str(tmp_path/"results.jsonl")], cwd=tmp_path, capture_output=True,
                            encoding="utf-8", env={**os.environ, "CCX_NO_QUOTA_PROBE": "1"})
    assert result.returncode == 0, result.stderr
    plan = json.loads(result.stdout)
    assert len(plan["units"]) == 12 and plan["target_tasks"] == 6 and not plan["run"]
    assert plan["dispatch"]["stop_escalation_rate_above"] == .3
    assert plan["budget_envelope"]["operational_upper_usd"] <= 8
    assert not (tmp_path/"results.jsonl").exists()


@pytest.mark.parametrize("args", [("--budget", "9"), ("--rounds", "2"), ("--arms", "ccxcheapfirst")])
def test_invalid_experiments_refused_before_execution(args):
    with pytest.raises(SystemExit):
        P.main(["--dry-run", "--split", "dispatch", "--arms", "self,ccxcheapfirst", *args])


def test_operational_budget_above_eight_refuses_real_run_before_preflight(monkeypatch):
    monkeypatch.setattr(P, "run_experiment", lambda *args: pytest.fail("started a model run"))
    with pytest.raises(SystemExit, match="operational budget envelope"):
        P.main(["--run", "--split", "dispatch", "--arms", "self,ccxcheapfirst", "--budget", "8"])


def test_engine_stops_before_next_model_when_first_attempt_escalates(fake_engine, monkeypatch):
    a, ts, log = fake_engine
    a.budget = 7
    a.lead_budget = .25
    a.child_budget = .5
    monkeypatch.setattr(P.r5, "hub_rows", lambda hub: [{"dispatch": {"cheap_first": True, "attempted": 1,
                           "escalated": 1, "first_usd": .01, "escalation_usd": .1}}] if str(hub).endswith(D.ARM) else [])
    assert P.run_experiment(a, ts, P.schedule(ts, arms=("self", D.ARM))) == 2
    entries = [json.loads(s) for s in log.read_text().splitlines()]
    assert len(entries) == 1  # alternating schedule starts the candidate in the first pair
    rows = P.read_jsonl(a.out)
    assert len(rows) == 1 and D.stop_reason(rows) == "escalation_rate_above_30_percent"
    assert (a.work / "hub-1-1-ccxcheapfirst" / "ccx" / "settings.toml").read_text() == "[dispatch]\ncheap_first = true\n"


def test_comparison_preserves_incomplete_and_clean_denominators():
    rows = []
    for i in range(6):
        common = {"round": 1, "episode": i + 1, "ok": True, "cost_complete": True,
                  "env_clean": i != 0, "wall_s": 1}
        rows += [row(0, task=str(i), usd=.1, **common),
                 {"arm": "self", "task": str(i), "usd": .2, **common}]
    result = D.comparison(rows, 6)
    assert result["all"]["verdict"] == "Pass"
    assert result["env_clean"]["verdict"] == "Unknown"
    assert result["env_clean"]["arms"][D.ARM]["attempted"] == 5
    assert D.comparison(rows[:-1], 6)["all"]["verdict"] == "Unknown"
