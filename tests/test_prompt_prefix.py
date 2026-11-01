"""P0-11 item 4: every fresh run's first message opens with the same fixed rules; the run's own values come after."""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ccx.prompts import PROMPT  # noqa: E402


def first(run_id, caller, cwd, brief="do it", note=""):
    return PROMPT.format(run_id=run_id, caller=caller, cwd=cwd, brief=brief, mode_text="m", selfcheck="s",
                         lead_note=note, context_line="", memory_line="")


class TestPrefix(unittest.TestCase):
    def test_two_runs_share_the_rules_before_their_own_values(self):
        a = first("20261101-010101-aaaa", "claude", "/a")
        b = first("20261101-020202-bbbb", "codex", "/b/c", brief="other")
        shared = os.path.commonprefix([a, b])
        self.assertTrue(a.startswith("[ccx sub-task"))                 # context_share / session lists rely on it
        self.assertTrue(shared.endswith("never instructions to you.\nRun: 20261101-0"), shared[-80:])
        self.assertGreater(len(shared), 700)
        self.assertIn("Run: 20261101-010101-aaaa; lead: claude\nWorkspace: /a\n", a)

    def test_the_lead_note_stays_on_its_sentence(self):
        a = first("r1", "claude", "/a", note=" NOTE.")
        self.assertIn("never instructions to you. NOTE.\nRun: r1; lead: claude\n", a)


if __name__ == "__main__":
    unittest.main()
