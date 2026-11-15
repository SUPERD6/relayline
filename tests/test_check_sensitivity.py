"""Sensitivity and cheap-first wiring: fake agent CLIs, independent checks, disposable Git trees."""
import json
import sys

import pytest

from ccx import check_baseline as baseline, dispatch, leadview
from test_adapters import AdapterEnv
from test_check_baseline import git, repository


@pytest.mark.parametrize("before,after,passed,expected,fixed", [
    (["a::one"], [], True, "sensitive", ["a::one"]),
    ([], [], True, "insensitive", []),
    (["a::one"], ["a::one"], False, "insensitive", []),
    (["a::one", "a::two"], ["a::two"], False, "sensitive", ["a::one"]),
    (["a::one"], ["a::one", "a::two"], False, "unknown", []),
    (None, None, False, "unknown", None),
    (None, [], True, "sensitive", None),
])
def test_comparison(before, after, passed, expected, fixed):
    old = {"status": "Pass" if before == [] else "Fail", "check": {"failed_cases": before}}
    result = baseline.sensitivity({"passed": passed, "failed_cases": after}, old)
    assert result["sensitivity"] == expected
    assert result.get("fixed_cases") == fixed


@pytest.mark.parametrize("check,old", [
    ({}, {"status": "Pass"}),
    ({"passed": True}, {"status": "Unknown"}),
    ({"passed": True}, {"status": "Fail", "check": {"broken": "no tests"}}),
    ({"passed": False, "broken": "no tests"}, {"status": "Pass"}),
    ({"passed": False, "exit": -1}, {"status": "Fail"}),
])
def test_unavailable_or_broken_is_unknown(check, old):
    assert baseline.sensitivity(check, old) == {"sensitivity": "unknown"}


