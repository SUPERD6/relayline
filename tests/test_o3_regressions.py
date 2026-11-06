"""Review regressions; subprocess cases use only fake CLIs in disposable repos."""
import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from ccx import dispatch, relay, relay_state, review_pipeline
from ccx.relay_lock import WorkspaceLock, known_writers
import test_relay
import test_dispatch


class TestHookRegressions(test_relay.TestRelay):
    def test_utf8_bom_hook_outside_repo(self):
        self.enable()
        event = {"hook_event_name": "StopFailure", "error": "rate_limit", "cwd": str(self.work),
                 "session_id": "中文会话", "error_details": "usage limit reached"}
        # Force a legacy text decoder; the hook must read the BOM-prefixed UTF-8 bytes.
        r = self.ccx("relay", "capture", "--hook", stdin="\ufeff" + json.dumps(event, ensure_ascii=False),
                     env={"PYTHONIOENCODING": "ascii"})
        assert r.returncode == 0, r.stdout + r.stderr
        packet_id = json.loads(r.stdout)["relay"]["packet"]
        packet = json.loads((self.work / ".ccx/relay" / (packet_id + ".json")).read_text(encoding="utf-8"))
        assert packet["source_session"] == "中文会话"

    def test_subagent_hook_returns_before_json(self):
        self.enable()
        for env in ({"CCX_DEPTH": "1"}, {"CCX_ROLE": "subagent"}):
            result = self.ccx("relay", "capture", "--hook", stdin="invalid json", env=env)
            assert (result.returncode, result.stdout) == (0, "")

    def test_popen_failure_releases_both_locks(self):
        self.enable()
        packet = self.capture()
        _, captured = relay_state.load_packet(self.work.resolve(), packet)
        with patch("ccx.relay.subprocess.Popen", side_effect=OSError("fake spawn failure")), \
                patch("ccx.relay.state.snapshot", return_value=captured["git"]), \
                patch("ccx.relay.known_writers", return_value={"known_live_writers": []}):
            with pytest.raises(OSError):
                relay.continue_packet(self.work.resolve(), packet, "codex", 30, True, True)
        assert not list((self.work / ".ccx/relay").glob("*.launch-lock"))

    def test_different_packets_share_workspace_lock(self):
        self.enable()
        first, second = self.capture(), self.capture()
        lock = WorkspaceLock(self.work / ".ccx/relay")
        lock.acquire()
        try:
            for packet in (first, second):
                with pytest.raises(ValueError, match="workspace relay lock is active"):
                    relay.continue_packet(self.work.resolve(), packet, "codex", 30, True, True)
        finally:
            lock.release()


class TestIndependentDispatch(test_dispatch.TestDispatchCommand):
    def test_cheap_cli_error_without_session_escalates(self):
        from test_ccx import FAKES
        self.enable()
        self.env["CCX_CODEX_BIN"] = str(FAKES / "fake_dispatch_error.py")
        result = self.checked(extra="passbase")
        record = self.rec(result["run_id"])
        assert [a["tier"] for a in record["attempts"]] == ["T1", "T2"]
        assert record["dispatch"]["escalated"] == 1

    def test_passing_edited_test_escalates_cheap_attempt(self):
        self.enable()
        (self.work / "test_acceptance.py").write_text("def test_acceptance():\n    assert True\n", encoding="utf-8")
        from test_check_baseline import git
        git(self.work, "add", "test_acceptance.py")
        git(self.work, "commit", "-qm", "acceptance")
        import sys
        result = self.j("run", "--from", "claude", "--to", "codex", "--tier", "T2", "--new", "--review", "off",
                        "--no-fallback", "--check", f'"{sys.executable}" -m pytest -q -p no:cacheprovider test_acceptance.py',
                        "fix state.txt", env={"FAKE_WRITE": "test_acceptance.py=def test_acceptance():\n    assert 1 == 1\n",
                                               "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"})
        record = self.rec(result["run_id"])
        assert [a["tier"] for a in record["attempts"]] == ["T1", "T2"]
        assert record["attempts"][0]["kind"] == "ok_self_checked"
        assert record["dispatch"]["escalated"] == 1


@pytest.mark.parametrize("covers", [{"edited": ["test_a.py"]}, {"written": ["test_a.py"]},
                                    {"added_to": ["test_a.py"]}])
def test_mixed_test_basis_is_not_independent(covers):
    assert dispatch.tainted({"files": ["test_a.py", "test_independent.py"], **covers})


@pytest.mark.parametrize("kind,expected", [("error", True), ("timeout", True), ("auth", False), ("env", False)])
def test_cli_retry_policy_without_a_clock(kind, expected):
    assert dispatch.retry_cli(False, kind) is expected
    assert not dispatch.retry_cli(True, kind)


def test_filtered_check_cannot_claim_file_verified():
    record = {"check": {"passed": True, "covers": {"files": ["test_a.py"], "filtered": ["-k one"]}}}
    assert review_pipeline.evidence(record)["evidence_level"] == "unverified"


@pytest.mark.parametrize("data", [{}, {"hooks": {}}, {"hooks": {"StopFailure": []}},
                                    {"hooks": {"StopFailure": [None, 1, "foreign"]}}, {"hooks": []}])
def test_disabled_hook_preserves_foreign_structure(data):
    before = json.dumps(data)
    assert not relay.sync_hook(data, False, "unused")
    assert json.dumps(data) == before


def test_removing_only_owned_hook_leaves_no_empty_hooks():
    data = {"hooks": {"StopFailure": [{"hooks": [{"command": "ccx relay capture --hook"}]}]}}
    assert relay.sync_hook(data, False, "")
    assert data == {}


