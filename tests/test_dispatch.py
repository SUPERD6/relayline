"""Cheap dispatch wiring through real ccx subprocesses and the fake CLI adapters."""
import json
import sys
from pathlib import Path

import pytest

from test_adapters import AdapterEnv
from test_check_baseline import git, repository
from ccx import dispatch
from ccx.config import Paths, load_config


def test_default_off_and_strict_boolean():
    assert load_config(Paths(Path("unused-hub")))["dispatch"]["cheap_first"] is False
    assert not dispatch.cheap_first({"dispatch": {"cheap_first": "true"}})


@pytest.mark.parametrize("check,expected", [
    ({"passed": False, "baseline_comparison": "baseline_passed"}, True),
    ({"passed": False, "baseline_comparison": "new_failures"}, True),
    ({"passed": False, "baseline_comparison": "baseline_only"}, False),
    ({"passed": False, "baseline_comparison": "Unknown"}, False),
    ({"passed": False, "broken": True, "baseline_comparison": "baseline_passed"}, False),
    ({"passed": True, "baseline_comparison": "baseline_passed"}, False),
])
def test_only_independently_verified_new_failures_escalate(check, expected):
    assert dispatch.may_escalate(check) is expected
    assert not dispatch.may_escalate(check, self_checked=True)


def test_unknown_cost_is_not_zero():
    record = {"dispatch": {}, "attempts": [{"dispatch_phase": "first", "ae_usd": None},
                                            {"dispatch_phase": "escalation", "ae_usd": .2}]}
    dispatch.receipt(record)
    assert record["dispatch"] == {"attempted": 1, "escalated": 1, "escalation_rate": 1.,
                                  "first_usd": None, "escalation_usd": .2, "recovery_usd": 0}


