"""#286 opt-in self-first gating; subprocess CLI checks use isolated fake tool homes."""
import json
from unittest.mock import patch

import pytest

from ccx.config import Paths, load_config
from ccx.self_first import decision
from test_discuss import DiscussEnv


@pytest.fixture
def gate_env(tmp_path):
    p = Paths(tmp_path / "hub")
    cfg = load_config(p)
    cfg["routing"]["default"] = "self_first"
    return p, cfg


def test_auto_is_exact_noop_without_reading_context_or_quota(gate_env):
    p, cfg = gate_env
    for setting in (None, "auto"):
        if setting is None:
            cfg["routing"].pop("default")
        else:
            cfg["routing"]["default"] = setting
        with patch("ccx.self_first.context.lead_now", side_effect=AssertionError("read context")), \
                patch("ccx.self_first.quota.pressure", side_effect=AssertionError("read quota")):
            assert decision(p, cfg, {}, "claude") is None


@pytest.mark.parametrize("spec,matched", [
    ({"quota": {"claude": 0.81}}, "quota_tight"),
    ({"lead_ctx": 150000}, "large_context"),
    ({"to": "codex"}, "explicit_request"),
    ({"independent_parts": True}, "parallel"),
    ({"model": "sonnet"}, "explicit_request"),
    ({"role": "build"}, "explicit_request"),
])
def test_each_exception_is_visible(gate_env, spec, matched):
    p, cfg = gate_env
    with patch("ccx.self_first.context.lead_now", return_value=None), \
            patch("ccx.self_first.quota.pressure", return_value={}):
        out = decision(p, cfg, spec, "claude")
    assert out["eligible"] and not out["applied"]
    assert out["matched"] == [matched]
    assert matched in out["why"]


def test_unknown_is_not_tight_or_large(gate_env):
    p, cfg = gate_env
    with patch("ccx.self_first.context.lead_now", return_value=None), \
            patch("ccx.self_first.quota.pressure", return_value={}):
        out = decision(p, cfg, {"to": "auto"}, "claude")
    assert out["applied"] and not out["eligible"]
    assert out["checks"]["quota_tight"] == "Unknown"
    assert out["checks"]["large_context"] == "Unknown"


def test_cached_quota_projection_and_expired_window(gate_env):
    p, cfg = gate_env
    for window, expected in [({"used": 0.5, "projected": 1.1}, True),
                             ({"used": None, "projected": 1.1}, False),
                             ({"used": 0.8, "projected": 0.8}, False)]:
        with patch("ccx.self_first.quota.pressure", return_value={"pace": {"claude": {"week": window}}}):
            out = decision(p, cfg, {"lead_ctx": 0}, "claude")
        assert out["eligible"] is expected


def test_reuses_custom_thresholds_and_lead_session_context(gate_env):
    p, cfg = gate_env
    cfg["policy"]["bands"]["lead_ctx_large"] = 42
    cfg["quota"]["avoid_above"] = 0.6
    with patch("ccx.self_first.context.lead_now", return_value=42), \
            patch("ccx.self_first.quota.pressure", return_value={}):
        out = decision(p, cfg, {"quota": {"claude": 0.61}}, "claude")
    assert out["matched"] == ["quota_tight", "large_context"]


def test_clean_lead_view_keeps_condition_evidence():
    from ccx import leadview
    from test_leadview import PASSED
    route = {"self_first": {"checks": {"parallel": True}, "matched": ["parallel"], "eligible": True}}
    out = leadview.line({**PASSED, "route": route})
    assert out["route"] == route


