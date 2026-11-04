"""[review] must_needs_repro (P1-10, default off): with ccx's check passed, a review [must] without a reproducible
failure starts no fix round (downgrade), or is settled once by a stronger reviewer first (confirm)."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ccx import review  # noqa: E402
from test_ccx import Env  # noqa: E402

NO_REPRO = "[must] a.py:3 — \"returns the total\" — off by one in the loop"
WITH_REPRO = "[must] a.py:3 — \"returns the total\" — off by one; repro: total([1, 2]) returns 1, not 3"


class TestRule(unittest.TestCase):
    def test_setting(self):
        for v, want in ((None, "off"), (False, "off"), ("", "off"), (True, "downgrade"), ("downgrade", "downgrade"),
                        ("Confirm", "confirm"), ("nonsense", "off")):
            self.assertEqual(review.must_needs_repro({} if v is None else {"must_needs_repro": v}), want, v)

    def test_downgrade(self):
        v = {"verdict": "issues", "issues": [NO_REPRO], "summary": "REVIEW: issues"}
        d = review.downgrade(v)
        self.assertEqual((d["verdict"], d["issues"], d["downgraded"]), ("pass", [], 1))
        self.assertTrue(d["notes"][0].startswith("[should] a.py:3"))
        # a [must] with a repro stays; only the other one becomes a [should]
        d = review.downgrade({"verdict": "issues", "issues": [WITH_REPRO, NO_REPRO], "summary": "x"})
        self.assertEqual((d["verdict"], d["issues"], d["downgraded"]), ("issues", [WITH_REPRO], 1))
        self.assertIs(review.downgrade({"verdict": "issues", "issues": [WITH_REPRO]})["verdict"], "issues")
        # issues_full (long items) is what is looked at
        long = NO_REPRO + " " + "x" * 400 + " repro: python -c 'import a; print(a.total([1]))' prints 0"
        v = review.verdict({"summary": "REVIEW: issues", "open_questions": [long]})
        self.assertEqual(review.without_repro(v), [])

    def test_what_counts_as_a_repro(self):
        for item in ("[must] a — repro: N/A (static reading)", "[must] a — repro: cannot run commands",
                     "[must] a — no repro: none found", "[must] a — repro:\n\nnothing", "[must] a — repro: TBD later"):
            self.assertFalse(review.has_repro(item), item)
        for item in ("[must] a — **repro**: total([1,2]) returns 1", "[must] a — reproduction: f(0) raises KeyError",
                     "[must] a — repro: `ccx q resume` -> exit 1, expected 0"):
            self.assertTrue(review.has_repro(item), item)
        # an edited assertion and a safety problem have no wrong output to show: left as they are
        for item in ("[must] tests/t.py:3 — assertion changed from 3 to 2", "[must] x.py — (d) secret written to log"):
            self.assertEqual(review.without_repro({"verdict": "issues", "issues": [item]}), [])

    def test_untagged_items_under_issues_count_too(self):
        for item in ("- **[must]** a.py:1 — off by one", "[should] a.py:1 — off by one", "a.py:1 off by one"):
            d = review.downgrade({"verdict": "issues", "issues": [item], "summary": "REVIEW: issues"})
            self.assertEqual((d["verdict"], d["downgraded"]), ("pass", 1), item)
            self.assertTrue(d["notes"][0].startswith("[should] a.py:1"), d)
            self.assertEqual(d["downgraded_items"], [item])

    def test_brief_says_so_only_with_a_passed_check(self):
        ok = {"cmd": "pytest", "passed": True, "exit": 0}
        self.assertIn("needs a `repro:` at its end", review.brief("r", "t", "s", "+x", 100, ok, repro=True))
        self.assertNotIn("repro:", review.brief("r", "t", "s", "+x", 100, ok))
        self.assertNotIn("repro:", review.brief("r", "t", "s", "+x", 100, {"cmd": "pytest", "passed": False,
                                                                           "exit": 1}, repro=True))


class TestFakeReviewers(unittest.TestCase):
    def test_reviewers_skip_fake_writes_but_builders_still_write(self):
        fakes = Path(__file__).resolve().parent / "fakes"
        with tempfile.TemporaryDirectory() as tmp:
            for name, argv in (("fake_claude.py", ["-p"]), ("fake_codex.py", ["exec", "--json"])):
                with self.subTest(fake=name):
                    target = Path(tmp) / name
                    target.write_text("original", encoding="utf-8")
                    env = os.environ.copy()
                    env.pop("FAKE_LOG", None)
                    env.pop("FAKE_REVIEW", None)
                    env.pop("FAKE_REVIEW_MUST", None)
                    env["FAKE_WRITE"] = f"{target}=new"
                    fake = fakes / name
                    review_run = subprocess.run([sys.executable, str(fake), *argv], input="[ccx review of run x]", cwd=tmp,
                                                env=env, capture_output=True, text=True)
                    self.assertEqual(review_run.returncode, 0, review_run.stderr)
                    self.assertEqual(target.read_text(encoding="utf-8"), "original")
                    builder_run = subprocess.run([sys.executable, str(fake), *argv], input="ordinary task", cwd=tmp,
                                                 env=env, capture_output=True, text=True)
                    self.assertEqual(builder_run.returncode, 0, builder_run.stderr)
                    self.assertEqual(target.read_text(encoding="utf-8"), "new")


class TestRun(Env):
    def setUp(self):
        super().setUp()
        g = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.run(["git", "init", "-q"], cwd=self.work, check=True)
        (self.work / "a.py").write_text("x = 1\n", encoding="utf-8")
        subprocess.run([*g, "add", "a.py"], cwd=self.work, check=True)
        subprocess.run([*g, "commit", "-qm", "init"], cwd=self.work, check=True)

    def go(self, setting, seq, must=NO_REPRO, check=True):
        if setting is not None:
            (self.hub / "ccx").mkdir(parents=True, exist_ok=True)
            (self.hub / "ccx" / "tiers.toml").write_text(f'[review]\nmust_needs_repro = "{setting}"\n',
                                                         encoding="utf-8")
        py = sys.executable.replace("\\", "/")
        extra = ["--check", f'"{py}" -c "import a; assert a.x == 2"'] if check else []
        r = self.ccx("run", "--to", "codex", "--model", "gpt-6-luna", "--effort", "low", "--mode", "write",
                     "--no-fallback", "--review", "on", *extra, "change x to 2 in a.py",
                     env={"FAKE_WRITE": f"{self.work / 'a.py'}=x = 2\n", "FAKE_REVIEW": seq, "FAKE_REVIEW_MUST": must})
        self.assertIn(r.returncode, (0, 2), r.stderr)
        return json.loads(r.stdout)

    def reviews(self):
        return [c for c in self.calls() if c["agent"] == "claude" and "[ccx review" in c["prompt"]]

    def test_off_by_default(self):
        out = self.go(None, "issues")
        self.assertEqual(out["review"]["verdict"], "issues")
        self.assertNotIn("repro:", self.reviews()[0]["prompt"])

    def test_downgrade_keeps_the_run_out_of_a_fix_round(self):
        out = self.go("downgrade", "issues")
        self.assertEqual(out["review"]["verdict"], "pass", out)
        self.assertNotIn("kind", out)
        self.assertTrue(out["ok"])
        self.assertEqual(len(self.reviews()), 1, out)             # no fix round, no second review
        self.assertIn("needs a `repro:` at its end", self.reviews()[0]["prompt"])

    def test_a_must_with_a_repro_still_starts_the_fix_round(self):
        out = self.go("downgrade", "issues,pass", must=WITH_REPRO)
        self.assertGreaterEqual(len(self.reviews()), 2)          # first review, then the fix round's review
        self.assertEqual(out["review"]["verdict"], "pass")

    def test_without_a_check_the_rule_does_not_apply(self):
        out = self.go("downgrade", "issues,issues", check=False)
        self.assertIn(out.get("kind"), ("review_failed", "review_issues"))

    def test_confirm_asks_a_stronger_reviewer_once(self):
        out = self.go("confirm", "issues,pass")
        rv = self.reviews()
        self.assertEqual(len(rv), 2, [c["argv"] for c in rv])
        self.assertIn("A first reviewer's [must] items", rv[1]["prompt"])
        self.assertIn("haiku", rv[0]["argv"])
        self.assertIn("sonnet", rv[1]["argv"])                    # one of [review] also, not the cheapest again
        self.assertEqual(out["review"]["verdict"], "pass", out)
        self.assertEqual(out["review"]["by"], "claude:sonnet:medium")
        self.assertNotIn("kind", out)
        rec = json.loads((self.hub / "ccx" / "runs" / out["run_id"] / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(rec["review"]["first_by"], "claude:haiku:low")

    def test_confirm_not_adopted_keeps_the_first_reviewer(self):
        out = self.go("confirm", "issues,unclear")
        self.assertEqual(out["review"]["by"], "claude:haiku:low")
        self.assertEqual(out["review"]["verdict"], "pass")        # the first one's [must], downgraded

    def test_confirm_that_finds_it_again_still_needs_a_repro(self):
        out = self.go("confirm", "issues,issues")                 # the stronger one repeats it, still no repro
        self.assertEqual(out["review"]["verdict"], "pass", out)
        self.assertNotIn("kind", out)


if __name__ == "__main__":
    unittest.main()