class TestDispatchCommand(AdapterEnv):
    def setUp(self):
        super().setUp()
        repository(self.work)

    def enable(self):
        self.j("config", "set", "dispatch.cheap_first", "true")

    def checked(self, *options, extra="", env=None):
        return self.j("run", "--from", "claude", "--to", "codex", "--tier", "T2", "--new",
                      "--mode", "write", "--review", "off", "--no-fallback", *options,
                      "--check", f'"{sys.executable}" check_run.py {extra}', "fix state.txt",
                      env=env or {"FAKE_WRITE": "state.txt=edited"})

    def test_default_keeps_original_start(self):
        out = self.checked()
        rec = self.rec(out["run_id"])
        assert rec["attempts"][0]["tier"] == "T2"
        assert "dispatch" not in rec

    def test_baseline_only_stops_at_cheap_rung_and_records_cost(self):
        self.enable()
        out = self.checked()
        rec = self.rec(out["run_id"])
        assert [a["tier"] for a in rec["attempts"]] == ["T1"]
        assert rec["kind"] == "check_baseline_failed"
        assert rec["dispatch"]["escalation_rate"] == 0
        assert rec["dispatch"]["first_usd"] == rec["attempts"][0]["ae_usd"]
        rows = [json.loads(s) for s in (self.hub/"ccx"/"ledger.jsonl").read_text().splitlines()]
        assert next(r for r in rows if r.get("run_id") == out["run_id"])["dispatch"] == rec["dispatch"]

    def test_new_failures_escalate_and_only_new_cases_are_carried(self):
        self.enable()
        out = self.checked(env={"FAKE_WRITE": "state.txt=new", "FAKE_WRITE_RESUMED": "state.txt=edited"})
        rec = self.rec(out["run_id"])
        assert [a["tier"] for a in rec["attempts"]] == ["T1", "T2"]
        assert rec["dispatch"]["escalation_rate"] == 1
        prompt = [c for c in self.calls() if c["agent"] == "codex"][-1]["prompt"]
        assert "test_new" in prompt and "test_old" not in prompt
        assert rec["dispatch"]["escalation_usd"] == rec["attempts"][1]["ae_usd"]

    def test_unknown_baseline_stops_without_escalation(self):
        self.enable()
        out = self.checked(extra="opaque")
        rec = self.rec(out["run_id"])
        assert len(rec["attempts"]) == 1 and rec["kind"] == "check_failed"
        assert rec["checks"][0]["baseline_comparison"] == "Unknown"

    def test_baseline_pass_allows_escalation(self):
        self.enable()
        rec = self.rec(self.checked(extra="passbase")["run_id"])
        assert [a["tier"] for a in rec["attempts"]] == ["T1", "T2"]

    def test_explicit_pin_and_no_escalate_are_preserved(self):
        self.enable()
        for options in (("--model", "gpt-6.1-sol", "--effort", "high"), ("--no-escalate",)):
            rec = self.rec(self.checked(*options)["run_id"])
            assert rec["attempts"][0]["model"] == "gpt-6.1-sol"
            assert "dispatch" not in rec

    def test_no_check_keeps_original_path(self):
        self.enable()
        out = self.j("run", "--from", "claude", "--to", "codex", "--tier", "T2", "--new",
                     "--review", "off", "--no-fallback", "fix state.txt", env={"FAKE_WRITE": "state.txt=edited"})
        rec = self.rec(out["run_id"])
        assert rec["attempts"][0]["tier"] == "T2" and "dispatch" not in rec

    def test_self_written_check_failure_cannot_trigger_escalation(self):
        self.enable()
        (self.work / "test_contract.py").write_text("def test_contract():\n    assert True\n", encoding="utf-8", newline="")
        git(self.work, "add", "test_contract.py")
        git(self.work, "commit", "-qm", "independent check")
        out = self.j("run", "--from", "claude", "--to", "codex", "--tier", "T2", "--new", "--review", "off",
                     "--no-fallback", "--check", f'"{sys.executable}" -m pytest -q -p no:cacheprovider test_contract.py',
                     "fix state.txt", env={"FAKE_WRITE": "test_contract.py=def test_contract():\n    assert False\n",
                                           "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"})
        rec = self.rec(out["run_id"])
        assert len(rec["attempts"]) == 1 and rec["kind"] == "check_failed"
        assert rec["check"]["baseline_comparison"] == "baseline_passed"

    def test_environment_failure_does_not_escalate(self):
        self.enable()
        out = self.j("run", "--from", "claude", "--to", "codex", "--tier", "T2", "--new", "--review", "off",
                     "--no-fallback", "--check", f'"{sys.executable}" check_run.py', "fix state.txt",
                     env={"FAKE_STATUS": "env"})
        rec = self.rec(out["run_id"])
        assert rec["kind"] == "env" and len(rec["attempts"]) == 1
        assert rec["dispatch"]["escalated"] == 0

    def test_quota_fallback_is_recovery_not_task_escalation(self):
        self.enable()
        out = self.j("run", "--from", "claude", "--to", "codex", "--tier", "T2", "--new", "--review", "off",
                     "--check", f'"{sys.executable}" check_run.py', "fix state.txt",
                     env={"FAKE_STATUS_CODEX": "quota", "FAKE_WRITE": "state.txt=edited"})
        rec = self.rec(out["run_id"])
        assert [a["agent"] for a in rec["attempts"]] == ["codex", "claude"]
        assert rec["dispatch"]["escalated"] == 0 and rec["dispatch"]["escalation_usd"] == 0
        assert rec["dispatch"]["recovery_usd"] == rec["attempts"][1]["ae_usd"]

    def test_budget_still_stops_before_stronger_attempt(self):
        self.enable()
        rec = self.rec(self.checked("--max-usd", "0.0000001", extra="passbase")["run_id"])
        assert len(rec["attempts"]) == 1 and rec["dispatch"]["escalated"] == 0
        assert rec["max_usd"]["stopped_before"] == "attempt"

    def test_blocked_worker_with_baseline_failure_does_not_climb(self):
        self.enable()
        out = self.checked(env={"FAKE_STATUS": "blocked", "FAKE_WRITE": "state.txt=edited"})
        rec = self.rec(out["run_id"])
        assert len(rec["attempts"]) == 1 and rec["kind"] == "check_baseline_failed"
        assert rec["learned"] is None

    def passing_command(self):
        (self.work / "check_pass.py").write_text(
            "from pathlib import Path\nimport sys\n"
            "sys.exit(0 if Path('state.txt').read_text() in ('base', 'fixed') else 1)\n",
            encoding="utf-8", newline="")
        git(self.work, "add", "check_pass.py")
        git(self.work, "commit", "-qm", "acceptance command")
        return f'"{sys.executable}" check_pass.py'

    def test_passing_cheap_attempt_finishes_without_stronger_model(self):
        self.enable()
        command = self.passing_command()
        out = self.j("run", "--from", "claude", "--to", "codex", "--tier", "T2", "--new", "--review", "off",
                     "--no-fallback", "--check", command, "fix state.txt", env={"FAKE_WRITE": "state.txt=fixed"})
        rec = self.rec(out["run_id"])
        assert out["ok"] is True and [a["tier"] for a in rec["attempts"]] == ["T1"]
        assert rec["dispatch"]["escalated"] == 0 and "check_baseline" not in rec

    def test_failed_cheap_attempt_can_finish_successfully_after_escalation(self):
        self.enable()
        command = self.passing_command()
        out = self.j("run", "--from", "claude", "--to", "codex", "--tier", "T2", "--new", "--review", "off",
                     "--no-fallback", "--check", command, "fix state.txt",
                     env={"FAKE_WRITE": "state.txt=new", "FAKE_WRITE_RESUMED": "state.txt=fixed"})
        rec = self.rec(out["run_id"])
        assert out["ok"] is True and [a["tier"] for a in rec["attempts"]] == ["T1", "T2"]
        assert out["dispatch"]["escalated"] == 1 and out["check"]["passed"] is True