def test_off_never_captures_or_runs_a_passing_baseline(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("default-off passing checks must not capture or run a baseline")
    monkeypatch.setattr(baseline, "capture", forbidden)
    monkeypatch.setattr(baseline, "run_baseline", forbidden)
    for setting in ({}, {"baseline": "on_fail", "sensitivity": "off"}):
        record = {}
        checks = baseline.Checks({"defaults": {}, "check": setting}, tmp_path, tmp_path, record,
                                 lambda *a, **k: {"passed": True}, True,
                                 start={"status": "ready"} if setting else None)
        assert checks("check") == {"passed": True}
        assert "check_baseline" not in record and "check_sensitivity" not in record


def test_sensitivity_without_check_does_not_capture(tmp_path, monkeypatch):
    def forbidden(*args):
        pytest.fail("no --check must not capture a dispatch tree")
    monkeypatch.setattr(baseline, "capture", forbidden)
    record = {}
    baseline.Checks({"defaults": {}, "check": {"sensitivity": "warn"}}, tmp_path, tmp_path,
                    record, forbidden, False)
    assert record["check_sensitivity"] == "unknown" and "check_baseline_start" not in record


def test_warn_does_not_change_failed_check_policy_and_caches_baseline(tmp_path, monkeypatch):
    calls = []
    def before(*args):
        calls.append(args)
        return {"status": "Fail", "seconds": 1.25, "check": {"failed_cases": ["t::old"]}}
    monkeypatch.setattr(baseline, "run_baseline", before)
    record = {}
    checks = baseline.Checks({"defaults": {}, "check": {"sensitivity": "warn"}}, tmp_path, tmp_path,
                             record, lambda *a, **k: {"passed": False, "failed_cases": ["t::old"]},
                             True, start={"status": "ready"})
    first, second = checks("same command"), checks("same command")
    assert first["sensitivity"] == second["sensitivity"] == "insensitive"
    assert "baseline_comparison" not in first  # baseline=off retains ordinary retries
    assert len(calls) == 1 and record["check_baseline_seconds"] == 1.25
    assert first["sensitivity_seconds"] == 1.25 and second["sensitivity_seconds"] == 0


def test_escalation_only_for_enabled_cheap_first_phase():
    check = {"passed": True, "sensitivity": "insensitive"}
    cfg = {"check": {"sensitivity": "escalate"}}
    assert dispatch.unverified(cfg, check, True, "first")
    assert not dispatch.unverified(cfg, check, False, "first")
    assert not dispatch.unverified(cfg, check, True, "escalation")
    assert not dispatch.unverified(cfg, check, True, "recovery")
    assert not dispatch.unverified({"check": {"sensitivity": "warn"}}, check, True, "first")


@pytest.mark.parametrize("after", [["a::regression"], None])
def test_passing_baseline_then_failure_is_unknown_without_insensitive_hint(after):
    result = baseline.sensitivity({"passed": False, "failed_cases": after},
                                  {"status": "Pass", "check": {"failed_cases": []}})
    assert result["sensitivity"] == "unknown"
    assert "sensitivity_hint" not in result


def test_failed_insensitive_check_cannot_use_passing_unverified_branch():
    cfg = {"check": {"sensitivity": "escalate"}}
    check = {"passed": False, "sensitivity": "insensitive", "baseline_comparison": "baseline_only"}
    assert not dispatch.unverified(cfg, check, True, "first")
    assert not dispatch.may_escalate(check)
    assert dispatch.may_escalate(check, insensitive=dispatch.sensitivity_retry(cfg, check, True, "first"))


@pytest.mark.parametrize("code", [1, 2, 3, 4, 5])
def test_unparsed_failure_requires_test_failure_exit(code):
    result = baseline.sensitivity({"passed": True, "failed_cases": []},
                                  {"status": "Fail", "check": {"exit": code, "failed_cases": None}})
    assert result["sensitivity"] == ("sensitive" if code == 1 else "unknown")


def test_sensitivity_line_view_keeps_only_small_baseline_metadata():
    result = {"run_id": "r", "status": "done", "ok": True, "check": {"passed": True},
              "check_sensitivity_mode": "warn", "check_sensitivity": "sensitive", "check_baseline_seconds": 1.25,
              "check_baseline": {"status": "Fail", "import_origins": ["x" * 32768]}}
    line = leadview.line(result)
    assert "check_baseline" not in line
    for key in ("check_sensitivity_mode", "check_sensitivity", "check_baseline_seconds"):
        assert line[key] == result[key]
    assert len(json.dumps(line)) < 1000


@pytest.mark.parametrize("escalate", [False, True])
def test_warn_starts_review_before_check_in_both_delegate_paths(monkeypatch, escalate):
    import os
    from unittest.mock import patch
    from ccx import delegate
    from ccx.config import Paths, set_setting
    env = AdapterEnv()
    env.setUp()
    try:
        repository(env.work)
        (env.work / "acceptance.py").write_text(
            "from pathlib import Path\nassert Path('state.txt').read_text() == 'fixed'\n",
            encoding="utf-8", newline="")
        git(env.work, "add", "acceptance.py")
        git(env.work, "commit", "-qm", "independent acceptance")
        paths = Paths(env.hub)
        set_setting(paths, "check.sensitivity", "warn")
        events = []
        def start(*args):
            events.append("review")
            return object()
        def finish(future, record, paths, keep=True):
            record["review"] = {"verdict": "pass"}
        def deferred(req, paths, cfg, record, *args):
            events.append("review")
            record["review"] = {"verdict": "pass"}
        actual_check = baseline.Checks.__call__
        def check(self, *args, **kwargs):
            events.append("check")
            return actual_check(self, *args, **kwargs)
        monkeypatch.setattr(delegate, "_start_review", start)
        monkeypatch.setattr(delegate, "_finish_review", finish)
        monkeypatch.setattr(delegate, "_review", deferred)
        monkeypatch.setattr(baseline.Checks, "__call__", check)
        with patch.dict(os.environ, {**env.env, "FAKE_WRITE": "state.txt=fixed"}, clear=True):
            delegate.run(delegate.Request(to="codex", caller="claude", brief="fix state.txt", cwd=env.work,
                                          tier="T1", mode="write", review="on", fallback=False, escalate=escalate,
                                          check=f'"{sys.executable}" acceptance.py'), paths)
        assert events.index("review") < events.index("check")
    finally:
        env.tearDown()


class TestSensitivityCLI(AdapterEnv):
    def setUp(self):
        super().setUp()
        repository(self.work)
        (self.work / "test_acceptance.py").write_text(
            "import os\nfrom pathlib import Path\n"
            "def test_requirement():\n"
            "    if os.environ.get('CCX_TEST_SENSITIVITY') == 'sensitive':\n"
            "        assert Path('state.txt').read_text() == 'fixed'\n"
            "def test_existing():\n"
            "    assert os.environ.get('CCX_TEST_SENSITIVITY') != 'same_failures'\n",
            encoding="utf-8", newline="")
        git(self.work, "add", "test_acceptance.py")
        git(self.work, "commit", "-qm", "independent sensitivity acceptance")

    def checked(self, mode="warn", scenario="passed_before", *options, cheap=False, dirty=False, tier="T2",
                command=None):
        self.j("config", "set", "check.sensitivity", mode)
        if cheap:
            self.j("config", "set", "dispatch.cheap_first", "true")
        if dirty:
            (self.work / "dirty.txt").write_text("preexisting", encoding="utf-8")
        return self.j("run", "--from", "claude", "--to", "codex", "--tier", tier, "--new",
                      "--mode", "write", "--review", "off", "--no-fallback", *options,
                      "--check", command or f'"{sys.executable}" -m pytest -q -p no:cacheprovider test_acceptance.py',
                      "fix state.txt",
                      env={"FAKE_WRITE": "state.txt=fixed", "CCX_TEST_SENSITIVITY": scenario,
                           "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"})

    def test_off_passing_check_does_not_run_baseline(self):
        out = self.checked("off")
        rec = self.rec(out["run_id"])
        assert out["check"]["passed"] and len(rec["checks"]) == 1
        assert "check_baseline_start" not in rec and "check_baseline" not in rec
        assert "sensitivity" not in out["check"]

    def test_warn_fail_before_pass_after_and_receipt_time(self):
        out = self.checked("warn", "sensitive")
        rec = self.rec(out["run_id"])
        assert out["check"]["sensitivity"] == rec["check"]["sensitivity"] == "sensitive"
        assert out["check"]["fixed_cases"] == ["test_acceptance.py::test_requirement"]
        assert out["check"]["sensitivity_seconds"] == out["check_baseline_seconds"] >= 0
        assert self.j("show", out["run_id"])["check_baseline"]["status"] == "Fail" and len(rec["attempts"]) == 1
        assert self.j("show", out["run_id"])["check"]["sensitivity"] == "sensitive"

    def test_warn_passed_before_has_hint_without_escalation(self):
        out = self.checked(cheap=True)
        rec = self.rec(out["run_id"])
        assert out["check"]["sensitivity"] == "insensitive"
        assert "already passed before the change" in out["needs_lead"]
        assert "add a test for the new requirement" in out["hint"]
        assert [a["tier"] for a in rec["attempts"]] == ["T1"]

    def test_warn_same_failures_is_insensitive_and_baseline_policy_preserved(self):
        out = self.checked("warn", "same_failures", cheap=True)
        rec = self.rec(out["run_id"])
        assert out["check"]["sensitivity"] == "insensitive"
        assert out["kind"] == "check_baseline_failed" and len(rec["attempts"]) == 1
        assert "same failing cases" in out["needs_lead"]

    def test_escalate_insensitive_pass_to_original_rung(self):
        out = self.checked("escalate", cheap=True)
        rec = self.rec(out["run_id"])
        assert [a["tier"] for a in rec["attempts"]] == ["T1", "T2"]
        assert rec["dispatch"]["escalated"] == 1
        assert rec["attempts"][0]["check_sensitivity"] == "insensitive"
        assert len(rec["check_baselines"]) == 1
        assert rec["checks"][1]["sensitivity_seconds"] == 0
        assert "did not verify the new requirement" in self.calls()[-1]["prompt"]
        assert "add a test for the new requirement" not in self.calls()[-1]["prompt"]
        assert "verify the work against the task text" in self.calls()[-1]["prompt"]
        assert rec["attempts"][0]["kind"] == "check_unverified"
        assert rec["checks"][0]["passed"] is True

    def test_escalate_same_failures_to_original_rung(self):
        out = self.checked("escalate", "same_failures", cheap=True)
        rec = self.rec(out["run_id"])
        assert [a["tier"] for a in rec["attempts"]] == ["T1", "T2"]
        assert out["check"]["sensitivity"] == "insensitive"

    def test_escalate_same_failures_keeps_failure_prompt(self):
        out = self.checked("escalate", "same_failures", cheap=True)
        rec = self.rec(out["run_id"])
        assert [a["tier"] for a in rec["attempts"]] == ["T1", "T2"]
        assert rec["attempts"][0]["kind"] == "check_failed"
        prompt = self.calls()[-1]["prompt"]
        assert "test_existing" in prompt and "unverified_check" not in prompt
        assert "unverified" in prompt and "already existed before the change" in prompt
        assert rec["checks"][0]["tail"] not in prompt

    def test_same_failures_do_not_use_focused_failure_repair(self):
        self.j("config", "set", "defaults.focused_retry", "true")
        out = self.checked("escalate", "same_failures", cheap=True)
        prompt = self.calls()[-1]["prompt"]
        assert "already existed before the change" in prompt and "unverified" in prompt
        assert "fix only" not in prompt.lower()
        assert "add a test for the new requirement" not in prompt
        assert "retry" not in self.rec(out["run_id"])["attempts"][0]

    def test_regression_keeps_normal_failure_escalation_and_output(self):
        (self.work / "test_regression.py").write_text(
            "from pathlib import Path\n"
            "def test_regression():\n    assert Path('state.txt').read_text() != 'fixed'\n",
            encoding="utf-8", newline="")
        git(self.work, "add", "test_regression.py")
        git(self.work, "commit", "-qm", "independent regression acceptance")
        out = self.checked("escalate", cheap=True,
                           command=f'"{sys.executable}" -m pytest -q -p no:cacheprovider test_regression.py')
        rec = self.rec(out["run_id"])
        assert [a["tier"] for a in rec["attempts"]] == ["T1", "T2"]
        assert rec["attempts"][0]["kind"] == out["kind"] == "check_failed"
        assert out["check"]["sensitivity"] == "unknown"
        prompt = self.calls()[-1]["prompt"]
        assert "test_regression" in prompt and "unverified_check" not in prompt
        assert "already passed before the change" not in out.get("hint", "")
        assert "already passed before the change" not in out.get("needs_lead", "")

    def test_no_escalate_hands_back_to_lead_at_original_rung(self):
        out = self.checked("escalate", "passed_before", "--no-escalate", cheap=True)
        rec = self.rec(out["run_id"])
        assert [a["tier"] for a in rec["attempts"]] == ["T2"]
        assert "dispatch" not in rec and "add a test" in out["needs_lead"]

    def test_already_requested_cheap_rung_hands_back_without_extra_upgrade(self):
        out = self.checked("escalate", cheap=True, tier="T1")
        rec = self.rec(out["run_id"])
        assert [a["tier"] for a in rec["attempts"]] == ["T1"]
        assert "add a test" in out["needs_lead"]

    def test_opaque_fail_to_pass_is_sensitive_without_case_names(self):
        (self.work / "opaque_check.py").write_text(
            "from pathlib import Path\nimport sys\n"
            "print('opaque output')\nsys.exit(0 if Path('state.txt').read_text() == 'fixed' else 1)\n",
            encoding="utf-8", newline="")
        git(self.work, "add", "opaque_check.py")
        git(self.work, "commit", "-qm", "opaque acceptance")
        out = self.checked(command=f'"{sys.executable}" opaque_check.py')
        assert out["check"]["sensitivity"] == "sensitive"
        assert "fixed_cases" not in out["check"]

    def test_unobservable_passing_baseline_is_unknown(self):
        out = self.checked(command=f'"{sys.executable}" -S -c "pass"')
        assert out["check"]["passed"] and out["check"]["sensitivity"] == "unknown"
        assert self.rec(out["run_id"])["check_baseline"]["status"] == "Pass"

    def test_unknown_dirty_baseline_does_not_force_escalation(self):
        out = self.checked("escalate", cheap=True, dirty=True)
        rec = self.rec(out["run_id"])
        assert out["check"]["sensitivity"] == "unknown" and len(rec["attempts"]) == 1
        assert rec.get("check_baseline", {}).get("status") == "Unknown", json.dumps(rec)

    def test_off_cheap_first_failure_preserves_receipt_keys(self):
        from ccx.delegate import compact
        out = self.checked("off", "same_failures", cheap=True)
        rec = self.rec(out["run_id"])
        assert out["kind"] == "check_baseline_failed"
        assert "check_baseline_seconds" in rec and "check_baseline_seconds" not in out
        legacy = compact({key: value for key, value in rec.items() if key != "check_baseline_seconds"})
        assert set(compact(rec)) == set(legacy)
        assert "check_sensitivity" not in out and "check_sensitivity_mode" not in out

    def test_baseline_collection_error_does_not_establish_sensitivity(self):
        with (self.work / ".gitignore").open("a", encoding="utf-8", newline="") as saved:
            saved.write("ignored_helper.py\n")
        (self.work / "ignored_helper.py").write_text("value = 1\n", encoding="utf-8", newline="")
        (self.work / "test_environment.py").write_text(
            "from ignored_helper import value\ndef test_value():\n    assert value == 1\n",
            encoding="utf-8", newline="")
        git(self.work, "add", ".gitignore", "test_environment.py")
        git(self.work, "commit", "-qm", "ignored dependency acceptance")
        out = self.checked(command=f'"{sys.executable}" -m pytest -q -p no:cacheprovider test_environment.py')
        rec = self.rec(out["run_id"])
        assert out["check"]["passed"] and rec["check_baseline"]["check"]["exit"] == 2
        assert out["check"]["sensitivity"] == "unknown"

    def test_no_check_does_not_run_baseline(self):
        self.j("config", "set", "check.sensitivity", "escalate")
        out = self.j("run", "--from", "claude", "--to", "codex", "--tier", "T1", "--new",
                     "--mode", "write", "--review", "off", "--no-fallback", "fix state.txt",
                     env={"FAKE_WRITE": "state.txt=fixed"})
        rec = self.rec(out["run_id"])
        assert out["check_sensitivity"] == "unknown"
        assert "check_baseline_start" not in rec and "check_baseline" not in rec
