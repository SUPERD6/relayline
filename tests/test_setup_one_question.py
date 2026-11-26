"""#552: `ccx setup` on a terminal asks ONE question by default; `--advanced` keeps every step-by-step question;
`--yes` and the non-terminal plan are unchanged. Fake CLIs and fake input only; never a real CLI or the real home."""
import io
import unittest
from contextlib import redirect_stdout
from unittest import mock

from test_ccx import Env

from ccx import config, setup


class SetupQuestions(Env):
    def run_setup(self, answers, **kw):
        asked, it = [], iter(answers)

        def fake_input(prompt=""):
            asked.append(prompt)
            try:
                return next(it)
            except StopIteration:
                raise EOFError

        out = io.StringIO()
        with mock.patch("builtins.input", fake_input), mock.patch.object(setup.sys.stdin, "isatty", lambda: True), \
                redirect_stdout(out):
            rc = setup.run(**kw)
        return rc, asked, out.getvalue()

    def test_default_path_asks_exactly_one_question_and_wires(self):
        rc, asked, out = self.run_setup(["y"])
        self.assertEqual(rc, 0, out)
        self.assertEqual(len(asked), 1, asked)
        self.assertTrue(any(self.hub.iterdir()))
        self.assertIn("skipped (costs a little)", out)               # the paid selftest is not part of it
        self.assertNotIn("sessions of the last", out)                # nor the notes scan
        self.assertFalse(self.calls())                               # no CLI ran a task

    def test_default_path_no_changes_nothing(self):
        hub_files = sorted(self.hub.rglob("*"))
        rc, asked, out = self.run_setup(["n"])
        self.assertEqual((rc, len(asked)), (0, 1))
        self.assertIn("ccx setup --advanced", out)
        self.assertEqual(sorted(self.hub.rglob("*")), hub_files)
        self.assertFalse((self.home_claude / "settings.json").exists())

    def test_advanced_keeps_every_question(self):
        # hub location, create hub, wire, notes scan, selftest
        rc, asked, out = self.run_setup(["", "y", "y", "n", "n"], advanced=True)
        self.assertEqual(rc, 0, out)
        joined = "\n".join(asked)
        for want in ("Where should it live?", "Create/update ccx files", "Make these changes?",
                     "sessions of the last", "Run one tiny real task"):
            self.assertIn(want, joined)
        self.assertNotIn("recommended settings", joined)

    def test_relay_stays_off_by_default(self):
        self.run_setup(["y"])
        cfg = config.load_config(config.paths())
        self.assertIs(config.relay_enabled(cfg), False)

    def test_yes_is_unchanged_and_asks_nothing(self):
        rc, asked, out = self.run_setup([], yes=True)
        self.assertEqual((rc, asked), (0, []))

    def test_cli_has_advanced_flag(self):
        r = self.ccx("setup", "--help")
        self.assertIn("--advanced", r.stdout)
        self.assertIn("--yes", r.stdout)
        self.assertIn("--hub", r.stdout)


if __name__ == "__main__":
    unittest.main()
