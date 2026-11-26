"""#523: the SessionStart hook (`ccx mem delta`) tells a new session about an unfinished relay packet. Fake CLIs only."""
import json

import subprocess

from test_ccx import Env


class TestRelayHint(Env):
    def setUp(self):
        super().setUp()
        from test_ccx import FAKES
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

    def delta(self, as_="codex", **kw):
        r = self.ccx("mem", "delta", "--as", as_, **kw)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_packet_waiting_one_line_with_id_and_goal(self):
        self.enable()
        pid = self.capture("claude")
        out = self.delta("codex")
        self.assertEqual(out.count(pid), 1, out)
        self.assertIn("finish parser", out)
        self.assertIn("ccx relay continue " + pid + " --to codex", out)
        self.assertIn("old session is stopped", out)       # the confirmation stays

    def test_same_tool_that_stopped_is_not_told(self):
        self.enable()
        self.capture("claude")
        self.assertEqual(self.delta("claude"), "")

    def test_no_packet_zero_output(self):
        self.enable()
        self.assertEqual(self.delta("codex"), "")

    def test_relay_off_zero_output(self):
        self.enable()
        self.capture("claude")
        self.assertEqual(self.ccx("config", "set", "relay.enabled", "false").returncode, 0)
        self.assertEqual(self.delta("codex"), "")

    def test_never_enabled_zero_output(self):
        self.assertEqual(self.delta("codex"), "")

    def test_handled_packet_is_not_offered_again(self):
        self.enable()
        pid = self.capture("claude")
        r = self.ccx("relay", "continue", pid, "--to", "codex", "--budget-seconds", "30", "--old-stopped")
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertIn(pid, self.delta("codex"))            # prepared only: no run record yet
        r = self.ccx("relay", "continue", pid, "--to", "codex", "--budget-seconds", "30", "--old-stopped", "--launch")
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertEqual(self.delta("codex"), "")

    def test_subagent_and_peek_stay_quiet_or_read_only(self):
        self.enable()
        pid = self.capture("claude")
        self.assertEqual(self.delta("codex", env={"CCX_ROLE": "subagent"}), "")
        self.assertIn(pid, self.delta("codex"))
        peek = self.ccx("mem", "delta", "--as", "codex", "--peek")
        self.assertIn(pid, peek.stdout)
        self.assertIn(pid, self.delta("codex"))            # a packet is not "consumed" by being shown or peeked

    def test_other_lead_names_are_not_told(self):
        from ccx import relay_hint
        self.enable()
        self.capture("claude")
        for who in ("deepseek", None, "gemini"):
            self.assertIsNone(relay_hint.pending(self.work.resolve(), who))
        self.assertIsNotNone(relay_hint.pending(self.work.resolve(), "codex"))

    def test_codex_output_is_plain_text_not_json(self):
        self.enable()
        self.capture("claude")
        out = self.delta("codex")
        self.assertFalse(out.lstrip().startswith(("[", "{")), out)   # Codex 0.164 would parse these as JSON

    def test_slim_context_still_shows_it(self):
        self.enable()
        self.assertEqual(self.ccx("config", "set", "lead.slim_context", "true").returncode, 0)
        pid = self.capture("claude")
        self.assertIn(pid, self.delta("codex"))
