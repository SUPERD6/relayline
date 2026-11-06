"""Review regressions: independent task parts, missing quota windows, context provenance."""
from unittest.mock import patch

import pytest

from ccx import cli
from ccx.commands import delegation
from ccx.config import Paths, load_config
from ccx.self_first import decision
from test_discuss import DiscussEnv


@pytest.fixture
def gate_env(tmp_path):
    p = Paths(tmp_path / "hub")
    cfg = load_config(p)
    cfg["routing"]["default"] = "self_first"
    return p, cfg


@pytest.mark.parametrize("spec,eligible", [({"parallel": True}, False),
                                          ({"independent_parts": True}, True)])
def test_only_independent_parts_satisfies_parallel_condition(gate_env, spec, eligible):
    p, cfg = gate_env
    with patch("ccx.self_first.context.lead_now", return_value=None), \
            patch("ccx.self_first.quota.pressure", return_value={}):
        out = decision(p, cfg, spec, "claude")
    assert out["eligible"] is eligible
    assert out["checks"]["parallel"] is eligible
    assert out["matched"] == (["parallel"] if eligible else [])


@pytest.mark.parametrize("used,expected", [(0.4, False), (0.9, True), (None, "Unknown")])
def test_quota_missing_windows_are_visible_with_partial_readings(gate_env, used, expected):
    p, cfg = gate_env
    windows = {"five_hour": {"used": None, "projected": 0.0},
               "seven_day": {"used": used, "projected": used}}
    with patch("ccx.self_first.quota.pressure", return_value={"pace": {"claude": windows}}):
        out = decision(p, cfg, {"lead_ctx": 0}, "claude")
    assert out["checks"]["quota_tight"] == expected
    assert out["checks"]["quota_missing"] == (["five_hour", "seven_day"] if used is None else ["five_hour"])
    assert out["eligible"] is (expected is True)


@pytest.mark.parametrize("source,expected", [("given", True), ("lead_session", True),
                                            ("none", False), (None, False),
                                            ("estimate", False), ("default", False)])
def test_route_reuses_only_known_context_sources(gate_env, monkeypatch, source, expected):
    p, cfg = gate_env
    args = cli.parse(["route", "--b", "4", "--lead", "claude:opus:high"])
    monkeypatch.setattr(delegation, "paths", lambda: p)
    monkeypatch.setattr(delegation, "load_config", lambda _: cfg)
    monkeypatch.setattr(delegation, "_route_pick", lambda _: {
        "self_vs_delegate": {"ctx_source": source, "lead_ctx_tokens": 200000}})
    with patch("ccx.self_first.context.lead_now", return_value=None), \
            patch("ccx.self_first.quota.pressure", return_value={}):
        out = delegation._route(args)["self_first"]
    assert out["eligible"] is expected
    assert out["checks"]["large_context"] == (True if expected else "Unknown")
    assert out["lead_ctx_tokens"] == (200000 if expected else None)


class TestIndependentPartsCLI(DiscussEnv):
    def test_new_signal_through_route_propose_and_run(self):
        self.j("config", "set", "routing.default", "self_first")
        for command in ("route", "propose"):
            out = self.j(command, "--b", "4", "--lead", "claude:opus:high", "--lead-ctx", "0",
                         "--independent-parts", "review a.py and b.py")
            assert out["self_first"]["matched"] == ["parallel"]
        out = self.j("run", "--from", "claude", "--tier", "T1", "--mode", "read",
                     "--independent-parts", "review a.py and b.py")
        assert out["status"] == "done"
        assert out["route"]["self_first"]["matched"] == ["parallel"]
        assert "You are explicitly asked to use sub-agents" not in self.calls()[-1]["prompt"]

    def test_parallel_alone_does_not_open_gate_or_start_cli(self):
        self.j("config", "set", "routing.default", "self_first")
        out = self.j("route", "--b", "4", "--parallel")
        assert out["self_first"]["applied"]
        out = self.j("run", "--from", "claude", "--tier", "T1", "--mode", "read",
                     "--parallel", "review a.py")
        assert out["delegated"] is False
        assert out["route"]["self_first"]["checks"]["parallel"] is False
        assert self.calls() == []

    def test_both_flags_keep_child_parallel_behavior(self):
        self.j("config", "set", "routing.default", "self_first")
        out = self.j("run", "--from", "claude", "--tier", "T1", "--mode", "read", "--parallel",
                     "--independent-parts", "review a.py and b.py")
        assert out["status"] == "done"
        assert out["route"]["self_first"]["matched"] == ["parallel"]
        assert "You are explicitly asked to use sub-agents" in self.calls()[-1]["prompt"]
