"""#523: the SessionStart hook (`ccx mem delta`) tells a new session about an unfinished relay packet. Fake CLIs only."""
import json

import test_relay
from test_ccx import Env

R = test_relay.TestRelay


class TestRelayHint(Env):
    # reuse the relay fixtures (git repo, fake CLIs, capture) without inheriting - and re-running - its tests
    setUp, git, enable, capture = R.setUp, R.git, R.enable, R.capture

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
        self.assertIn(pid, self.delta("codex"))            # a packet is not "consumed" by being shown

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
