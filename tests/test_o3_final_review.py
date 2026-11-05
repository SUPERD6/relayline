"""Final review regressions: deterministic mocks and actual ccx processes with fake CLIs only."""
import io
import json
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from ccx import delegate, relay, relay_state
from ccx.commands import relay as relay_command
from ccx.config import Paths
import test_relay


@pytest.fixture
def relay_env():
    env = test_relay.TestRelay(methodName="runTest")
    env.setUp()
    try:
        yield env
    finally:
        env.tearDown()


@pytest.mark.parametrize("failure", ["no_snapshot", "missing_command", "namecheck", "changes_error",
                                     "coverage_unknown", "coverage_partial"])
def test_unknown_check_basis_escalates_only_cheap_dispatch(tmp_path, failure):
    snapshot = None if failure == "no_snapshot" else {"repo": str(tmp_path)}
    check = {} if failure == "missing_command" else {"cmd": "python -m pytest test_a.py"}
    if failure == "namecheck":
        check["reason"] = "namecheck"
    covers = ({"unknown": "cannot resolve"} if failure == "coverage_unknown" else
              {"files": ["test_a.py"], "partial": True} if failure == "coverage_partial" else {"files": ["test_a.py"]})
    with patch("ccx.delegate.run_snapshot", return_value=snapshot), \
            patch("ccx.review.changes", side_effect=RuntimeError("unavailable") if failure == "changes_error" else None,
                  return_value=(None, "")), \
            patch("ccx.coverage.summarize", return_value=covers):
        assert delegate._self_checked_now(Paths(tmp_path), {}, tmp_path, check, independent=True) is True
        assert delegate._self_checked_now(Paths(tmp_path), {}, tmp_path, check) is False


def test_known_independent_check_is_not_tainted(tmp_path):
    with patch("ccx.delegate.run_snapshot", return_value={"repo": str(tmp_path)}), \
            patch("ccx.review.changes", return_value=(None, "")), \
            patch("ccx.coverage.summarize", return_value={"files": ["test_a.py"]}):
        assert delegate._self_checked_now(Paths(tmp_path), {}, tmp_path,
                                          {"cmd": "python -m pytest test_a.py"}, independent=True) is False


def test_unknown_changes_exit_nonzero_through_cli(relay_env):
    env = relay_env
    env.enable()
    packet = env.capture()
    # Exceed the fingerprint bound deterministically; no sleep or slow filesystem is needed.
    (env.work / "large.dat").write_bytes(b"x" * (8 * 1024 * 1024 + 1))
    result = env.ccx("relay", "continue", packet, "--to", "codex", "--budget-seconds", "30",
                     "--old-stopped", "--launch")
    assert result.returncode == 2, result.stdout + result.stderr
    record = json.loads(result.stdout)
    assert record["changes_observed"] == "Unknown"
    assert record["state"] == "changes_unknown"
    assert "git status" in record["message"]
    assert record["exit_code"] == 0  # child exit remains distinct from ccx command exit


def test_continue_git_timeout_and_claude_permission_scope_through_cli(relay_env):
    env = relay_env
    env.enable()
    packet = env.capture(source="codex")
    result = env.ccx("relay", "continue", packet, "--to", "claude", "--budget-seconds", "30",
                     "--old-stopped", "--git-timeout-seconds", "45")
    assert result.returncode == 0, result.stdout + result.stderr
    record = json.loads(result.stdout)
    assert record["git_timeout_seconds"] == 45
    assert "no exact, trusted check commands" in record["prompt"]
    assert "tests are denied" in record["prompt"] and "tests as not-run" in record["prompt"]
    assert "--allowedTools" not in record["argv"]
    assert record["argv"][record["argv"].index("--permission-prompts") + 1] == "none"
    for value in ("0", "-1", "nan", "inf"):
        rejected = env.ccx("relay", "continue", packet, "--to", "claude", "--budget-seconds", "30",
                           "--old-stopped", "--git-timeout-seconds", value)
        assert rejected.returncode == 3


