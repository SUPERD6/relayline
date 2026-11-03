"""What the lead is handed when nothing needs a look (ccx/leadview.py, P0-11 item 3): one JSON line; the whole result
otherwise, with `output.lead full`, and from `ccx show <id>`. Fake CLIs only; never a real claude/codex."""
import json
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_ccx import ROOT, Env  # noqa: E402

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

    def terminal(self, *args, env=None):
        driver = self.work / "tty_cli.py"
        driver.write_text("import sys\nfrom unittest import mock\n"
                          f"sys.path.insert(0, {str(ROOT)!r})\nfrom ccx.cli import main\n"
                          "with mock.patch.object(sys.stdout, 'isatty', return_value=True):\n"
                          "    raise SystemExit(main())\n", encoding="utf-8", newline="")
        result = subprocess.run([sys.executable, str(driver), *args], cwd=self.work,
                                env={**self.env, **(env or {})}, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

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
            self.assertEqual(out["status"], "done")
            self.assertIn("status=done ok=true", out["recap"])
            self.assertIn("(model)", out["recap"])

    def test_a_budget_blocked_fix_round_does_not_claim_review_never_ran(self):
        from ccx.delegate import recap
        rec = {"run_id": "r", "ok": False, "attempts": []}
        res = {"status": "failed", "ok": False, "max_usd": {"cap": 1, "stopped_before": "fix round"},
               "review": {"verdict": "issues"}}
        text = recap(rec, res)
        self.assertIn("status=failed ok=false", text)
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

    def test_all_reviewers_failing_produces_a_visible_not_run_receipt(self):
        self.init_repo()
        out = self.run_json("run", "--from", "user", "--to", "codex", "--model", "gpt-6-luna", "--effort", "low",
                            "--review", "on", "--check", "python -c pass", "change x to 2",
                            env={"FAKE_WRITE": "a.py=x = 2\n", "FAKE_STATUS_CLAUDE": "quota"})
        self.assertEqual(out["review"]["verdict"], "not-run")
        self.assertIn("usage limit", out["review"]["error"])
        self.assertIn("review not run (", out["recap"])
        self.assertEqual(out["status"], "partial")
        self.assertIn("status=partial ok?", out["recap"])
        self.assertTrue(any("[ccx review" in c["prompt"] for c in self.calls()))

    def test_quota_reassignment_survives_a_review_fix_round(self):
        self.init_repo()
        wrapper = self.work / "quota_then_review.py"
        fake = ROOT / "tests" / "fakes" / "fake_codex.py"
        wrapper.write_text("import io, os, runpy, sys\nprompt = sys.stdin.read()\n"
                           "if '[ccx review' in prompt:\n"
                           "    os.environ['FAKE_STATUS_CODEX'] = 'done'\n"
                           "    os.environ['FAKE_SUMMARY'] = 'REVIEW: pass'\n"
                           "sys.stdin = io.StringIO(prompt)\n"
                           f"sys.path.insert(0, {str(fake.parent)!r})\n"
                           f"runpy.run_path({str(fake)!r}, run_name='__main__')\n", encoding="utf-8", newline="")
        out = self.run_json("run", "--from", "user", "--to", "codex", "--tier", "T2", "--review", "on",
                            "--check", "python -c pass", "change x to 2",
                            env={"CCX_CODEX_BIN": str(wrapper), "FAKE_STATUS_CODEX": "quota",
                                 "FAKE_WRITE": "a.py=x = 2\n", "FAKE_REVIEW": "issues,pass"})
        rec = self.record(out)
        parent = self.record({"run_id": out["fixed_after_review_of"]})
        self.assertEqual(parent["review"]["verdict"], "issues")
        self.assertEqual(out["review"]["verdict"], "pass")
        self.assertEqual(rec["review_round"], 1)
        for key in ("requested_agent", "requested_model", "quota_fallback"):
            self.assertEqual(rec[key], parent[key])
            self.assertEqual(out[key], parent[key])
        self.assertEqual((out["requested_agent"], out["agent"]), ("codex", "claude"))
        self.assertIn("reassigned codex→claude (quota)", out["recap"])
        self.assertIn("status=partial ok?", out["recap"])
        shown = self.run_json("show", parent["run_id"])
        self.assertEqual(shown["requested_agent"], "codex")
        self.assertIn("reassigned codex→claude (quota)", shown["recap"])

    def test_terminal_quota_reassignment_prints_partial_and_show_instead_of_verify(self):
        output = self.terminal("run", "--from", "user", "--to", "claude", "--tier", "T2", "--review", "off",
                               "--check", "python -c pass", "implement parser", env={"FAKE_STATUS_CLAUDE": "quota"})
        self.assertIn("Result: partial (ok?); reassigned claude→codex (quota)", output)
        self.assertNotIn("Next: look at the result, then record your verdict", output)
        self.assertIn("Next: ccx show", output)

    def test_terminal_budget_stop_reports_the_missing_review(self):
        self.init_repo()
        output = self.terminal("run", "--from", "user", "--to", "codex", "--model", "gpt-6-luna", "--effort", "low",
                               "--review", "on", "--max-usd", "0.0000001", "--check", "python -c pass",
                               "change x to 2", env={"FAKE_WRITE": "a.py=x = 2\n"})
        self.assertIn("Result: stopped (ok?); stopped: budget $1e-07 reached, review not run", output)
        self.assertNotIn("Result: done", output)
        self.assertNotIn("Next: look at the result, then record your verdict", output)

    def test_terminal_review_error_reports_partial_and_inspection(self):
        self.init_repo()
        output = self.terminal("run", "--from", "user", "--to", "codex", "--model", "gpt-6-luna", "--effort", "low",
                               "--review", "on", "--check", "python -c pass", "change x to 2",
                               env={"FAKE_WRITE": "a.py=x = 2\n", "FAKE_STATUS_CLAUDE": "quota"})
        self.assertIn("Result: partial (ok?); review not run (", output)
        self.assertNotIn("Result: done", output)
        self.assertIn("Next: ccx show", output)

    def test_terminal_done_self_check_keeps_its_hint_without_suggesting_a_positive_verdict(self):
        self.init_repo()
        check = f'"{sys.executable}" -m pytest -q -p no:cacheprovider test_own.py'
        output = self.terminal("run", "--from", "user", "--to", "codex", "--tier", "T2", "--review", "off",
                               "--no-escalate", "--check", check, "change x to 2 and test it",
                               env={"FAKE_WRITE": "a.py=x = 2\n;test_own.py=import a\n\ndef test_x():\n    assert a.x == 2\n"})
        self.assertIn('"status": "done"', output)
        self.assertIn('"kind": "ok_self_checked"', output)
        self.assertIn("Result: done, but its check is not independent", output)
        self.assertIn("Next: hold the change against the task text yourself", output)
        self.assertNotIn("Next: look at the result, then record your verdict", output)
        self.assertNotIn("ccx verify", output)

    def test_show_recovers_interrupted_executor_fields_that_were_null_or_stale(self):
        from ccx import ledger
        from ccx.config import Paths
        p = Paths(self.hub)
        out = self.run_json("run", "--from", "user", "--to", "codex", "--tier", "T2", "--mode", "read",
                            "--review", "off", "Read the parser")
        original = self.record(out)
        for stale in (None, "old"):
            rid = ledger.new_run_id(p)
            rec = {**original, "run_id": rid, "state": "running", "result": None, "ok": False,
                   "agent": stale, "model": stale, "effort": stale, "session_id": None,
                   "host": "another-machine", "ccx_pid": 1, "ts": time.time(),
                   "current": {"n": 1, "agent": "codex", "cli": "codex", "model": "gpt-6.1-sol",
                               "effort": "high", "rung": "codex:gpt-6.1-sol:high", "tier": "T3", "t0": time.time()}}
            ledger.write_record(p.runs / rid, rec)
            os.utime(p.runs / rid / "run.json", (1, 1))
            shown = self.run_json("show", rid)
            recovered = self.record(shown)
            self.assertEqual(recovered["kind"], "interrupted")
            self.assertTrue(recovered["attempts"][-1]["recovered"])
            self.assertEqual((recovered["agent"], recovered["model"], recovered["effort"]),
                             ("codex", "gpt-6.1-sol", "high"))

    def test_show_finishing_fix_round_recomputes_recap_after_changing_ok(self):
        from ccx import ledger
        from ccx.config import Paths
        p = Paths(self.hub)
        out = self.run_json("run", "--from", "user", "--to", "codex", "--tier", "T2", "--mode", "read",
                            "--review", "off", "Read the parser")
        original = self.record(out)
        parent, child = ledger.new_run_id(p), ledger.new_run_id(p)
        ledger.write_record(p.runs / parent, {**original, "run_id": parent, "kind": "review_issues"})
        ledger.write_record(p.runs / child, {**original, "run_id": child, "resumed_from": parent, "review_round": 1})
        shown = self.run_json("show", parent)
        self.assertEqual(shown["fix_round"], "finishing")
        self.assertFalse(shown["ok"])
        self.assertIn("ok=false", shown["recap"])
        self.assertNotIn("ok=true", shown["recap"])


class TestReceiptStates(unittest.TestCase):
    def test_failed_status_and_ok_false_survive_every_notice(self):
        from ccx.delegate import human_summary, recap
        notices = ({"quota_fallback": {"from": "claude", "to": "codex"}},
                   {"max_usd": {"cap": 1, "stopped_before": "attempt"}},
                   {"review": {"verdict": "not-run", "error": "timeout"}})
        for status in ("blocked", "failed", "error", "done"):
            for notice in notices:
                with self.subTest(status=status, notice=notice):
                    rec = {"run_id": "r", "ok": False, "attempts": []}
                    res = {"status": status, "ok": False, "agent": "codex", **notice}
                    text = recap(rec, res)
                    self.assertIn(f"status={status} ok=false", text)
                    self.assertNotIn("ok?", text)
                    human = human_summary(rec, res)
                    self.assertIn(f"not done (status {status})", human[0])
                    self.assertNotIn("ccx verify", human[-1])

    def test_not_run_without_error_uses_its_reason_or_failed_reviewers_fallback(self):
        from ccx.delegate import human_summary, recap
        for review, reason in (({"verdict": "not-run"}, "all reviewers failed"),
                               ({"verdict": "not-run", "reason": "reviewer unavailable"}, "reviewer unavailable")):
            rec = {"run_id": "r", "ok": True, "attempts": []}
            res = {"status": "done", "ok": True, "review": review}
            text = recap(rec, res)
            self.assertIn("status=partial ok?", text)
            self.assertIn(f"review not run ({reason})", text)
            self.assertIn(f"review not run ({reason})", human_summary(rec, res)[0])

    def test_partial_worker_result_never_becomes_a_clean_line_after_quota_reassignment(self):
        res = {**PASSED, "status": "partial", "quota_fallback": {"from": "claude", "to": "codex"}}
        self.assertFalse(leadview.clean(res))

    def test_budget_stopped_self_check_still_says_its_check_is_not_independent(self):
        from ccx.delegate import human_summary, recap
        rec = {"run_id": "r", "ok": True, "kind": "ok_self_checked", "attempts": []}
        res = {"status": "done", "ok": True, "kind": "ok_self_checked",
               "max_usd": {"cap": 1, "stopped_before": "review"}}
        self.assertIn("status=stopped ok=true", recap(rec, res))
        text = human_summary(rec, res)
        self.assertIn("Result: stopped (ok=true)", text[0])
        self.assertIn("its check is not independent", text[0])
        self.assertNotIn("ccx verify", text[-1])

    def test_done_self_check_without_hint_needs_review_before_a_positive_verdict(self):
        from ccx.delegate import human_summary
        rec = {"run_id": "r", "ok": True, "kind": "ok_self_checked", "attempts": []}
        res = {"status": "done", "ok": True, "kind": "ok_self_checked"}
        self.assertEqual(human_summary(rec, res)[-1], "Next: ccx show r --full")
        rec["review"] = {"self_checked": True, "verdict": "pass"}
        self.assertIn("ccx verify r --ok 1", human_summary(rec, res)[-1])


if __name__ == "__main__":
    unittest.main()
