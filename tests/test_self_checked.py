"""P0-8: a check that passed only on tests the sub-agent wrote or changed in the run is not plain ok
(kind ok_self_checked), and [escalate] on_self_checked sends it to review (default) or one rung up."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ccx import coverage as cv  # noqa: E402
from ccx import review as rv  # noqa: E402
from ccx.config import Paths  # noqa: E402
from test_ccx import Env  # noqa: E402


class TestSelfAuthored(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for f in ("tests/test_a.py", "tests/test_b.py", "src/m.py"):
            (self.root / f).parent.mkdir(parents=True, exist_ok=True)
            (self.root / f).write_text("", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_written_or_edited_only(self):
        c = cv.summarize("pytest tests/test_a.py", self.root, self.root, [], ["tests/test_a.py"])
        self.assertTrue(cv.self_checked(c))                          # written by the run (pg1's test_own.py)
        c = cv.summarize("pytest tests/test_a.py", self.root, self.root, ["tests/test_a.py"], [])
        self.assertTrue(cv.self_checked(c))                          # an existing test it changed (the audit's 7)
        c = cv.summarize("pytest tests", self.root, self.root, ["tests/test_a.py"], ["tests/test_b.py"])
        self.assertTrue(cv.self_checked(c))                          # one written, one changed: still all its own

    def test_independent_tests_keep_it_plain(self):
        c = cv.summarize("pytest tests", self.root, self.root, [], ["tests/test_a.py"])
        self.assertFalse(cv.self_checked(c))                         # test_b.py was there before and still ran
        c = cv.summarize("pytest tests/test_a.py", self.root, self.root, [], [], ["tests/test_a.py"])
        self.assertFalse(cv.self_checked(c))                         # added to: its earlier tests still ran
        self.assertFalse(cv.self_checked(cv.summarize("make test", self.root, self.root, [], [])))
        self.assertFalse(cv.self_checked(None))

    def test_import_only_edit_is_not_its_own_yardstick(self):
        imports = ("--- a/tests/test_a.py\n+++ b/tests/test_a.py\n@@ -1 +1 @@\n-from m import load\n"
                   "+from m import load, load_delim\n@@ -9,0 +10,2 @@\n+def test_delim():\n+    assert load_delim()\n")
        self.assertEqual(cv.rewritten_tests(imports), [])
        c = cv.summarize("pytest tests/test_a.py", self.root, self.root, ["tests/test_a.py"], [], [],
                         cv.rewritten_tests(imports))
        self.assertTrue(c["basis_changed"])                          # still shown, as before
        self.assertFalse(cv.self_checked(c))                         # its earlier tests still ran
        asserts = "--- a/tests/test_a.py\n+++ b/tests/test_a.py\n@@ -3 +3 @@\n-    assert f() == 1\n+    assert f() == 2\n"
        self.assertEqual(cv.rewritten_tests(asserts), ["tests/test_a.py"])

    def test_a_check_that_also_runs_something_else(self):
        self.assertTrue(cv.only_tests("cd sub && python -m pytest -q t.py 2>&1 | tail -5"))
        self.assertFalse(cv.only_tests("pytest -q test_own.py && python hidden_check.py"))
        c = cv.summarize("pytest tests/test_a.py && python check.py", self.root, self.root, [], ["tests/test_a.py"])
        self.assertFalse(cv.self_checked(c))

    def test_reviewed_ok(self):
        self.assertTrue(cv.reviewed_ok({"review": {"self_checked": True, "verdict": "pass"}}))
        self.assertFalse(cv.reviewed_ok({"review": {"self_checked": True, "verdict": "pass", "downgraded": 1}}))
        self.assertFalse(cv.reviewed_ok({"review": {"verdict": "pass"}}))

    def test_switch(self):
        self.assertEqual(cv.on_self_checked({}), "review")
        self.assertEqual(cv.on_self_checked({"escalate": {"on_self_checked": "RUNG"}}), "rung")
        self.assertEqual(cv.on_self_checked({"escalate": {"on_self_checked": "off"}}), "off")
        self.assertEqual(cv.on_self_checked({"escalate": {"on_self_checked": "bogus"}}), "review")

    def test_brief_asks_for_the_task_text(self):
        b = rv.brief("r1", "add f", "did it", "+x", 4000, {"cmd": "pytest t.py", "passed": True}, [],
                     self_checked=True)
        self.assertIn("ccx counts this check as self-authored", b)
        self.assertIn("signature and argument order", b)
        self.assertNotIn("self-authored", rv.brief("r1", "add f", "did it", "+x", 4000,
                                                   {"cmd": "pytest t.py", "passed": True}, []))

    def test_ui_says_why(self):
        from ccx.ui import _act
        rec = {"run_id": "r1", "ok": True, "kind": "ok_self_checked", "state": "finished",
               "result": {"status": "done"}, "to": "codex", "cwd": "."}
        a = _act(rec, None, 0, None)
        self.assertEqual((a["kind"], a["why"][0]), ("review", "w_self_checked"))
        strings = json.loads((Path(__file__).resolve().parent.parent / "ccx" / "ui_static" / "strings.json")
                             .read_text(encoding="utf-8"))
        for lang in ("zh", "en"):
            self.assertIn("w_self_checked", strings[lang])
            self.assertIn("h_ok_self_checked", strings[lang])


# A polyglot-like task: the sub-agent writes add() without the ValueError the task asks for, and a test_own.py of its
# own that passes. The hidden test (never in the repo) fails.
TASK = "add add(a, b) to a.py: return a + b; raise ValueError when either is negative"
WRONG = "def add(a, b):\n    return a + b\n"
RIGHT = "def add(a, b):\n    if a < 0 or b < 0:\n        raise ValueError('negative')\n    return a + b\n"
OWN_TEST = "from a import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n"
HIDDEN = ("from a import add\ntry:\n    add(-1, 2)\n    print('hidden failed')\n"
          "except ValueError:\n    print('hidden passed')\n")


class TestSelfCheckedRun(Env):
    def setUp(self):
        super().setUp()
        g = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.run(["git", "init", "-q"], cwd=self.work, check=True)
        (self.work / "readme.txt").write_text("calc\n", encoding="utf-8")
        subprocess.run([*g, "add", "."], cwd=self.work, check=True)
        subprocess.run([*g, "commit", "-qm", "init"], cwd=self.work, check=True)
        self.py = sys.executable.replace("\\", "/")
        self.check = f'"{self.py}" -m pytest -q -p no:cacheprovider test_own.py'

    def writes(self, impl):
        return f"{self.work / 'a.py'}={impl};{self.work / 'test_own.py'}={OWN_TEST}"

    def record(self, rid):
        return json.loads((Paths(self.hub).runs / rid / "run.json").read_text(encoding="utf-8"))

    def ledger_row(self, rid):
        rows = [json.loads(x) for x in (self.hub / "ccx" / "ledger.jsonl").read_text(encoding="utf-8").splitlines()
                if x.strip()]
        return [r for r in rows if r.get("run_id") == rid and not r.get("type")][-1]

    def hidden_fails(self):
        """The hidden test, run as a plain script outside the repo (no pytest collection of the temp folders)."""
        r = subprocess.run([sys.executable, "-B", "-c", HIDDEN], cwd=self.work, capture_output=True, text=True,
                           env={**self.env, "PYTHONPATH": str(self.work)})
        self.assertIn(r.stdout.strip(), ("hidden passed", "hidden failed"), r.stdout + r.stderr)
        return r.stdout.strip() == "hidden failed"

    def run_it(self, *extra, env=None):
        r = self.ccx("run", "--to", "codex", "--mode", "write", "--no-fallback", "--check", self.check, *extra,
                     TASK, env={"FAKE_WRITE": self.writes(WRONG), "FAKE_REVIEW": "pass", **(env or {})})
        self.assertIn(r.returncode, (0, 2), r.stderr)
        return json.loads(r.stdout), r

    def review_prompts(self):
        return [c["prompt"] for c in self.calls() if "[ccx review" in c["prompt"]]

    def calls(self):
        if not self.log.exists():
            return []
        return [json.loads(x) for x in self.log.read_text(encoding="utf-8").splitlines() if x.strip()]

    def test_own_tests_pass_hidden_behaviour_wrong_is_labelled_and_reviewed(self):
        # no other trigger reviews it: claimed files match, < min_lines, and weak-evidence reviews are switched off
        (self.hub / "ccx").mkdir(parents=True, exist_ok=True)
        (self.hub / "ccx" / "tiers.toml").write_text("[review]\nweak = false\n", encoding="utf-8")
        out, r = self.run_it("--model", "gpt-6-luna", "--effort", "low")
        self.assertEqual(r.returncode, 0, out)                      # still a pass: labelled, not failed
        self.assertTrue(out["check"]["passed"])
        self.assertTrue(self.hidden_fails())                        # what the label is about
        self.assertEqual(out["kind"], "ok_self_checked")
        self.assertIn("not independently verified", out["check"]["basis"])
        rec = self.record(out["run_id"])
        self.assertEqual(rec["kind"], "ok_self_checked")
        row = self.ledger_row(out["run_id"])
        self.assertEqual(row["kind"], "ok_self_checked")
        self.assertTrue(row["check"]["self_authored"])
        # default review: reviewed although the check names the changed file (strong by the old rule)
        prompts = self.review_prompts()
        self.assertTrue(prompts, out)
        self.assertIn("ccx counts this check as self-authored", prompts[-1])
        self.assertTrue(rec["review"]["self_checked"])
        self.assertTrue(rec["review"]["reason"].startswith("check basis self-authored"), rec["review"])
        # the review held it against the task text and passed: the label stays, needs_lead goes
        self.assertNotIn("needs_lead", out)
        self.assertIn("the review held it against the task text and passed", out["hint"])

    def test_switch_off_labels_without_a_review(self):
        self.assertEqual(self.ccx("config", "set", "escalate.on_self_checked", "off").returncode, 0)
        out, r = self.run_it("--model", "gpt-6-luna", "--effort", "low")
        self.assertEqual(out["kind"], "ok_self_checked")
        self.assertIn("not independently verified", out["needs_lead"])     # no review: the lead looks
        self.assertIn("needs_lead=ok_self_checked", r.stdout)               # the recap line
        self.assertNotIn("ccx counts this check as self-authored", "".join(self.review_prompts()))
        self.assertNotIn("self_checked", self.record(out["run_id"]).get("review") or {})

    def test_rung_climbs_once_and_says_why(self):
        self.assertEqual(self.ccx("config", "set", "escalate.on_self_checked", "rung").returncode, 0)
        out, _ = self.run_it("--tier", "T1", "--review", "off", env={"FAKE_WRITE_RESUMED": self.writes(RIGHT)})
        rec = self.record(out["run_id"])
        self.assertIn("->", out.get("escalated", ""), out)
        self.assertEqual(rec["attempts"][0]["kind"], "ok_self_checked")
        prompts = [c["prompt"] for c in self.calls() if c["agent"] == "codex"]
        self.assertIn("every test it ran was written or changed by you", "".join(prompts))
        self.assertFalse(self.hidden_fails())                       # the stronger rung got it right
        self.assertEqual(out["kind"], "ok_self_checked")            # its check is still its own: still labelled

    def test_rung_climbs_only_once_for_this_reason(self):
        self.assertEqual(self.ccx("config", "set", "escalate.on_self_checked", "rung").returncode, 0)
        self.assertEqual(self.ccx("config", "set", "defaults.max_escalations", "3").returncode, 0)
        out, _ = self.run_it("--tier", "T1", "--review", "off", env={"FAKE_WRITE_RESUMED": self.writes(RIGHT)})
        rec = self.record(out["run_id"])
        self.assertEqual(sum(a.get("kind") == "ok_self_checked" for a in rec["attempts"]), 1, rec["attempts"])
        self.assertEqual(len(rec["attempts"]), 2)

    def test_an_existing_test_in_the_check_keeps_it_plain(self):
        g = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]
        (self.work / "test_old.py").write_text("def test_old():\n    assert True\n", encoding="utf-8")
        subprocess.run([*g, "add", "."], cwd=self.work, check=True)
        subprocess.run([*g, "commit", "-qm", "old test"], cwd=self.work, check=True)
        self.check = f'"{self.py}" -m pytest -q -p no:cacheprovider test_own.py test_old.py'
        out, _ = self.run_it("--model", "gpt-6-luna", "--effort", "low", "--review", "off")
        self.assertNotIn("kind", out)
        self.assertNotIn("basis", out["check"])


if __name__ == "__main__":
    unittest.main()
