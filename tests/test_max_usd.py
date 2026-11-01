"""P0-15 `ccx run --max-usd`: the whole delegation (rungs, review, fix round) stops once it has spent its cap, and the
receipt says "budget cap reached". Fake CLIs only; never a real claude/codex."""
import json
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ccx.commands.delegation import max_usd  # noqa: E402
from ccx.config import Paths  # noqa: E402
from test_ccx import Env  # noqa: E402

TINY = "0.0000001"


class TestDefault(unittest.TestCase):
    def test_flag_then_config_and_zero_is_no_limit(self):
        a = SimpleNamespace(max_usd=None)
        self.assertIsNone(max_usd(a, {}))
        self.assertIsNone(max_usd(a, {"run": {"max_usd": 0}}))           # the shipped default: no limit
        self.assertEqual(max_usd(a, {"run": {"max_usd": 1.5}}), 1.5)
        self.assertEqual(max_usd(SimpleNamespace(max_usd=0.2), {"run": {"max_usd": 1.5}}), 0.2)
        self.assertIsNone(max_usd(SimpleNamespace(max_usd=0), {"run": {"max_usd": 1.5}}))   # 0 on the line: off
        self.assertIsNone(max_usd(a, {"run": {"max_usd": "x"}}))


class TestRun(Env):
    def setUp(self):
        super().setUp()
        g = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.run(["git", "init", "-q"], cwd=self.work, check=True)
        (self.work / "a.py").write_text("x = 1\n", encoding="utf-8")
        subprocess.run([*g, "add", "a.py"], cwd=self.work, check=True)
        subprocess.run([*g, "commit", "-qm", "init"], cwd=self.work, check=True)

    def go(self, *extra, review_seq="pass"):
        env = {"FAKE_WRITE": f"{self.work / 'a.py'}=x = 2\n", "FAKE_REVIEW": review_seq}
        r = self.ccx("run", "--to", "codex", "--model", "gpt-6-luna", "--effort", "low", "--mode", "write",
                     "--no-fallback", *extra, "change x to 2 in a.py", env=env)
        self.assertIn(r.returncode, (0, 1, 2), r.stderr)
        return json.loads(r.stdout)

    def reviews(self):
        return [c for c in self.calls() if c["agent"] == "claude" and "[ccx review" in c["prompt"]]

    def builds(self):
        return [c for c in self.calls() if c["agent"] == "codex"]

    def test_no_cap_is_as_before(self):
        out = self.go("--review", "on")
        self.assertNotIn("max_usd", out)
        self.assertNotIn("max_usd=", out["recap"])
        self.assertEqual(len(self.reviews()), 1)

    def test_cap_reached_skips_the_review(self):
        out = self.go("--review", "on", "--max-usd", TINY)
        self.assertEqual(self.reviews(), [])
        m = out["max_usd"]
        self.assertEqual((m["stopped_before"], m["note"], m["cap"]), ("review", "budget cap reached", float(TINY)))
        self.assertGreater(m["spent"], 0)
        self.assertIn("budget cap reached", out["hint"])
        self.assertIn("max_usd=reached", out["recap"])

    def test_cap_reached_skips_the_next_rung(self):
        out = self.go("--review", "off", "--check", "exit 1", "--max-usd", TINY)
        self.assertEqual(len(self.builds()), 1, self.builds())          # no second attempt
        self.assertEqual(out["max_usd"]["stopped_before"], "attempt")
        self.assertEqual(out["kind"], "check_failed")
        # without a cap the same run climbs
        subprocess.run(["git", "checkout", "a.py"], cwd=self.work, check=True)
        n = len(self.builds())
        self.go("--review", "off", "--check", "exit 1")
        self.assertGreater(len(self.builds()) - n, 1)

    def test_cap_reached_hands_review_issues_to_the_lead_instead_of_a_fix_round(self):
        first = self.go("--review", "on", review_seq="issues")            # measure: one build + one review
        rows = [json.loads(x) for x in Paths(self.hub).ledger.read_text(encoding="utf-8").splitlines()]
        r0 = first["fixed_after_review_of"]
        build = next(r["ae_usd"] for r in rows if r.get("run_id") == r0)
        rev = next(r["ae_usd"] for r in rows if r.get("label") == f"review:{r0}")
        self.assertGreater(rev, 0)
        subprocess.run(["git", "checkout", "a.py"], cwd=self.work, check=True)
        n = len(self.reviews())
        out = self.go("--review", "on", "--max-usd", str(build + rev / 2), review_seq="issues")
        self.assertEqual(len(self.reviews()) - n, 1)                     # reviewed, not fixed
        self.assertEqual(out["kind"], "review_issues")
        self.assertNotIn("fixed_after_review_of", out)
        self.assertEqual(out["max_usd"]["stopped_before"], "fix round")
        self.assertIn("budget cap reached", out["hint"])

    def test_config_default_and_resume_flag(self):
        Paths(self.hub).user_tiers.parent.mkdir(parents=True, exist_ok=True)
        Paths(self.hub).user_tiers.write_text(f"[run]\nmax_usd = {TINY}\n", encoding="utf-8")
        out = self.go("--review", "on")
        self.assertEqual(out["max_usd"]["stopped_before"], "review")
        self.assertEqual(self.ccx("config", "set", "run.max_usd", "0").returncode, 0)
        r = self.ccx("resume", out["run_id"], "go on", "--max-usd", TINY, "--review", "on",
                     env={"FAKE_WRITE": f"{self.work / 'a.py'}=x = 3\n", "FAKE_REVIEW": "pass"})
        res = json.loads(r.stdout)
        self.assertEqual(res["max_usd"]["stopped_before"], "review", res)


if __name__ == "__main__":
    unittest.main()
