"""What the lead is handed when nothing needs a look (ccx/leadview.py, P0-11 item 3): one JSON line; the whole result
otherwise, with `output.lead full`, and from `ccx show <id>`. Fake CLIs only; never a real claude/codex."""
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_ccx import Env  # noqa: E402

from ccx import leadview  # noqa: E402

PASSED = {"run_id": "r1", "agent": "codex", "tier": "T1", "model": "m/low", "ok": True, "status": "done",
          "summary": "added x", "files_changed": ["a.py"], "verification": "pytest ok", "open_questions": [],
          "next_step": "", "tokens": {"input": 1, "cached": 2, "output": 3}, "diffstat": "1 file changed",
          "review": {"verdict": "pass", "by": "claude:sonnet", "notes": ["[note] fine"], "usd": 0.01},
          "check": {"cmd": "pytest -q", "passed": True, "exit": 0}, "route": {"rung": "T1"},
          "recap": "ccx run r1: status=done ok=true check=passed review=pass cost=~$0.01; next: ccx show r1"}


class TestClean(unittest.TestCase):
    def test_a_passed_run_is_one_line_with_what_was_done(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CCX_LEAD_VIEW", None)
            obj, one = leadview.render(PASSED, {})
        self.assertTrue(one)
        self.assertEqual(set(obj), {"run_id", "ok", "status", "summary", "files_changed", "diffstat", "check", "view",
                                    "recap"})
        self.assertEqual(list(obj)[-1], "recap")                     # last key: survives `| tail`
        s = leadview.dumps(obj, one)
        self.assertNotIn("\n", s)
        self.assertLess(len(s), len(json.dumps(PASSED, indent=2)) / 2)

    def test_anything_for_the_lead_keeps_the_whole_result(self):
        cases = [dict(PASSED, ok=False), dict(PASSED, status="partial"), dict(PASSED, hint="see"),
                 dict(PASSED, needs_lead="x"), dict(PASSED, kind="review_issues"), dict(PASSED, edited_tests=["t"]),
                 dict(PASSED, namecheck=["n"]), dict(PASSED, open_questions=["q?"]), dict(PASSED, policy_blocked=1),
                 dict(PASSED, check={"passed": True, "weak": True, "note": "n"}),
                 dict(PASSED, check={"passed": True, "basis_changed": ["t.py"]}),
                 dict(PASSED, check={"passed": None, "status": "unchanged tree"}),
                 dict(PASSED, check={"passed": False, "exit": 1}),
                 {k: v for k, v in PASSED.items() if k != "check"},       # no check: nothing was verified
                 dict(PASSED, review={"verdict": "issues"}), dict(PASSED, review={"verdict": "pass", "error": "e"})]
        for c in cases:
            obj, one = leadview.render(c, {})
            self.assertFalse(one, c)
            self.assertIs(obj, c)

    def test_no_review_ran_is_still_one_line(self):
        self.assertTrue(leadview.render({k: v for k, v in PASSED.items() if k != "review"}, {})[1])

    def test_full_switches_it_off(self):
        self.assertFalse(leadview.render(PASSED, {"output": {"lead": "full"}})[1])
        with mock.patch.dict(os.environ, {"CCX_LEAD_VIEW": "full"}):
            self.assertFalse(leadview.render(PASSED, {})[1])
        with mock.patch.dict(os.environ, {"CCX_LEAD_VIEW": "line"}):
            self.assertTrue(leadview.render(PASSED, {"output": {"lead": "full"}})[1])

    def test_a_long_summary_is_cut(self):
        obj, _ = leadview.render(dict(PASSED, summary="w " * 500), {})
        self.assertLessEqual(len(obj["summary"]), leadview.SUMMARY_CHARS)


class TestRunOutput(Env):
    def test_run_with_a_passing_check_prints_one_line_and_show_the_whole(self):
        r = self.ccx("run", "--from", "claude", "--to", "codex", "--model", "gpt-6-luna", "--effort", "low",
                     "--no-ab", "--review", "off", "--check", "python -c pass", "implement thing")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        line = r.stdout.strip()
        self.assertEqual(len(line.splitlines()), 1, line)
        out = json.loads(line)
        self.assertEqual((out["view"], out["ok"], out["status"]), ("line", True, "done"))
        self.assertIn("check=passed", out["recap"])
        whole = json.loads(self.ccx("show", out["run_id"]).stdout)
        self.assertIn("tokens", whole)                              # `ccx show` is the whole result
        self.assertEqual(whole["check"]["passed"], True)
        waited = self.ccx("show", out["run_id"], "--wait", "5").stdout.strip()
        self.assertEqual(json.loads(waited)["view"], "line")

    def test_output_lead_full_is_as_before(self):
        r = self.ccx("run", "--from", "claude", "--to", "codex", "--model", "gpt-6-luna", "--effort", "low",
                     "--no-ab", "--review", "off", "--check", "python -c pass", "implement thing",
                     env={"CCX_LEAD_VIEW": "full"})
        out = json.loads(r.stdout)
        self.assertNotIn("view", out)
        self.assertIn("tokens", out)
        self.assertIn("route", out)


if __name__ == "__main__":
    unittest.main()