def test_new_handoff_inherits_manual_git_timeout(relay_env):
    from test_ccx import FAKES
    env = relay_env
    env.enable()
    packet = env.capture()
    with patch("ccx.relay.bin_argv", return_value=[sys.executable, str(FAKES / "fake_relay.py")]), \
            patch.dict("os.environ", {**env.env, "FAKE_RELAY_QUOTA": "1"}), \
            patch("ccx.relay.state.capture", wraps=relay_state.capture) as capture:
        result = relay.continue_packet(env.work.resolve(), packet, "codex", 30, True, True, git_timeout=45)
    assert result["state"] == "quota_stopped"
    assert capture.call_args.kwargs == {"command_timeout": 45, "total_timeout": 180}


def test_snapshot_short_capture_long_continue_without_clock(tmp_path):
    timeouts = []

    def simulated_git(cwd, *args, timeout=2):
        timeouts.append(timeout)
        if timeout <= 2:
            raise subprocess.TimeoutExpired("git", timeout)
        return "abc123\n" if args[0] == "rev-parse" else ""

    with patch("ccx.relay_state.git", side_effect=simulated_git):
        short = relay_state.snapshot(tmp_path)
        long = relay_state.snapshot(tmp_path, command_timeout=30, total_timeout=120)
    assert short["snapshot_status"] == "Unknown"
    assert "timed out" in short["snapshot_reason"]
    assert "--git-timeout-seconds 60" in short["retry_hint"]
    assert "snapshot_status" not in long and long["head"] == "abc123"
    assert timeouts == [2, 30, 30, 30, 30]


def test_unknown_snapshot_gives_reason_and_recapture_hint(relay_env):
    env = relay_env
    env.enable()
    packet = env.capture()
    unavailable = {"head": "Unknown", "snapshot_status": "Unknown", "snapshot_reason": "Git status timed out"}
    with patch("ccx.relay.state.snapshot", return_value=unavailable) as snapshot:
        with pytest.raises(ValueError, match="Git status timed out.*--git-timeout-seconds 60"):
            relay.continue_packet(env.work.resolve(), packet, "codex", 30, True)
    assert snapshot.call_args.kwargs == {"command_timeout": 30, "total_timeout": 120}


def test_hook_keeps_short_deadline_even_when_long_timeout_requested(tmp_path, capsys):
    args = SimpleNamespace(action="capture", hook=True, cwd=str(tmp_path), source="claude", session_id=None,
                           goal=None, progress=None, next_step=None, git_timeout_seconds=90)
    packet = {"id": "a" * 32, "state": "quota_stopped", "quota_signal": {"kind": "quota"},
              "continue_command": "ccx relay continue"}
    event = {"cwd": str(tmp_path), "hook_event_name": "StopFailure", "error": "rate_limit",
             "error_details": "usage limit reached"}
    with patch.dict("os.environ", {"CCX_DEPTH": "0", "CCX_ROLE": "lead"}), \
            patch("ccx.commands.relay.load_config", return_value={"relay": {"enabled": True}}), \
            patch("ccx.commands.relay.sys.stdin", io.StringIO(json.dumps(event))), \
            patch("ccx.commands.relay.state.root", return_value=tmp_path) as root, \
            patch("ccx.commands.relay.state.context_path", return_value=tmp_path / "missing.json"), \
            patch("ccx.commands.relay.state.capture", return_value=(tmp_path / "packet.json", packet)) as capture, \
            patch("ccx.commands.relay.state.atomic_json"):
        assert relay_command.command(args) == 0
    assert root.call_args.kwargs == {"timeout": 2}
    assert capture.call_args.kwargs == {"command_timeout": 2, "total_timeout": 6}
    assert json.loads(capsys.readouterr().out)["relay"]["state"] == "quota_stopped"
