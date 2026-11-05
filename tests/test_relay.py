"""Exercise real ccx subprocess entry points outside the repository with fake CLIs only."""
import json
import subprocess
from pathlib import Path
from unittest.mock import patch

from test_ccx import Env, FAKES
from ccx.config import Paths
from ccx.sync import Plan, sync_hooks
from ccx.relay import continue_packet, sync_hook


class TestRelay(Env):
    def setUp(self):
        super().setUp()
        self.env.update(CCX_CODEX_BIN=str(FAKES / "fake_relay.py"), CCX_CLAUDE_BIN=str(FAKES / "fake_relay.py"))
        self.git("init")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "user.name", "Test")
        (self.work / ".gitignore").write_text(".ccx/\n", encoding="utf-8")
        (self.work / "tracked.txt").write_text("initial\n", encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-m", "initial")

    def git(self, *args):
        r = subprocess.run(["git", *args], cwd=self.work, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def enable(self):
        r = self.ccx("config", "set", "relay.enabled", "true")
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)

    def capture(self, source="claude"):
        r = self.ccx("relay", "capture", "--goal", "finish parser", "--progress", "partial parser", "--next-step",
                     "run targeted tests", "--session-id", "session-1", "--source", source)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        return json.loads(r.stdout)["packet"]

    def test_disabled_no_hook_or_capture(self):
        sync_hooks(Paths(self.hub), Plan(apply=True))
        data = json.loads((self.home_claude / "settings.json").read_text(encoding="utf-8"))
        self.assertNotIn("StopFailure", data["hooks"])
        r = self.ccx("relay", "capture", "--hook", stdin="not even json")
        self.assertEqual((r.returncode, r.stdout), (0, ""))
        self.assertFalse((self.work / ".ccx" / "relay").exists())
        self.assertEqual(self.ccx("relay", "capture", "--goal", "x").returncode, 3)

    def test_real_managed_hook_command_outside_repo(self):
        self.enable()
        self.capture()
        sync_hooks(Paths(self.hub), Plan(apply=True))
        settings = self.home_claude / "settings.json"
        data = json.loads(settings.read_text(encoding="utf-8"))
        group = data["hooks"]["StopFailure"][0]
        self.assertEqual(group["matcher"], "rate_limit")
        event = {"hook_event_name": "StopFailure", "error": "rate_limit", "session_id": "session-1",
                 "cwd": str(self.work), "transcript_path": "deliberately-unreadable"}
        # Execute the exact installed command, with the platform's native shell, not its Python handler.
        r = subprocess.run(group["hooks"][0]["command"], shell=True, cwd=self.work, env=self.env,
                           input=json.dumps(event), capture_output=True, encoding="utf-8")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        notice = json.loads(r.stdout)
        packet = json.loads((self.work / ".ccx" / "relay" / (notice["relay"]["packet"] + ".json")).read_text(encoding="utf-8"))
        self.assertEqual(packet["goal"], "finish parser")
        self.assertEqual(packet["quota_signal"]["source"], "StopFailure")
        self.assertIn("terminalSequence", notice)
        self.assertTrue((self.work / ".ccx" / "relay" / (packet["id"] + ".notification.json")).exists())
        before = settings.read_bytes()
        sync_hooks(Paths(self.hub), Plan(apply=True))
        self.assertEqual(settings.read_bytes(), before)

    def test_continue_budget_stop_attestation_and_dirty_work(self):
        self.enable()
        (self.work / "tracked.txt").write_text("staged\n", encoding="utf-8")
        self.git("add", "tracked.txt")
        (self.work / "tracked.txt").write_text("unstaged\n", encoding="utf-8")
        packet = self.capture()
        self.assertEqual(self.ccx("relay", "continue", packet, "--to", "codex").returncode, 2)
        self.assertEqual(self.ccx("relay", "continue", packet, "--to", "codex", "--budget-seconds", "10").returncode, 3)
        args = ("relay", "continue", packet, "--to", "codex", "--budget-seconds", "30", "--old-stopped")
        prepared = self.ccx(*args)
        self.assertEqual(prepared.returncode, 0, prepared.stdout + prepared.stderr)
        self.assertEqual(json.loads(prepared.stdout)["state"], "prepared")
        self.assertFalse((self.work / "relay-fake-call.json").exists())
        for budget in ("0", "-1", "nan", "inf"):
            r = self.ccx("relay", "continue", packet, "--to", "codex", "--budget-seconds", budget, "--old-stopped")
            self.assertEqual(r.returncode, 3, r.stdout)
        staged, diff = self.git("diff", "--cached"), self.git("diff")
        r = self.ccx(*args, "--launch")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        call = json.loads((self.work / "relay-fake-call.json").read_text(encoding="utf-8"))
        self.assertEqual(call["argv"][:2], ["exec", "--json"])
        self.assertIn("git diff --cached", call["prompt"])
        self.assertEqual((self.git("diff", "--cached"), self.git("diff")), (staged, diff))
        self.assertEqual(self.ccx(*args, "--launch").returncode, 3)  # no duplicate writer

    def test_midprocess_death_preserves_partial_work_and_can_recapture(self):
        self.enable()
        packet = self.capture(source="codex")
        r = self.ccx("relay", "continue", packet, "--to", "claude", "--budget-seconds", "30", "--old-stopped",
                     "--launch", env={"FAKE_RELAY_DIE": "1"})
        self.assertEqual(r.returncode, 2, r.stderr + r.stdout)
        record = json.loads(r.stdout)
        self.assertEqual(record["exit_code"], 17)
        self.assertEqual(record["verification"], "not-run")
        self.assertEqual((self.work / "partial.txt").read_text(encoding="utf-8"), "partial work survives\n")
        self.assertIn("-p", json.loads((self.work / "relay-fake-call.json").read_text(encoding="utf-8"))["argv"])
        fresh = self.capture(source="claude")
        new = json.loads((self.work / ".ccx" / "relay" / (fresh + ".json")).read_text(encoding="utf-8"))
        self.assertTrue(any("partial.txt" in f for f in new["git"]["uncommitted"]))

    def test_midprocess_kill_and_zero_exit_quota_keep_evidence(self):
        self.enable()
        for flag, expected in (("FAKE_RELAY_KILL", "exited"), ("FAKE_RELAY_QUOTA", "quota_stopped")):
            with self.subTest(flag=flag):
                packet = self.capture()
                r = self.ccx("relay", "continue", packet, "--to", "codex", "--budget-seconds", "30",
                             "--old-stopped", "--launch", env={flag: "1"})
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                record = json.loads(r.stdout)
                self.assertEqual(record["state"], expected)
                saved = json.loads(Path(record["record"]).read_text(encoding="utf-8"))
                self.assertEqual(saved["state"], expected)
                self.assertTrue((self.work / "partial.txt").exists())
                if flag == "FAKE_RELAY_QUOTA":
                    self.assertEqual(saved["exit_code"], 0)
                    self.assertEqual(saved["quota_signal"]["kind"], "quota")
                    self.assertTrue((self.work / ".ccx" / "relay" / (saved["handoff_packet"] + ".json")).exists())
                else:
                    self.assertNotEqual(saved["exit_code"], 0)

    def test_cli_sync_plugin_disable_and_uninstall_preserve_user_hook(self):
        settings = self.home_claude / "settings.json"
        other = {"matcher": "rate_limit", "hooks": [{"type": "command", "command": "other-handler"}]}
        settings.write_text(json.dumps({"enabledPlugins": {"relayline@example": True},
                                        "hooks": {"StopFailure": [other]}}), encoding="utf-8")
        self.enable()
        r = self.ccx("sync", "--only", "hooks", "--apply")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        data = json.loads(settings.read_text(encoding="utf-8"))
        self.assertEqual(len(data["hooks"]["StopFailure"]), 2)
        self.assertNotIn("SessionStart", data["hooks"])  # plugin still owns ordinary hooks
        before = settings.read_bytes()
        r = self.ccx("sync", "--only", "hooks", "--apply")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(settings.read_bytes(), before)
        r = self.ccx("config", "set", "relay.enabled", "false")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        r = self.ccx("sync", "--only", "hooks", "--apply")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(json.loads(settings.read_text(encoding="utf-8"))["hooks"]["StopFailure"], [other])
        self.enable()
        self.assertEqual(self.ccx("sync", "--only", "hooks", "--apply").returncode, 0)
        r = self.ccx("uninstall", "--apply")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(json.loads(settings.read_text(encoding="utf-8"))["hooks"]["StopFailure"], [other])

    def test_unknown_goal_and_moved_head_refuse_launch(self):
        self.enable()
        r = self.ccx("relay", "capture")
        packet = json.loads(r.stdout)["packet"]
        self.assertEqual(self.ccx("relay", "continue", packet, "--to", "codex", "--budget-seconds", "30",
                                  "--old-stopped", "--launch").returncode, 3)
        packet = self.capture()
        self.git("commit", "--allow-empty", "-m", "new head")
        r = self.ccx("relay", "continue", packet, "--to", "codex", "--budget-seconds", "30", "--old-stopped", "--launch")
        self.assertEqual(r.returncode, 3)
        self.assertIn("HEAD changed", r.stdout)

    def test_budget_interrupt_kills_child_tree_without_a_clock_race(self):
        self.enable()
        packet_id = self.capture()
        packet = json.loads((self.work / ".ccx" / "relay" / (packet_id + ".json")).read_text(encoding="utf-8"))

        class TimedChild:
            pid = 12345
            returncode = None
            calls = 0

            def communicate(self, data=None, timeout=None):
                self.calls += 1
                if self.calls == 1:
                    raise subprocess.TimeoutExpired("fake", timeout)
                self.returncode = -9

        child = TimedChild()
        with patch("ccx.relay.state.snapshot", return_value=packet["git"]), \
                patch("ccx.relay.subprocess.Popen", return_value=child), \
                patch("ccx.relay.kill_tree", return_value=True) as kill:
            out = continue_packet(self.work.resolve(), packet_id, "codex", 30, True, True)
        kill.assert_called_once_with(child.pid)
        self.assertEqual((out["state"], out["reason"]), ("interrupted", "wall_time_budget"))
        self.assertTrue(out["child_tree_killed"])
        self.assertEqual(child.calls, 2)


def test_hook_ownership_preserves_other_handlers():
    mine = 'python ccx.py relay capture --hook'
    data = {"hooks": {"StopFailure": [{"matcher": "rate_limit", "hooks": [{"command": mine}, {"command": "other"}]}]}}
    assert sync_hook(data, False, "")
    assert data["hooks"]["StopFailure"][0]["hooks"] == [{"command": "other"}]


def test_disabled_sync_does_not_modify_foreign_empty_groups():
    data = {"hooks": {"StopFailure": [{"matcher": "overloaded", "hooks": []}]}}
    before = json.dumps(data)
    assert not sync_hook(data, False, "")
    assert json.dumps(data) == before