def test_stale_workspace_lock_is_identified_without_unsafe_reclaim(tmp_path):
    lock = WorkspaceLock(tmp_path)
    lock.path.write_text(json.dumps({"pid": 999999, "created_at": 1}), encoding="utf-8")
    with patch("ccx.relay_lock.pid_alive", return_value=False), pytest.raises(ValueError, match="stale"):
        lock.acquire()


@pytest.mark.parametrize("nested", [False, True])
def test_known_live_writer_in_same_workspace_blocks(tmp_path, nested):
    from types import SimpleNamespace
    path = tmp_path / "runs/one/run.json"
    path.parent.mkdir(parents=True)
    work = tmp_path / "src" if nested else tmp_path
    work.mkdir(exist_ok=True)
    path.write_text(json.dumps({"cwd": str(work), "state": "running", "pid": 1234}), encoding="utf-8")
    with patch("ccx.relay_lock.paths", return_value=SimpleNamespace(runs=tmp_path / "runs")), \
            patch("ccx.relay_lock.pid_alive", return_value=True):
        assert known_writers(tmp_path)["known_live_writers"] == [{"run": "one", "pid": 1234}]


class TestSnapshotRegressions(test_relay.TestRelay):
    def test_same_line_dirty_and_existing_untracked_edits_have_distinct_fingerprints(self):
        for name in ("tracked.txt", "untracked.txt"):
            path = self.work / name
            path.write_text("first\n", encoding="utf-8")
            before = relay_state.snapshot(self.work)
            path.write_text("other\n", encoding="utf-8")
            after = relay_state.snapshot(self.work)
            assert before["uncommitted"] == after["uncommitted"]
            assert before["diffstat"] == after["diffstat"]
            assert before["content_fingerprint"] != after["content_fingerprint"]

    def test_packets_do_not_store_secret_diff_and_bound_context(self):
        self.enable()
        (self.work / "tracked.txt").write_text("PRIVATE_FAKE_KEY_MUST_NOT_PERSIST\n", encoding="utf-8")
        path, packet = relay_state.capture(self.work, "claude", "sid", {}, {"goal": "a" * 20000})
        assert "PRIVATE_FAKE_KEY_MUST_NOT_PERSIST" not in path.read_text(encoding="utf-8")
        assert "diff" not in packet["git"] and "staged_diff" not in packet["git"]
        assert "tracked.txt" in packet["git"]["diffstat"]
        assert len(packet["goal"]) == 4096

    def test_capture_timeout_writes_minimal_packet(self):
        with patch("ccx.relay_state.git", side_effect=subprocess.TimeoutExpired("git", 2)):
            path, packet = relay_state.capture(self.work, "claude", "sid", {}, {})
        assert path.exists()
        assert packet["git"]["head"] == "Unknown"
        assert packet["git"]["snapshot_status"] == "Unknown"

    def test_storage_ignored_without_repository_ignore(self):
        (self.work / ".gitignore").write_text("", encoding="utf-8")
        path, _ = relay_state.capture(self.work, "claude", "sid", {}, {})
        assert self.git("check-ignore", str(path)).strip()

    def test_claude_permission_argv_and_zero_exit_without_edits(self):
        from test_ccx import FAKES
        self.enable()
        packet = self.capture(source="codex")
        result = self.ccx("relay", "continue", packet, "--to", "claude", "--budget-seconds", "30",
                          "--old-stopped", "--launch", env={"CCX_CLAUDE_BIN": str(FAKES / "fake_relay_no_changes.py")})
        assert result.returncode == 2, result.stdout + result.stderr
        record = json.loads(result.stdout)
        assert record["state"] == "no_changes"
        assert record["changes_observed"] is False
        argv = record["argv"]
        assert argv[argv.index("--permission-mode") + 1] == "acceptEdits"
        assert argv[argv.index("--permission-prompts") + 1] == "none"


@pytest.mark.parametrize("sample,kind", [
    # Synthetic Codex wording; not captured from a real quota refusal.
    ({"type": "error", "message": "You've hit your usage limit. Try again later."}, "quota"),
    ({"type": "error", "error": {"code": "billing_error", "message": "usage limit reached"}}, "billing"),
])
def test_additional_quota_wording_and_billing(sample, kind):
    from ccx.quota_signals import identify
    assert identify(sample)["kind"] == kind


def test_semantic_batch_unknown_layout_fails_closed_without_launch(tmp_path):
    from ccx.contract_semantic import generate_semantic
    with patch("ccx.contract_semantic.subprocess.run") as run:
        result = generate_semantic({"task": "Return 2.", "user_words": "Return 2."}, budget=.1,
                                   cli=[str(tmp_path / "claude.cmd")])
    run.assert_not_called()
    assert result["exit_code"] is None
    assert result["contract"]["unknown_reasons"]


def test_semantic_npm_shim_uses_direct_node_preserving_arguments(tmp_path):
    from ccx.semantic_cli import direct_argv
    script = tmp_path / "node_modules/@anthropic-ai/claude-code/cli.js"
    script.parent.mkdir(parents=True)
    script.touch()
    (tmp_path / "node.exe").touch()
    argv = [str(tmp_path / "claude.cmd"), "--tools", "", "--json-schema", '{"type":"object"}']
    result = direct_argv(argv)
    assert result == [str(tmp_path / "node.exe"), str(script), *argv[1:]]


@pytest.mark.parametrize("directory", [".codex", ".CODEX", ".Claude", ".ccx"])
def test_fingerprint_does_not_read_nested_private_directory(tmp_path, directory):
    secret = tmp_path / "nested" / directory / "data"
    secret.parent.mkdir(parents=True)
    secret.write_text("private", encoding="utf-8")
    with patch("pathlib.Path.open", side_effect=AssertionError("must not read")):
        assert relay_state.fingerprint(tmp_path, [f"nested/{directory}/data"], float("inf")) == "Unknown"
