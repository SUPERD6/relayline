"""What the lead is handed when nothing needs a look (ccx/leadview.py, P0-11 item 3): one JSON line; the whole result
otherwise, with `output.lead full`, and from `ccx show <id>`. Fake CLIs only; never a real claude/codex."""
import json
import os
import subprocess
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
          "review": {"verdict": "pass", "by": "claude:sonnet", "usd": 0.01},
          "check": {"cmd": "pytest -q", "passed": True, "exit": 0}, "route": {"rung": "T1"},
          "recap": "ccx run r1: status=done ok=true check=passed review=pass cost=~$0.01; next: ccx show r1"}


class TestClean(unittest.TestCase):
    def test_a_passed_run_is_one_line_with_what_was_done(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CCX_LEAD_VIEW", None)
            obj, one = leadview.render(PASSED, {})
        self.assertTrue(one)
        self.assertEqual(set(obj), {"run_id", "agent", "model", "ok", "status", "summary", "files_changed",
                                    "diffstat", "check", "review", "view", "recap"})
        self.assertEqual(list(obj)[-1], "recap")                     # last key: survives `| tail`
        s = leadview.dumps(obj, one)
        self.assertNotIn("\n", s)
        self.assertLess(len(s), len(json.dumps(PASSED, indent=2)) * 0.7)

    def test_anything_for_the_lead_keeps_the_whole_result(self):
        cases = [dict(PASSED, ok=False), dict(PASSED, status="partial"), dict(PASSED, hint="see"),
                 dict(PASSED, needs_lead="x"), dict(PASSED, kind="review_issues"), dict(PASSED, edited_tests=["t"]),
                 dict(PASSED, namecheck=["n"]), dict(PASSED, open_questions=["q?"]), dict(PASSED, policy_blocked=1),
                 dict(PASSED, check={"passed": True, "weak": True, "note": "n"}),
                 dict(PASSED, check={"passed": True, "basis_changed": ["t.py"]}),
                 dict(PASSED, check={"passed": None, "status": "unchanged tree"}),
                 dict(PASSED, check={"passed": False, "exit": 1}),
                 {k: v for k, v in PASSED.items() if k != "check"},       # no check: nothing was verified
                 dict(PASSED, review={"verdict": "issues"}), dict(PASSED, review={"verdict": "pass", "error": "e"}),
                 dict(PASSED, review={"verdict": "pass", "notes": ["[should] add a test for y"]}),
                 dict(PASSED, next_step="run the migration first"),
                 dict(PASSED, autonomy={"level": "L2", "merge": {"merged": False, "why_not": "x"}}),
                 dict(PASSED, project={"name": "p"}),
                 dict(PASSED, fixed_after_review_of="r0"),
                 dict(PASSED, check={"passed": True, "covers": "x", "covers_unknown": True})]
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

    def test_behind_base_remains_in_one_line_and_is_visible_in_the_recap(self):
        res = dict(PASSED, base_behind=3)
        with mock.patch.dict(os.environ, {"CCX_LEAD_VIEW": "line"}):
            obj, one = leadview.render(res, {})
        self.assertTrue(one)
        self.assertEqual(obj["base_behind"], 3)
        self.assertTrue(obj["recap"].endswith("; base: 3 behind upstream"))
        self.assertEqual(res["recap"], PASSED["recap"])
        self.assertEqual(len(leadview.dumps(obj, one).splitlines()), 1)
        again, _ = leadview.render(obj, {})
        self.assertEqual(again["recap"].count("base: 3 behind upstream"), 1)

    def test_known_zero_is_retained_without_a_behind_note(self):
        obj, _ = leadview.render(dict(PASSED, base_behind=0), {})
        self.assertEqual(obj["base_behind"], 0)
        self.assertEqual(obj["recap"], PASSED["recap"])

    def test_behind_base_is_also_visible_when_the_whole_result_is_needed(self):
        res = dict(PASSED, base_behind=2, needs_lead="review this")
        obj, one = leadview.render(res, {})
        self.assertFalse(one)
        self.assertEqual(obj["base_behind"], 2)
        self.assertIn("base: 2 behind upstream", obj["recap"])
        with mock.patch.dict(os.environ, {"CCX_LEAD_VIEW": "full"}):
            obj, one = leadview.render(dict(PASSED, base_behind=2), {})
        self.assertFalse(one)
        self.assertIn("base: 2 behind upstream", obj["recap"])


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

    def test_bg_wait_hands_the_lead_one_line_and_logs_the_whole(self):
        r = self.ccx("run", "--from", "claude", "--to", "codex", "--model", "gpt-6-luna", "--effort", "low",
                     "--no-ab", "--review", "off", "--check", "python -c pass", "--bg", "--wait", "90",
                     "implement thing")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        out = json.loads(r.stdout.strip())
        self.assertEqual(len(r.stdout.strip().splitlines()), 1)
        self.assertEqual(out["view"], "line")
        log = (self.hub / "ccx" / "runs" / out["run_id"] / "bg.log").read_text(encoding="utf-8", errors="replace")
        self.assertIn('  "tokens"', log)                      # the child's log keeps the whole result

    def test_config_set_output_lead(self):
        self.assertNotEqual(self.ccx("config", "set", "output.lead", "ful").returncode, 0)
        self.assertEqual(self.ccx("config", "set", "output.lead", "full").returncode, 0)
        r = self.ccx("run", "--from", "claude", "--to", "codex", "--model", "gpt-6-luna", "--effort", "low",
                     "--no-ab", "--review", "off", "--check", "python -c pass", "implement thing")
        self.assertNotIn("view", json.loads(r.stdout))

    def test_output_lead_full_is_as_before(self):
        r = self.ccx("run", "--from", "claude", "--to", "codex", "--model", "gpt-6-luna", "--effort", "low",
                     "--no-ab", "--review", "off", "--check", "python -c pass", "implement thing",
                     env={"CCX_LEAD_VIEW": "full"})
        out = json.loads(r.stdout)
        self.assertNotIn("view", out)
        self.assertIn("tokens", out)
        self.assertIn("route", out)


class TestReceiptHonesty(Env):
    def run_json(self, *args, env=None):
        result = self.ccx(*args, env=env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def record(self, out):
        return json.loads(self.record_path(out).read_text(encoding="utf-8"))

    def record_path(self, out):
        return self.hub / "ccx" / "runs" / out["run_id"] / "run.json"

    def init_repo(self):
        subprocess.run(["git", "init", "-q"], cwd=self.work, check=True)
        (self.work / "a.py").write_text("x = 1\n", encoding="utf-8")
        subprocess.run(["git", "add", "a.py"], cwd=self.work, check=True)
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init"],
                       cwd=self.work, check=True)

    def test_quota_reassignment_names_requested_and_final_executor_in_line_and_show(self):
        out = self.run_json("run", "--from", "user", "--to", "claude", "--tier", "T2",
                            "--no-escalate", "--review", "off", "--check", "python -c pass", "implement parser",
                            env={"FAKE_STATUS_CLAUDE": "quota"})
        rec = self.record(out)
        last = rec["attempts"][-1]
        self.assertEqual(out["view"], "line")
        self.assertEqual((out["requested_agent"], out["requested_model"]), ("claude", "sonnet"))
        self.assertEqual((rec["requested_agent"], rec["requested_model"]), ("claude", "sonnet"))
        self.assertEqual((rec["agent"], rec["model"], rec["effort"]),
                         (last["agent"], last["model"], last["effort"]))
        self.assertEqual((out["agent"], out["model"], out["effort"]),
                         ("codex", f"{last['model']}/{last['effort']}", last["effort"]))
        self.assertEqual(out["status"], "partial")
        self.assertIn("reassigned claude→codex (quota)", out["recap"])
        self.assertIn("status=partial ok?", out["recap"])
        self.assertNotIn("ok=true", out["recap"])
        shown = self.run_json("show", out["run_id"])
        self.assertEqual(shown["agent"], "codex")
        self.assertIn("reassigned claude→codex (quota)", shown["recap"])

    def test_budget_stop_names_the_missing_review_without_plain_ok(self):
        self.init_repo()
        out = self.run_json("run", "--from", "user", "--to", "codex", "--model", "gpt-6-luna", "--effort", "low",
                            "--review", "on", "--max-usd", "0.0000001", "--check", "python -c pass",
                            "change x to 2", env={"FAKE_WRITE": "a.py=x = 2\n"})
        self.assertEqual(out["max_usd"]["stopped_before"], "review")
        self.assertEqual(out["review"]["verdict"], "not-run")
        self.assertIn("status=stopped ok?", out["recap"])
        self.assertIn("stopped: budget $1e-07 reached, review not run", out["recap"])
        self.assertNotIn("ok=true", out["recap"])
        self.assertFalse(any("[ccx review" in c["prompt"] for c in self.calls()))
        shown = self.run_json("show", out["run_id"])
        self.assertIn("stopped: budget $1e-07 reached, review not run", shown["recap"])

    def test_review_error_is_not_reported_as_plain_ok(self):
        self.init_repo()
        config = self.hub / "ccx" / "tiers.toml"
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text('[review.by]\ncodex="invalid-rung"\n', encoding="utf-8")
        out = self.run_json("run", "--from", "user", "--to", "codex", "--model", "gpt-6-luna", "--effort", "low",
                            "--review", "on", "--check", "python -c pass", "change x to 2",
                            env={"FAKE_WRITE": "a.py=x = 2\n"})
        self.assertIn("ValueError", self.record(out)["review"]["error"])
        self.assertIn("review not run (ValueError:", out["recap"])
        self.assertIn("status=partial ok?", out["recap"])
        self.assertNotIn("ok=true", out["recap"])
        self.assertIn("review not run (ValueError:", self.run_json("show", out["run_id"])["recap"])

    def test_old_record_without_requested_fields_uses_the_last_attempt(self):
        out = self.run_json("run", "--from", "user", "--to", "claude", "--tier", "T2", "--review", "off",
                            "implement parser", env={"FAKE_STATUS_CLAUDE": "quota"})
        rec = self.record(out)
        for key in ("requested_agent", "requested_model", "agent", "model", "effort"):
            rec.pop(key, None)
        rec["to"] = "claude"             # legacy records could retain the initial target
        self.record_path(out).write_text(json.dumps(rec), encoding="utf-8")
        shown = self.run_json("show", out["run_id"])
        self.assertEqual(shown["agent"], "codex")
        self.assertNotIn("requested_agent", shown)
        self.assertIn("reassigned claude→codex (quota)", shown["recap"])

    def test_model_substitution_keeps_original_request_before_and_after_it_is_learned(self):
        for unused in range(2):
            out = self.run_json("run", "--from", "user", "--to", "codex", "--model", "gpt-6-luna",
                                "--effort", "low", "--mode", "read", "--review", "off", "--new",
                                "Read the parser", env={"FAKE_UNSUPPORTED": "gpt-6-luna"})
            rec = self.record(out)
            self.assertEqual((rec["requested_agent"], rec["requested_model"]), ("codex", "gpt-6-luna"))
            self.assertNotEqual(rec["model"], "gpt-6-luna")
            self.assertEqual(rec["agent"], "codex")
            self.assertEqual(out["substituted_for"], "codex:gpt-6-luna:low")
            self.assertEqual(out["model"], f"{rec['model']}/{rec['effort']}")

    def test_a_budget_blocked_fix_round_does_not_claim_review_never_ran(self):
        from ccx.delegate import recap
        rec = {"run_id": "r", "ok": False, "attempts": []}
        res = {"status": "done", "ok": False, "max_usd": {"cap": 1, "stopped_before": "fix round"},
               "review": {"verdict": "issues"}}
        text = recap(rec, res)
        self.assertIn("status=stopped", text)
        self.assertIn("stopped: budget $1 reached, fix round not run", text)
        self.assertNotIn("review not run", text)

    def test_self_checked_wording_and_an_unstarted_fallback_remain_honest(self):
        from ccx.delegate import recap
        rec = {"run_id": "r", "ok": True, "kind": "ok_self_checked", "attempts": []}
        res = {"status": "done", "ok": True, "kind": "ok_self_checked", "agent": "claude",
               "needs_lead": "ok_self_checked: not independently verified",
               "quota_fallback": {"from": "claude", "to": "codex"}}
        self.assertEqual(leadview.receipt_notes(res), [])
        self.assertIn("status=done ok=true", recap(rec, res))
        self.assertIn("needs_lead=ok_self_checked", recap(rec, res))


if __name__ == "__main__":
    unittest.main()
