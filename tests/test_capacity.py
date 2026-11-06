"""Capacity recovery uses synthetic signals and fake CLI subprocesses, never real CLIs."""
import json

import pytest

from ccx import capacity
from ccx.config import Paths, load_config
from ccx.quota_signals import identify
from ccx.runners import Outcome
from test_adapters import AdapterEnv
from test_ccx import FAKES


@pytest.mark.parametrize("sample", [
    "Selected model is at capacity. Please try again later.",
    "Model is overloaded", "API Error: 503: Selected model is at capacity",
    {"type": "turn.failed", "error": {"message": "Selected model is at capacity"}},
    {"type": "error", "error": {"code": "overloaded_error"}},
    {"type": "error", "error": {"code": "server_error", "message": "Selected model is at capacity"}},
    {"type": "result", "is_error": True, "errors": ["Selected model is at capacity"]},
])
def test_capacity_identification(sample):
    assert identify(sample)["kind"] == "capacity"


@pytest.mark.parametrize("sample", [
    "429 Too Many Requests", "usage limit reached", "401 Selected model is at capacity",
    "network error: Selected model is at capacity", "exhausted your capacity",
    {"type": "assistant", "message": "Selected model is at capacity"},
    {"type": "result", "result": "Selected model is at capacity"},
    {"type": "item.completed", "item": {"type": "command_execution", "output": "Selected model is at capacity"}},
    {"type": "error", "error": {"code": "network_error", "message": "Selected model is at capacity"}},
    {"type": "error", "error": {"code": "authentication_failed", "message": "Selected model is at capacity"}},
    {"type": "turn.failed", "error": {"code": "usage_limit_reached", "message": "Selected model is at capacity"}},
])
def test_other_signals_are_not_capacity(sample):
    assert identify(sample)["kind"] != "capacity"


def test_success_and_explicit_other_failures_do_not_trigger_recovery():
    for outcome in (Outcome(ok=True), Outcome(ok=False, kind="auth"), Outcome(ok=False, kind="timeout")):
        assert capacity.signal({}, outcome, "", "Selected model is at capacity") is None
    assert capacity.signal({}, Outcome(ok=False), json.dumps({
        "type": "error", "error": {"code": "network_error"}}), "Selected model is at capacity") is None
    mixed = '\n'.join(json.dumps(v) for v in (
        {"type": "error", "message": "Selected model is at capacity"},
        {"type": "error", "error": {"code": "authentication_failed"}}))
    assert capacity.signal({}, Outcome(ok=False), mixed, "") is None


def test_capacity_is_not_learned_as_an_ability_failure(monkeypatch, tmp_path):
    from ccx import learn

    class Routing:
        @staticmethod
        def load_priors():
            return {}

        @staticmethod
        def load_state():
            return {}

    monkeypatch.setattr(learn, "module", lambda *args: Routing())
    # With no eligible attempts, no ability record is written.
    record = {"route": {"b": 1}, "attempts": [
        {"agent": "codex", "model": "gpt-6.1-sol", "kind": "capacity"}]}
    assert learn.record_outcomes(Paths(tmp_path), record, final_ok=False) == []


def test_capacity_fallback_respects_daily_budget(monkeypatch, tmp_path):
    from ccx import plan
    from ccx.delegate import Request

    cfg = load_config(Paths(tmp_path))
    failed = {"agent": "codex", "model": "gpt-6.1-sol", "rung": "codex:gpt-6.1-sol:medium"}
    target = {"agent": "claude", "model": "sonnet", "effort": "medium", "rung": "claude:sonnet:medium"}
    monkeypatch.setattr(plan, "_fallback_plan", lambda *args: target)
    monkeypatch.setattr(plan, "_usable", lambda p, spec: spec)
    monkeypatch.setattr(plan, "_provider_envs", lambda *args: {})

    def exhausted(*args):
        raise ValueError("daily cap reached")

    monkeypatch.setattr(plan, "_within_budget", exhausted)
    req = Request(caller="user", to="codex", brief="read", cwd=tmp_path)
    assert capacity.next_plan(req, Paths(tmp_path), cfg, [failed], 0,
                              [{**failed, "kind": "capacity"}], False) == ([], None, False)


class TestCapacityCommand(AdapterEnv):
    def setUp(self):
        super().setUp()
        self.env["CCX_CODEX_BIN"] = str(FAKES / "fake_capacity.py")
        self.env["FAKE_CAPACITY_MODELS"] = "gpt-6.1-sol"

    def run_capacity(self, *options, code=0):
        # Env.ccx launches the actual entry point as a subprocess outside the checkout.
        r = self.ccx("run", "--from", "user", "--to", "codex", "--tier", "T2", "--mode", "read",
                     "--new", "--context", "off", "--no-ab", "--review", "off", *options, "Read the parser")
        assert r.returncode == code, r.stdout + r.stderr
        out = json.loads(r.stdout)
        return out, self.rec(out["run_id"])

    def test_same_model_other_effort_is_skipped_for_other_vendor(self):
        out, rec = self.run_capacity()
        assert [(a["agent"], a["kind"]) for a in rec["attempts"]] == [("codex", "capacity"), ("claude", "ok")]
        assert out["capacity_recovery"][0]["reason"] == "model_at_capacity"
        assert rec["attempts"][0]["capacity_stop"]["source"] == "explicit_capacity_text"
        assert "quota_stop" not in rec and "quota_fallback" not in rec
        assert "resume" not in self.calls()[-1]["argv"]
        shown = self.j("show", out["run_id"])
        assert shown["capacity_recovery"] == out["capacity_recovery"]
        from ccx import leadview
        assert leadview.line({**out, "check": {}})["capacity_recovery"] == out["capacity_recovery"]

    def test_existing_ladder_tries_different_model_in_fresh_session(self):
        self.j("config", "set", "defaults.max_escalations", "2")
        out, rec = self.run_capacity("--no-fallback")
        assert [a["model"] for a in rec["attempts"]] == ["gpt-6.1-sol", "gpt-6-astra"]
        assert out["status"] == "done"
        assert "resume" not in self.calls()[-1]["argv"]

    def test_no_fallback_stops_if_only_same_model_is_left(self):
        out, rec = self.run_capacity("--no-fallback", code=2)
        assert len(rec["attempts"]) == 1
        assert out["kind"] == "capacity"
        assert out["capacity_recovery"][-1]["action"] == "stop"

    def test_switches_are_bounded(self):
        self.env["FAKE_CAPACITY_MODELS"] = "all"
        self.j("config", "set", "defaults.max_escalations", "3")
        out, rec = self.run_capacity("--tier", "T1", code=2)
        assert [a["model"] for a in rec["attempts"]] == ["gpt-6-luna", "gpt-6.1-sol", "gpt-6-astra"]
        assert out["kind"] == "capacity" and out["capacity_recovery"][-1]["action"] == "stop"

    def test_disable_restores_legacy_retry(self):
        self.j("config", "set", "defaults.capacity_fallback", "false")
        out, rec = self.run_capacity("--no-fallback", code=2)
        assert [a["kind"] for a in rec["attempts"]] == ["error", "error"]
        assert "capacity_recovery" not in out

    def test_no_escalate_keeps_cross_vendor_fallback(self):
        out, rec = self.run_capacity("--no-escalate")
        assert [a["agent"] for a in rec["attempts"]] == ["codex", "claude"]
        assert out["status"] == "done"
