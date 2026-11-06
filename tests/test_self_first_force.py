"""User-force provenance, covering all five internal routing force sources."""
import json
from unittest.mock import patch

import pytest

from ccx import cli
from ccx.commands import common, memory as memory_commands
from ccx.config import Paths, load_config
from ccx.self_first import decision
from test_discuss import DiscussEnv


@pytest.fixture
def gate_env(tmp_path, monkeypatch):
    p = Paths(tmp_path / "hub")
    cfg = load_config(p)
    cfg["routing"]["default"] = "self_first"
    monkeypatch.setattr(common, "_maybe_probe_claude", lambda *args: None)
    monkeypatch.setattr("ccx.self_first.context.lead_now", lambda *args: None)
    monkeypatch.setattr("ccx.self_first.quota.pressure", lambda *args: {})
    return p, cfg


@pytest.mark.parametrize("spec", [{"force": True}, {"force": True, "_self_first_force": True}])
def test_internal_force_never_qualifies_without_user_marker(gate_env, spec):
    p, cfg = gate_env
    out = decision(p, cfg, spec, "claude")
    assert out["forced"] is False
    assert out["applied"] and not out["eligible"]
    assert "--force override" not in out["why"]


@pytest.mark.parametrize("argv,expected", [
    (["run", "--force", "review a.py"], True),
    (["run", "--forc", "review a.py"], True),
    (["run", "--", "--force"], False),
    (["run", "review a.py"], False),
])
def test_only_cli_force_creates_positive_marker(argv, expected):
    args = cli.parse(argv)
    assert getattr(args, "_user_force", False) is expected
    spec = common._spec_from_args(args, "review a.py")
    assert spec.get("_user_force", False) is expected


def test_transcript_handoff_internal_force_does_not_launch(gate_env, tmp_path, monkeypatch):
    p, cfg = gate_env
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text("unparsed transcript", encoding="utf-8")
    monkeypatch.setattr(memory_commands, "_caller", lambda _: "claude")
    monkeypatch.setattr("ccx.config.load_config", lambda _: cfg)
    original, seen = common.resolve, []
    def capture(spec, caller, paths, config):
        result = original(spec, caller, paths, config)
        seen.append((spec, result))
        return result
    with patch.object(common, "resolve", side_effect=capture), patch("ccx.delegate.run") as launch:
        assert memory_commands._handoff_by_model(p, tmp_path, "claude", transcript) is None
    assert seen[0][0]["force"] is True
    kw, route = seen[0][1]
    assert kw is None
    assert route["self_first"]["forced"] is False
    launch.assert_not_called()


class TestForceSourcesCLI(DiscussEnv):
    def enable(self):
        self.j("config", "set", "routing.default", "self_first")

    def test_queue_piece_records_explicit_queue_request(self):
        self.enable()
        self.j("q", "add", "inspect parser", "--brief", "review a.py", "--mode", "read", "--minutes", "5")
        out = self.j("q", "run", "--from", "claude")
        record = json.loads((self.hub / "ccx" / "runs" / out["results"][0]["run"] / "run.json")
                            .read_text(encoding="utf-8"))
        gate = record["route"]["self_first"]
        assert gate["forced"] is False
        assert gate["checks"]["explicit_request"] is True
        assert gate["checks"]["explicit_request_source"] == "queue"
        assert "source=queue" in gate["why"]
        assert "--force override" not in gate["why"]

    def test_advisory_role_and_rubric_force_is_not_user_force(self):
        self.enable()
        self.j("roles", "set", "build", "codex:gpt-6.1-sol:auto")
        for extra in ((), ("--role", "build")):
            for command in ("route", "propose"):
                out = self.j(command, "--b", "4", "--lead", "claude:opus:high", "--lead-ctx", "0", *extra)
                assert out["self_first"]["forced"] is False
                assert "--force override" not in out["self_first"]["why"]
                assert out["self_first"]["eligible"] is bool(extra)

    def test_user_force_still_records_override(self):
        self.enable()
        out = self.j("run", "--from", "claude", "--tier", "T1", "--mode", "read", "--force", "review a.py")
        gate = out["route"]["self_first"]
        assert gate["forced"] is True
        assert "--force override" in gate["why"]

    def test_queue_cli_force_marker_survives_refill_and_warm_lanes(self):
        self.enable()
        for lanes in (0, 1):
            self.j("q", "add", "inspect parser", "--brief", "review a.py", "--mode", "read", "--minutes", "5")
            out = self.j("q", "run", "--from", "claude", "--force", "--lanes", str(lanes))
            record = json.loads((self.hub / "ccx" / "runs" / out["results"][0]["run"] / "run.json")
                                .read_text(encoding="utf-8"))
            gate = record["route"]["self_first"]
            assert gate["forced"] is True
            assert gate["checks"]["explicit_request_source"] == "queue"

    def test_batch_plan_force_is_not_cli_force(self):
        self.enable()
        plan_file = self.work / "plan.json"
        plan_file.write_text(json.dumps({"tasks": [{"id": "a", "brief": "review a.py", "mode": "read",
                                                    "tier": "T1", "force": True}]}), encoding="utf-8")
        out = self.j("batch", str(plan_file), "--from", "claude")
        assert out["results"] == []
        assert self.calls() == []
        out = self.j("batch", str(plan_file), "--from", "claude", "--force")
        record = json.loads((self.hub / "ccx" / "runs" / out["results"][0]["run_id"] / "run.json")
                            .read_text(encoding="utf-8"))
        assert record["route"]["self_first"]["forced"] is True
        assert "--force override" in record["route"]["self_first"]["why"]
