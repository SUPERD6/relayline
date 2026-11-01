"""P2-12: ccx run itself puts a delegation's start and end (and a review fix round's) on the project's board, so
`ccx ui` / `ccx board` show it although no UI was open. Fake CLIs only; never a real claude/codex."""
import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from test_ccx import Env  # noqa: E402


class TestBoardRun(Env):
    def setUp(self):
        super().setUp()
        g = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.run(["git", "init", "-q"], cwd=self.work, check=True)
        (self.work / "a.py").write_text("x = 1\n", encoding="utf-8")
        (self.work / ".gitignore").write_text(".ccx/\n", encoding="utf-8")
        subprocess.run([*g, "add", "a.py", ".gitignore"], cwd=self.work, check=True)
        subprocess.run([*g, "commit", "-qm", "init"], cwd=self.work, check=True)

    def go(self, review="off", review_seq="pass"):
        env = {"FAKE_WRITE": f"{self.work / 'a.py'}=x = 2\n", "FAKE_REVIEW": review_seq}
        r = self.ccx("run", "--to", "codex", "--model", "gpt-6-luna", "--effort", "low", "--mode", "write",
                     "--no-fallback", "--review", review, "change x to 2 in a.py", env=env)
        self.assertIn(r.returncode, (0, 1, 2), r.stderr)
        return json.loads(r.stdout)

    def runs(self):
        f = self.work / ".ccx" / "board.jsonl"
        if not f.exists():
            return []
        es = [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]
        return [(e["run_id"], e["phase"], e["text"]) for e in es if e.get("kind") == "run"]

    def test_a_cli_run_posts_its_start_and_end(self):
        out = self.go()
        rid = out["run_id"]
        got = self.runs()
        self.assertEqual([(r, ph) for r, ph, _ in got], [(rid, "started"), (rid, "finished")], got)
        self.assertIn("→ codex: change x to 2 in a.py", got[0][2])
        self.assertTrue(got[1][2].startswith("Completed: "), got[1][2])
        self.assertIn(f"/runs/{rid}", got[1][2])
        self.go()                                                   # a second run: its own pair, nothing doubled
        self.assertEqual(len(self.runs()), 4)

    def test_a_review_fix_round_posts_its_own_pair_and_the_reviewer_none(self):
        out = self.go(review="on", review_seq="issues")
        first, fix = out["fixed_after_review_of"], out["run_id"]
        got = [(r, ph) for r, ph, _ in self.runs()]
        self.assertEqual(got, [(first, "started"), (first, "finished"), (fix, "started"), (fix, "finished")], got)

    def test_no_board_and_no_ignore_leaves_the_project_untouched(self):
        (self.work / ".gitignore").write_text("*.pyc\n", encoding="utf-8")
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qam", "ign"],
                       cwd=self.work, check=True)
        self.go()
        self.assertFalse((self.work / ".ccx" / "board.jsonl").exists())
        self.assertEqual((self.work / ".gitignore").read_text(encoding="utf-8"), "*.pyc\n")


if __name__ == "__main__":
    unittest.main()