class TestSelfFirstCLI(DiscussEnv):
    def enable(self):
        self.j("config", "set", "routing.default", "self_first")

    def test_default_auto_preserves_route_and_run(self):
        assert self.j("config", "get", "routing.default")["routing.default"] == "auto"
        baseline = self.j("route", "--b", "4", "--files", "3")
        self.j("config", "set", "routing.default", "auto")
        assert self.j("route", "--b", "4", "--files", "3") == baseline
        assert "self_first" not in baseline
        out = self.j("run", "--from", "claude", "--tier", "T1", "--mode", "read", "review a.py")
        assert out["status"] == "done"
        assert "self_first" not in out["route"]

    def test_config_round_trip_and_invalid_value(self):
        self.enable()
        assert self.j("config", "get", "routing.default")["routing.default"] == "self_first"
        self.j("config", "set", "routing.default", "never", code=3)
        assert self.j("config", "get", "routing.default")["routing.default"] == "self_first"

    def test_route_rubric_and_keywords_prefer_self_even_for_large_task(self):
        self.enable()
        from ccx.commands.delegation import _route_summary
        for args in (("--b", "4", "--files", "9"), ("implement the parser across nine modules",)):
            out = self.j("route", *args)
            assert out["self_first"]["applied"]
            assert out["advice"].startswith("do-it-yourself")
            assert _route_summary(out)[-1] == "Next: do it yourself"

    def test_four_exceptions_through_route_cli(self):
        self.enable()
        for args, expected in [(("--quota", "claude=0.81"), "quota_tight"),
                               (("--lead-ctx", "150000"), "large_context"),
                               (("--to", "codex"), "explicit_request"),
                               (("--independent-parts",), "parallel")]:
            out = self.j("route", "--b", "4", "--lead", "claude:opus:high", *args)
            assert expected in out["self_first"]["matched"]
            assert out["self_first"]["eligible"]

    def test_propose_does_not_offer_or_preauthorize_without_condition(self):
        self.enable()
        self.j("config", "set", "policy.picked", "save")
        out = self.j("propose", "--b", "4", "--files", "3", "--lead", "claude:opus:high",
                     "--lead-ctx", "0", "add the parser")
        assert (out["worth_offering"], out["authorized"], out["recommend"]) == (False, False, "self")
        assert out["say"] is None
        rows = [json.loads(line) for line in (self.hub / "ccx" / "ledger.jsonl").read_text(encoding="utf-8").splitlines()]
        row = next(row for row in rows if row.get("proposal") == out["proposal"])
        assert row["self_first"]["applied"]
        assert "preauthorized" not in row

    def test_proposal_explicit_assignment_keeps_existing_tier_authorization(self):
        self.enable()
        self.j("config", "set", "policy.picked", "save")
        out = self.j("propose", "--b", "4", "--files", "3", "--lead", "claude:opus:high",
                     "--lead-ctx", "0", "--to", "codex", "add the parser")
        assert out["authorized"]
        assert out["self_first"]["matched"] == ["explicit_request"]

    def test_run_refusal_starts_no_cli_then_explicit_and_parallel_run(self):
        self.enable()
        args = ("run", "--from", "claude", "--tier", "T1", "--mode", "read")
        out = self.j(*args, "review a.py")
        assert out["delegated"] is False
        assert out["route"]["self_first"]["applied"]
        assert self.calls() == []
        for extra, expected in [(("--to", "codex"), "explicit_request"), (("--independent-parts",), "parallel")]:
            out = self.j(*args, *extra, "review a.py")
            assert out["status"] == "done"
            assert expected in out["route"]["self_first"]["matched"]

    def test_run_reuses_explicit_lead_quota(self):
        self.enable()
        out = self.j("run", "--from", "claude", "--tier", "T1", "--quota", "claude=0.81",
                     "--mode", "read", "review a.py")
        assert out["status"] == "done"
        assert out["route"]["self_first"]["matched"] == ["quota_tight"]

    def test_fixed_role_reports_explicit_assignment_and_actual_force(self):
        self.enable()
        self.j("roles", "set", "build", "codex:gpt-6.1-sol:auto")
        for forced in (False, True):
            extra = ("--force",) if forced else ()
            out = self.j("run", "--from", "claude", "--role", "build", "--tier", "T1",
                         "--mode", "read", "--review", "off", *extra, "review a.py")
            assert out["status"] == "done"
            gate = out["route"]["self_first"]
            assert gate["forced"] is forced
            assert gate["matched"] == ["explicit_request"]
            assert "explicit_request" in gate["why"]
            assert "--force override" not in gate["why"]

    def test_routing_off_still_wins_and_force_keeps_override(self):
        self.enable()
        out = self.j("run", "--from", "claude", "--tier", "T1", "--force", "--mode", "read", "review a.py")
        assert out["status"] == "done"
        assert out["route"]["self_first"]["forced"]
        self.j("config", "set", "routing.mode", "off")
        out = self.j("route", "--b", "4", "--parallel")
        assert out["routing_mode"] == "off"
        assert "self_first" not in out
