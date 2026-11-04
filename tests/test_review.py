"""F1: independent review of a write run's diff by another vendor's cheap model (fake CLIs only)."""
import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ccx import review  # noqa: E402
from test_ccx import Env  # noqa: E402


class TestReason(unittest.TestCase):
    def test_when(self):
        ok = {"open_questions": []}
        self.assertIsNone(review.reason("auto", "low", ok, ["a.py"], ["a.py"]))
        self.assertIsNone(review.reason("on", None, ok, [], []))                     # nothing changed
        self.assertIsNone(review.reason("off", "critical", ok, [], ["a.py"]))
        self.assertEqual(review.reason("on", None, ok, ["a.py"], ["a.py"]), "asked")
        self.assertEqual(review.reason("auto", "visible", ok, ["a.py"], ["a.py"]), "risk visible")
        self.assertIn("unsure", review.reason("auto", None, {"open_questions": ["x?"]}, ["a.py"], ["a.py"]))
        self.assertIn("don't match", review.reason("auto", None, ok, ["b.py"], ["src/a.py"]))
        self.assertIsNotNone(review.reason("auto", None, ok, [], ["a.py"]))
        self.assertIsNone(review.reason("auto", None, ok, ["./src\\a.py"], ["src/a.py"]))
        self.assertIn("60 changed code lines", review.reason("auto", None, ok, ["a.py"], ["a.py"], 60))
        self.assertIsNone(review.reason("auto", None, ok, ["a.py"], ["a.py"], 60, min_lines=0))
        d = "+++ b/a.py\n" + "+x\n" * 3 + "-y\n" + "+++ b/README.md\n" + "+doc\n" * 9
        self.assertEqual(review.code_lines(d), 4)

    def test_reviewer_is_another_vendor(self):
        cfg = {"review": {"by": {"codex": "claude:haiku:low", "claude": "codex:gpt-6-luna:low"}}}
        self.assertEqual(review.reviewers(cfg, "codex", lambda a: True), [("claude", "haiku", "low")])
        self.assertEqual(review.reviewers(cfg, "claude", lambda a: True)[0], ("codex", "gpt-6-luna", "low"))
        self.assertEqual(review.reviewers(cfg, "codex", lambda a: a == "codex"), [])
        cfg["review"]["by"]["deepseek"] = "codex:gpt-6-luna:low"
        self.assertEqual(review.reviewers(cfg, "gemini", lambda a: True),
                         [("claude", "haiku", "low"), ("codex", "gpt-6-luna", "low")])

    def test_vendor_not_cli_decides_who_is_another(self):
        cfg = {"review": {"by": {}}, "providers": {"deepseek": {"agent": "claude"}}}
        # DeepSeek runs through the Claude CLI but is its own vendor: Claude may review it (I3)
        self.assertEqual(review.reviewers({**cfg, "review": {"also": ["claude:haiku:low"]}}, "deepseek",
                                          lambda a: True), [("claude", "haiku", "low")])
        self.assertEqual(review.reviewers({**cfg, "review": {"also": ["claude:haiku:low"]}}, "claude",
                                          lambda a: True), [])
        from ccx import agents
        self.assertTrue(agents.same_vendor("claude", "claude"))
        self.assertFalse(agents.same_vendor("claude", "deepseek", cfg))
        cfg["providers"]["deepseek"]["vendor"] = "anthropic"          # a provider can say it is the same vendor
        self.assertTrue(agents.same_vendor("claude", "deepseek", cfg))

    def test_cheapest_rung_before_routing_and_fallback(self):
        cfg = {"review": {"also": ["claude:sonnet:medium"]},
               "tiers": {"T1": {"claude": {"model": "haiku", "effort": "low"},
                                "codex": {"model": "gpt-6-luna", "effort": "low"}}}}
        got = review.reviewers(cfg, "codex", lambda a: a in ("codex", "claude"))
        self.assertEqual(got, [("claude", "haiku", "low"), ("claude", "sonnet", "medium")])   # sonnet only after
        self.assertEqual(review.reviewers(cfg, "claude", lambda a: a in ("codex", "claude"))[0],
                         ("codex", "gpt-6-luna", "low"))

    def test_brief_asks_for_requirements_not_tests(self):
        b = review.brief("r1", "task", "did it", "+x", 100)
        self.assertIn("requirement by requirement", b)
        # round 5: [must] only with a basis in the task or a broken existing behaviour; the rest is a note
        self.assertIn('`[must] file:line — "task words" — what is wrong` is only for', b)
        self.assertIn("quoting the task sentence it rests on", b)
        self.assertIn("existing tests, or crashes on inputs the task itself names", b)
        self.assertIn("A [must] without such a basis is treated as a note", b)
        self.assertIn("hardening, extra validation, edge cases or robustness the task did not ask for", b)

    def test_out_of_scope_must_is_a_note(self):
        for item in ("[must] (out of scope) run.json may be missing", "[must] Hardening: corrupt JSON crashes load()",
                     "[must] — not asked for: make it idempotent", "[MUST] [beyond the task] retry on EOF",
                     "  [must] robustness — no guard for empty files"):
            v = review.verdict({"summary": "REVIEW: issues", "open_questions": [item]})
            self.assertEqual((v["verdict"], v["issues"]), ("pass", []), item)
            self.assertTrue(v["notes"][0].startswith("[note]"), v)
        # a real [must] next to an out-of-scope one still triggers the fix round, with only the real one
        v = review.verdict({"summary": "REVIEW: issues", "open_questions": [
            "[must] (out of scope) no lock", '[must] a.py:3 — "return the SKUs" — returns Item objects']})
        self.assertEqual((v["verdict"], len(v["issues"])), ("issues", 1))
        self.assertIn("SKUs", v["issues"][0])
        # words like "robustness" later in a real item do not demote it
        v = review.verdict({"summary": "REVIEW: issues", "open_questions": [
            '[must] a.py:3 — "raise ValueError for n < 1" — no robustness check, n=0 passes']})
        self.assertEqual(v["verdict"], "issues")

    def test_at_most_one_fix_round(self):
        self.assertEqual([review.fix_rounds({"fix_rounds": n}) for n in (0, 1, 2, 5, "x")], [0, 1, 1, 1, 1])
        self.assertEqual(review.fix_rounds({}), 1)

    def test_fix_round_is_reviewed_against_the_first_task(self):
        import tempfile
        from ccx.config import Paths
        from ccx.delegate import Request
        with tempfile.TemporaryDirectory() as d:
            p = Paths(Path(d))
            (p.runs / "r0").mkdir(parents=True)
            (p.runs / "r0" / "brief.md").write_text("change x to 2", encoding="utf-8")
            (p.runs / "r1").mkdir()                                 # a resume of r0: no brief.md of its own
            (p.runs / "r1" / "run.json").write_text(json.dumps({"resumed_from": "r0"}), encoding="utf-8")
            fix = Request(to="codex", brief="An independent review found ...", resume_run="r1", review_round=1)
            self.assertEqual(review.task_for_review(p, fix), "change x to 2")
            plain = Request(to="codex", brief="follow-up", resume_run="r1")      # not a fix round: its own brief
            self.assertEqual(review.task_for_review(p, plain), "follow-up")
            lost = Request(to="codex", brief="issues", resume_run="gone", review_round=1)
            self.assertEqual(review.task_for_review(p, lost), "issues")

    def test_reviewers_from_routing_data(self):
        import tempfile
        from pathlib import Path
        from ccx.config import Paths
        with tempfile.TemporaryDirectory() as d:
            got = review.reviewers({"review": {}}, "claude", lambda a: a in ("codex", "claude"), Paths(Path(d)))
        self.assertTrue(got and all(a == "codex" for a, _, _ in got))     # routing's cheapest codex read rung

    def test_verdict(self):
        self.assertEqual(review.verdict({"summary": "REVIEW: issues", "open_questions": ["a"]})["verdict"], "issues")
        self.assertEqual(review.verdict({"summary": "review: pass — fine"})["verdict"], "pass")
        self.assertEqual(review.verdict({"summary": "looks ok"})["verdict"], "unclear")
        mixed = review.verdict({"summary": "REVIEW: issues", "open_questions": ["[note] style", "[must] a.py:1 — bug"]})
        self.assertEqual((mixed["verdict"], mixed["issues"]), ("issues", ["[must] a.py:1 — bug"]))
        notes = review.verdict({"summary": "REVIEW: issues", "open_questions": ["[note] Unicode names"]})
        self.assertEqual((notes["verdict"], notes["issues"], notes["notes"]), ("pass", [], ["[note] Unicode names"]))

    def test_verdict_without_the_review_line(self):
        # round 2 of the seven-cores A/B: haiku wrote its summary in Chinese and named the real bug as [must]
        zh = review.verdict({"summary": "检查了三项要求：low_stock 返回的是 Item 对象", "open_questions":
                             ["[must] inventory/report.py:1-3 — returns Item objects, the task asks for SKUs",
                              "[note] no test for remove_stock"]})
        self.assertEqual((zh["verdict"], zh["format"], len(zh["issues"])), ("issues", "lenient", 1))
        ok = review.verdict({"summary": "都符合要求", "open_questions": ["[note] style"]})
        self.assertEqual((ok["verdict"], ok["format"]), ("pass", "lenient"))
        self.assertEqual(review.verdict({"summary": "**REVIEW：issues** x", "open_questions": ["[must] a"]})["verdict"],
                         "issues")
        self.assertEqual(review.verdict({"summary": "`REVIEW: pass`"})["verdict"], "pass")
        self.assertEqual(review.verdict({"summary": "no idea", "open_questions": ["something"]})["verdict"], "unclear")
        self.assertEqual(review.verdict({"summary": "REVIEW: passing thoughts"})["verdict"], "unclear")

    def test_long_issue_kept_whole_for_the_fix_round(self):
        # r5: ~2 in 3 [must] items were cut at 300 characters before the fix brief; the cut part held the fix
        long = "[must] a.py:3 — " + "map blocked to split; " * 30 + "and add a test for the split status"
        self.assertGreater(len(long), 600)
        v = review.verdict({"summary": "REVIEW: issues", "open_questions": [long, "[must] b.py:1 — short"]})
        self.assertEqual(v["issues"], [long[:300], "[must] b.py:1 — short"])        # the lead's short form
        self.assertEqual(v["issues_full"], [long, "[must] b.py:1 — short"])
        huge = "[must] " + "y" * 3000
        v = review.verdict({"summary": "REVIEW: issues", "open_questions": [huge] * 10})
        self.assertEqual((len(v["issues_full"]), {len(x) for x in v["issues_full"]}), (8, {review.ISSUE_FULL_CHARS}))
        short = review.verdict({"summary": "REVIEW: issues", "open_questions": ["[must] a"]})
        self.assertNotIn("issues_full", short)
        s = "REVIEW: issues " + "z" * 900
        v = review.verdict({"summary": s})
        self.assertEqual((len(v["summary"]), v["summary_full"]), (400, s))

    def test_review_line_inside_an_item(self):
        # #154 replay, r5f:1: no REVIEW line in the summary, the first item began "REVIEW: issues" + a [must]
        for items in (["REVIEW: issues [must] a.py:3 — off by one"],
                      ["REVIEW: issues\n[must] a.py:3 — off by one\n[must] b.py:1 — no test"],
                      ["**REVIEW: issues**", "[must] a.py:3 — off by one"]):
            v = review.verdict({"summary": "checked the change", "open_questions": items})
            self.assertEqual((v["verdict"], v["format"]), ("issues", "lenient"), items)
            self.assertTrue(v["issues"][0].startswith("[must] a.py:3"), v)
        two = review.verdict({"summary": "checked", "open_questions": [
            "REVIEW: issues\n[must] a.py:3 — off by one\n[must] b.py:1 — no test"]})
        self.assertEqual(len(two["issues"]), 2)
        v = review.verdict({"summary": "checked", "open_questions": ["REVIEW: issues", "the loop is off by one"]})
        self.assertEqual((v["verdict"], v["issues"]), ("issues", ["the loop is off by one"]))
        self.assertEqual(review.verdict({"summary": "checked", "open_questions": ["REVIEW: pass"]})["verdict"], "pass")
        # verdicts the summary already decides are unchanged: the item's line is not read then
        same = [({"summary": "REVIEW: pass", "open_questions": ["REVIEW: issues [must] x"]}, "pass"),
                ({"summary": "REVIEW: issues", "open_questions": ["REVIEW: pass", "[note] style"]}, "pass"),
                ({"summary": "REVIEW: issues", "open_questions": ["[must] a"]}, "issues"),
                ({"summary": "no idea", "open_questions": ["something"]}, "unclear"),
                ({"summary": "checked", "open_questions": ["REVIEW: pass", "something odd"]}, "unclear")]
        for res, want in same:
            self.assertEqual(review.verdict(res)["verdict"], want, res)

    def test_brief_rubric_traces_the_normal_path(self):
        b = review.brief("r1", "task", "did it", "+x", 100)
        self.assertIn("fails on its normal path, even silently", b)
        self.assertIn("a name used but not defined or imported in that scope", b)
        self.assertIn("`except Exception: pass`", b)
        self.assertIn("only works\nfrom the repo directory", b)
        self.assertIn("trace the entry point the task names", b)
        self.assertNotIn("Existing tests edited", b)

    def test_edited_tests(self):
        diff = ("diff --git a/tests/test_old.py b/tests/test_old.py\n--- a/tests/test_old.py\n+++ b/tests/test_old.py\n"
                "@@ -1,2 +1,2 @@\n def test_x():\n-    assert f() == 1\n+    assert f() == 2\n"
                "--- a/tests/test_more.py\n+++ b/tests/test_more.py\n@@ -3,0 +4,2 @@\n+def test_y():\n+    pass\n"
                "--- /dev/null\n+++ b/tests/test_new.py\n@@ -0,0 +1 @@\n+def test_z(): pass\n"
                "--- a/src/lib.py\n+++ b/src/lib.py\n@@ -1 +1 @@\n-x = 1\n+x = 2\n"
                "--- a/test_gone.py\n+++ /dev/null\n@@ -1 +0,0 @@\n-def test_g(): pass\n")
        self.assertEqual(review.edited_tests(diff), ["tests/test_old.py", "test_gone.py"])
        self.assertEqual(review.edited_tests(""), [])
        b = review.brief("r1", "task", "did it", diff, 100_000)
        self.assertIn("Existing tests edited: tests/test_old.py, test_gone.py — check the task requires it", b)

    def test_edited_tests_are_weak_evidence_past_the_cap(self):
        from ccx.config import Paths
        import tempfile
        p = Paths(Path(tempfile.mkdtemp()))
        rec = {"run_id": "r", "check": {"cmd": "python -m pytest", "passed": True}}
        rc = {"weak_daily": 0}
        self.assertEqual(review.weak_reason(p, rc, rec, edited=["tests/test_a.py"]),
                         "existing tests edited: tests/test_a.py")
        self.assertIsNone(review.weak_reason(p, {"weak": False}, rec, edited=["tests/test_a.py"]))

    def test_brief_says_what_ccx_ran(self):
        b = review.brief("r1", "task", "did it", "+x", 100, {"cmd": "make test", "passed": True, "exit": 0})
        self.assertIn("`make test` after the change: passed", b)
        self.assertIn("cannot run commands", b)


STORE = "class Store:\n    def get(self, k):\n        return 1\n\n    def remove(self, k, n):\n        return n\n"


class TestCheckGap(unittest.TestCase):
    """H13 without history: is a passed acceptance command evidence for *this* change?"""
    START = {"inv/__init__.py": "", "inv/store.py": STORE, "inv/report.py": "def summary(s):\n    return {}\n",
             "tests/test_inv.py": "from inv.report import summary\n\n\ndef test_s():\n    assert summary(None) == {}\n"}

    def change(self, files: dict) -> tuple[Path, list[str], str]:
        import tempfile
        d = Path(tempfile.mkdtemp())
        g = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.run(["git", "init", "-q"], cwd=d, check=True)
        for f, c in self.START.items():
            (d / f).parent.mkdir(parents=True, exist_ok=True)
            (d / f).write_text(c, encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=d, check=True)
        subprocess.run([*g, "commit", "-qm", "i"], cwd=d, check=True)
        base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=d, capture_output=True, text=True).stdout.strip()
        for f, c in files.items():
            (d / f).write_text(c, encoding="utf-8")
        actual, diff = review.changes(d, {"base": base, "untracked": [], "repo": str(d)})
        return d, actual, diff

    def test_commands_that_run_no_tests(self):
        for cmd in ("exit 0", "ruff check .", 'python -c "import inv"', "flake8", "mypy ."):
            self.assertIn("runs no tests", review.check_gap(cmd, Path("."), ["a.py"], ""), cmd)
        for cmd in ("python -m pytest -q", "npm test", "go test ./...", "cargo test", "python -m unittest",
                    "python tests/test_inv.py", "make check", "pnpm run test"):
            self.assertIsNotNone(review._TEST_CMD.search(cmd), cmd)

    def test_tests_that_miss_the_change(self):
        # like r2's inventory: the visible test imports the package but never calls what changed
        d, actual, diff = self.change({"inv/store.py": STORE.replace("        return n\n",
                                                                     "        if n < 1:\n            raise ValueError(n)\n"
                                                                     "        return n\n")})
        self.assertEqual(review.check_gap("python -m pytest -q", d, actual, diff),
                         "the tests it runs don't touch inv/store.py (never named)")
        d, actual, diff = self.change({"inv/report.py": "def summary(s):\n    return {}\n\n\ndef low(s):\n    return []\n"})
        self.assertEqual(review.check_gap("python -m pytest -q", d, actual, diff),
                         "the tests it runs don't touch inv/report.py: low")

    def test_tests_that_reach_the_change_are_strong(self):
        test = "from inv.report import summary\n\n\ndef test_s():\n    assert summary(None) == {'n': 0}\n"
        d, actual, diff = self.change({"inv/report.py": "def summary(s):\n    return {'n': 0}\n",
                                       "tests/test_inv.py": test})
        self.assertIsNone(review.check_gap("python -m pytest -q", d, actual, diff))
        self.assertIsNone(review.check_gap("python -m pytest -q", d, ["README.md"], ""))   # no code changed

    def test_only_the_named_tests_count(self):
        d, actual, diff = self.change({"inv/report.py": "def summary(s):\n    return {'n': 0}\n"})
        (d / "tests" / "test_other.py").write_text("def test_x():\n    pass\n", encoding="utf-8")
        self.assertIn("report.py", review.check_gap("python -m pytest tests/test_other.py", d, actual, diff))
        self.assertIsNone(review.check_gap("python -m pytest tests/test_inv.py", d, actual, diff))

    def test_changed_symbols(self):
        src = ("class A:\n    def f(self):\n        x = 1\n\n        return x\n\n    def _g(self):\n        pass\n"
               "\n\ndef h():\n    pass\nY = 2\n")
        self.assertEqual(review.changed_symbols(src, [3]), ["f"])
        self.assertEqual(review.changed_symbols(src, [8]), [])                 # a private helper: not asked for
        self.assertEqual(review.changed_symbols(src, [11, 12, 13]), ["h"])     # Y = 2 is module level
        self.assertEqual(review.changed_symbols(src, [1]), ["A"])

    def test_code_context(self):
        # r5 design PR A: the changed function in full, the same-file definition it calls, the tests naming it
        removed = STORE.replace("        return n\n", "        if n > self.get(k):\n            raise ValueError(n)\n"
                                                    "        return n\n")
        test = ("from inv.store import Store\n\n\ndef test_other():\n    assert 1\n\n\n"
                "def test_remove():\n    assert Store().remove('a', 1) == 1\n")
        d, actual, diff = self.change({"inv/store.py": removed})
        (d / "tests" / "test_inv.py").write_text(test, encoding="utf-8")
        ctx = review.code_context(d, diff, 10_000, "python -m pytest -q")
        self.assertIn("## Code around the change", ctx)
        self.assertIn("several reads in one turn", ctx)
        self.assertIn("### inv/store.py:5-8 (remove)\n```\n    def remove(self, k, n):", ctx)
        self.assertIn("### inv/store.py:2-3 (get)", ctx)                  # a same-file name it calls
        self.assertIn("### tests/test_inv.py:8-9 (test_remove)", ctx)
        self.assertNotIn("test_other", ctx)
        self.assertNotIn("left out", ctx)
        # the budget is what the diff leaves: too little -> the block shrinks or goes, never past the budget
        small = review.code_context(d, diff, 700, "python -m pytest -q")
        self.assertLessEqual(len(small), 700)
        self.assertIn("left out to fit", small)
        self.assertEqual(review.code_context(d, diff, 100, ""), "")
        self.assertEqual(review.code_context(None, diff, 10_000, ""), "")
        b = review.brief("r1", "task", "did it", diff, 12_000, {"cmd": "python -m pytest -q", "passed": True}, cwd=d)
        self.assertIn("### inv/store.py:5-8 (remove)", b)
        self.assertLess(b.index("```diff"), b.index("## Code around the change"), b)
        self.assertLess(b.index("## Code around the change"), b.index("## Checks"))
        self.assertNotIn("Code around the change", review.brief("r1", "task", "did it", diff, 12_000))
        self.assertNotIn("Code around the change", review.brief("r1", "task", "did it", diff, len(diff) + 50,
                                                                 cwd=d))

    def test_code_context_skips_new_code_the_diff_shows(self):
        d, actual, diff = self.change({"inv/report.py": "def summary(s):\n    return {}\n\n\ndef low(s):\n"
                                                         "    return summary(s)\n"})
        ctx = review.code_context(d, diff, 10_000)
        self.assertNotIn("(low)", ctx)                                     # wholly new: already in the diff
        self.assertIn("(summary)", ctx)                                    # but what it calls is shown

    def test_code_context_follows_imports_into_the_tree(self):
        d, actual, diff = self.change({"inv/report.py": "from .store import Store\nfrom os import getcwd\n\n\n"
                                                         "def summary(s):\n    getcwd()\n    return Store().get(s)\n"})
        ctx = review.code_context(d, diff, 10_000)
        self.assertIn("### inv/store.py:1-6 (Store)", ctx)                # imported from this repository
        self.assertNotIn("getcwd", ctx.split("```", 1)[0] + "".join(ctx.split("### ")[2:]))   # stdlib: not shown
        self.assertEqual(review._imports(d, "inv/report.py", "from . import store\nfrom .store import Store as S\n"
                                                            "def f():\n    from inv.report import summary\n"),
                         {"store": "inv/store.py", "S": "inv/store.py", "summary": "inv/report.py"})

    def test_spans(self):
        src = ["def f(", "    a,", "):", "    return a", "", "x = 1", "function g() {", "  return 1;", "}", "y()"]
        self.assertEqual(review._spans(src), [("f", 0, 3), ("g", 6, 8)])


class TestReviewRun(Env):
    def setUp(self):
        super().setUp()
        g = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.run(["git", "init", "-q"], cwd=self.work, check=True)
        (self.work / "a.py").write_text("x = 1\n", encoding="utf-8")
        subprocess.run([*g, "add", "a.py"], cwd=self.work, check=True)
        subprocess.run([*g, "commit", "-qm", "init"], cwd=self.work, check=True)

    def go(self, *extra, review_seq="pass", env_extra=None):
        env = {"FAKE_WRITE": f"{self.work / 'a.py'}=x = 2\n", "FAKE_REVIEW": review_seq, **(env_extra or {})}
        r = self.ccx("run", "--to", "codex", "--model", "gpt-6-luna", "--effort", "low", "--mode", "write",
                     "--no-fallback", *extra, "change x to 2 in a.py", env=env)
        self.assertEqual(r.returncode in (0, 2), True, r.stderr)
        return json.loads(r.stdout)

    def reviews(self):
        return [c for c in self.calls() if c["agent"] == "claude" and "[ccx review" in c["prompt"]]

    def test_strong_check_not_reviewed(self):
        # a passed acceptance command that runs a test naming the changed file: strong evidence, no review
        (self.work / "test_a.py").write_text("import a\nassert a.x == 2\n", encoding="utf-8")
        out = self.go("--check", f'"{sys.executable}" test_a.py')
        self.assertTrue(out["check"]["passed"], out)
        self.assertNotIn("review", out)
        self.assertEqual(self.reviews(), [])

    def test_edited_existing_test_forces_a_review(self):
        # round 5: the builder rewrote an existing test's assertion; the check then passed and nothing was reviewed
        g = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]
        (self.work / "test_a.py").write_text("import a\nassert a.x == 1\n", encoding="utf-8")
        subprocess.run([*g, "add", "test_a.py"], cwd=self.work, check=True)
        subprocess.run([*g, "commit", "-qm", "test"], cwd=self.work, check=True)
        env = {"FAKE_WRITE": f"{self.work / 'a.py'}=x = 2\n;{self.work / 'test_a.py'}=import a\nassert a.x == 2\n",
               "FAKE_REVIEW": "pass"}
        r = self.ccx("run", "--to", "codex", "--model", "gpt-6-luna", "--effort", "low", "--mode", "write",
                     "--no-fallback", "--check", f'"{sys.executable}" test_a.py', "change x to 2 in a.py", env=env)
        out = json.loads(r.stdout)
        self.assertTrue(out["check"]["passed"], out)
        self.assertEqual(out["review"]["reason"], "existing tests edited: test_a.py")
        self.assertEqual((out["edited_tests"], out["review"]["edited_tests"]), (["test_a.py"], ["test_a.py"]))
        from ccx.config import Paths
        rec = json.loads((Paths(self.hub).runs / out["run_id"] / "run.json").read_text(encoding="utf-8"))
        self.assertEqual((rec["review"]["edited_tests"], rec["edited_tests"]), (["test_a.py"], ["test_a.py"]))
        self.assertIn("Existing tests edited: test_a.py", self.reviews()[0]["prompt"])

    def test_check_without_tests_is_reviewed_with_no_history(self):
        # seven-cores r2: `--review auto` never fired in 36 runs because weak evidence needed history; a fresh hub
        # and a check that runs no tests now get one review, on the other vendor's cheapest rung only
        out = self.go("--check", "exit 0")
        self.assertEqual((out["review"]["reason"], out["review"]["by"]),
                         ("the acceptance command `exit 0` runs no tests", "claude:haiku:low"))
        self.assertEqual(len(self.reviews()), 1)

    def test_read_only_run_not_reviewed(self):
        r = self.ccx("run", "--to", "codex", "--model", "gpt-6-luna", "--effort", "low", "--mode", "read",
                     "--no-fallback", "look at a.py", env={"FAKE_REVIEW": "pass"})
        self.assertNotIn("review", json.loads(r.stdout))
        self.assertEqual(self.reviews(), [])

    def test_reviewer_is_not_told_to_run_tests(self):
        # r5 design PR A: the review prompt carried the builder's "run the tests" Finish text and "your shell tool
        # works", against the brief's "You cannot run commands"; the builder keeps its self-check
        from ccx import prompts
        self.go("--check", "exit 0")
        rev = self.reviews()[0]["prompt"]
        self.assertIn(prompts.REVIEW_FINISH, rev)
        self.assertIn("Permission: " + prompts.REVIEW_PERMISSION_CLAUDE, rev)      # a Claude reviewer: its own words
        self.assertNotIn("cat / Get-Content", rev)             # its allow-list refuses those (#7)
        for builder_text in ("The acceptance check is", "run the relevant tests"):
            self.assertNotIn(builder_text, rev)
        self.assertIn("cannot run commands", rev)
        self.assertIn("ccx ran the acceptance command `exit 0`", rev)
        build = [c["prompt"] for c in self.calls() if c["agent"] == "codex"][0]
        self.assertIn("The acceptance check is `exit 0`", build)
        self.assertNotIn(prompts.REVIEW_FINISH, build)

    def test_reviewer_text_without_a_check(self):
        # H13 weak-evidence review: no --check, so the Finish text must not claim ccx ran one
        from ccx import prompts
        self.go()
        rev = self.reviews()[0]["prompt"]
        self.assertIn(prompts.REVIEW_FINISH, rev)
        self.assertIn("No acceptance command was given", rev)
        self.assertNotIn("already ran the acceptance check", rev)

    def test_codex_reviewer_may_still_read_through_its_shell(self):
        # a Codex reviewer reads files only with shell commands; "run no commands" would leave it nothing to read
        from ccx import prompts
        env = {"FAKE_WRITE": f"{self.work / 'a.py'}=x = 2\n"}
        self.ccx("run", "--to", "claude", "--model", "haiku", "--effort", "low", "--mode", "write", "--no-fallback",
                 "--review", "on", "--check", "exit 0", "change x to 2 in a.py", env=env)
        rev = [c["prompt"] for c in self.calls() if c["agent"] == "codex" and "[ccx review" in c["prompt"]]
        self.assertTrue(rev, self.calls())
        self.assertIn("Permission: " + prompts.REVIEW_PERMISSION, rev[0])
        self.assertIn("your shell tool works", rev[0])
        self.assertIn(prompts.REVIEW_FINISH, rev[0])

    def test_code_context_is_opt_in(self):
        # off by default (the replay found fewer real bugs with it); [review] context = true adds it
        g = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]
        (self.work / "a.py").write_text("def f():\n    y = 0\n    return 1\n", encoding="utf-8")
        subprocess.run([*g, "commit", "-qam", "f"], cwd=self.work, check=True)
        env = {"FAKE_WRITE": f"{self.work / 'a.py'}=def f():\n    y = 0\n    return 2\n", "FAKE_REVIEW": "pass"}
        argv = ("run", "--to", "codex", "--model", "gpt-6-luna", "--effort", "low", "--mode", "write", "--no-fallback",
                "--check", "exit 0", "make f return 2")
        self.ccx(*argv, env=env)
        self.assertNotIn("## Code around the change", self.reviews()[-1]["prompt"])
        from ccx.config import Paths
        Paths(self.hub).user_tiers.write_text("[review]\ncontext = true\n", encoding="utf-8")
        subprocess.run(["git", "checkout", "a.py"], cwd=self.work, check=True)
        self.ccx(*argv, env=env)
        self.assertIn("### a.py:1-3 (f)", self.reviews()[-1]["prompt"])

    def test_weak_evidence_gets_one_cheap_review(self):
        # H13: no acceptance command, only the sub-agent's own check -> one review by the cheapest other-vendor rung
        out = self.go()
        self.assertEqual((out["review"]["verdict"], out["review"]["reason"], out["review"]["by"]),
                         ("pass", "only the sub-agent's own check", "claude:haiku:low"))
        self.assertEqual(len(self.reviews()), 1)
        self.assertNotIn("review", self.go("--review", "off"))           # --review off still means off

    def test_weak_check_is_reviewed(self):
        reset = lambda: (self.work / "a.py").write_text("x = 1\n", encoding="utf-8")  # noqa: E731
        for _ in range(3):                                                # the same check passed wrong work 3 times
            rid = self.go("--check", "exit 0")["run_id"]
            self.assertEqual(self.ccx("verify", rid, "--ok", "0").returncode, 0)
            reset()
        out = self.go("--check", "exit 0")
        self.assertEqual(out["check"]["weak"], "3/3 passed but judged wrong")
        self.assertTrue(out["review"]["reason"].startswith("weak check"))

    def test_weak_reviews_are_capped_and_can_be_switched_off(self):
        from ccx.config import Paths
        p = Paths(self.hub)
        rec = {"run_id": "r", "result": {"verification": "ran pytest"}}
        self.assertEqual(review.weak_reason(p, {"weak": False}, rec), None)
        self.assertEqual(review.weak_reason(p, {"weak": False}, {"run_id": "r"}), None)
        self.assertEqual(review.weak_reason(p, {}, {"run_id": "r", "result": {"verification": "not-run"}}),
                         "no acceptance command")
        self.assertEqual(review.weak_reason(p, {}, {**rec, "check": {"passed": True}}), None)   # nothing to judge with
        rc = {"weak_daily": 3}                                   # the "no acceptance command" one above counts
        self.assertEqual([review.weak_reason(p, rc, rec) is not None for _ in range(3)], [True, True, False])

    def test_issues_fixed_then_pass(self):
        out = self.go("--risk", "visible", review_seq="issues,pass")
        self.assertEqual(out["review"]["verdict"], "pass")
        self.assertEqual(out["review"]["first_round"]["verdict"], "issues")
        self.assertIn("fixed_after_review_of", out)
        rv = self.reviews()
        self.assertEqual(len(rv), 2)
        self.assertIn("x = 2", rv[0]["prompt"])                          # the reviewer saw the diff
        fix = [c for c in self.calls() if c["agent"] == "codex" and c["argv"][:2] == ["exec", "resume"]]
        self.assertTrue(fix and "off by one" in fix[-1]["prompt"])           # the issues went back to the worker
        self.assertIn("did not ask for", fix[-1]["prompt"])
        # the fix is judged against the task, not against the issue list it was handed
        task = rv[1]["prompt"].split("## The task it was given", 1)[1].split("## What it says it did", 1)[0]
        self.assertIn("change x to 2 in a.py", task)
        self.assertNotIn("off by one", task)

    def repair_receipt(self, verdict):
        from ccx.config import Paths
        from ccx.workspace import canonical
        from test_ccx import FAKES
        env = {"FAKE_WRITE": f"{self.work / 'a.py'}=x = 2\n", "FAKE_REVIEW": f"issues,{verdict}"}
        if verdict == "not-run":
            # Fail only reviewers after the first; keep the worker and its resumed session running normally.
            wrapper = self.work / "reviewer.py"
            wrapper.write_text("import os, runpy, sys\nfrom pathlib import Path\n"
                               "count = Path(os.environ['FAKE_LOG']).with_name('fake-review-count')\n"
                               "if count.exists():\n    os.environ['FAKE_STATUS_CLAUDE'] = 'quota'\n"
                               f"sys.path.insert(0, {str(FAKES)!r})\n"
                               f"runpy.run_path({str(FAKES / 'fake_claude.py')!r}, run_name='__main__')\n",
                               encoding="utf-8", newline="")
            env["CCX_CLAUDE_BIN"] = str(wrapper)
        r = self.ccx("run", "--to", "codex", "--model", "gpt-6-luna", "--effort", "low", "--mode", "write",
                     "--no-fallback", "--review", "on", "change x to 2 in a.py", env=env)
        self.assertEqual(r.returncode, 0, r.stderr)       # receipt changes never change the exit code or ok
        out = json.loads(r.stdout)
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["review"]["verdict"], verdict)
        self.assertEqual(out["review"]["first_round"]["verdict"], "issues")
        runs = Paths(self.hub).runs
        def load(rid):
            return json.loads((runs / rid / "run.json").read_text(encoding="utf-8"))

        first, fix = load(out["fixed_after_review_of"]), load(out["run_id"])
        self.assertEqual(fix["resumed_from"], first["run_id"])
        self.assertEqual(fix["session_id"], first["session_id"])
        reviewer_ids = [first["review"]["run_id"], fix["review"]["run_id"]]
        self.assertEqual(len(set([first["run_id"], fix["run_id"], *reviewer_ids])), 4)
        for rid in reviewer_ids:
            reviewer = load(rid)
            self.assertEqual((reviewer["to"], reviewer["mode"], reviewer["caller"]),
                             ("claude", "read", "ccx-review"))
            self.assertTrue(reviewer["ephemeral"])
            self.assertFalse(reviewer.get("resumed_from"))
            self.assertEqual(canonical(reviewer["cwd"]), canonical(self.work))
        for call in self.reviews():
            self.assertNotIn("--resume", call["argv"])
            task = call["prompt"].split("## The task it was given", 1)[1].split("## What it says it did", 1)[0]
            self.assertIn("change x to 2 in a.py", task)
            self.assertNotIn("off by one", task)
        marker = "repair_review_incomplete"
        if verdict == "pass":
            self.assertNotIn("needs_lead", out)
            self.assertNotIn(marker, out["recap"])
        else:
            why = "did not run" if verdict == "not-run" else "verdict is unclear"
            self.assertIn(f"{marker}: fix completed, but independent re-review {why}", out["needs_lead"])
            self.assertIn("not independently verified", out["needs_lead"])
            self.assertIn(f"needs_lead={marker}", out["recap"])
            self.assertIn(f"fix completed; independent re-review={verdict}", out["recap"])
        shown = json.loads(self.ccx("show", first["run_id"]).stdout)
        self.assertEqual(shown.get("needs_lead"), out.get("needs_lead"))
        self.assertEqual(shown["recap"], out["recap"])

    def test_repair_receipt_pass(self):
        self.repair_receipt("pass")

    def test_repair_receipt_unclear(self):
        self.repair_receipt("unclear")

    def test_repair_receipt_not_run(self):
        self.repair_receipt("not-run")

    def test_ordinary_unclear_receipt_has_no_repair_hint(self):
        out = self.go("--review", "on", review_seq="unclear")
        self.assertNotIn("fixed_after_review_of", out)
        self.assertNotIn("needs_lead", out)
        self.assertNotIn("repair_review_incomplete", out["recap"])
        self.assertNotIn("fix completed", out["recap"])

    def test_ordinary_not_run_receipt_has_no_repair_hint(self):
        out = self.go("--review", "on", env_extra={"FAKE_STATUS_CLAUDE": "quota"})
        self.assertEqual(out["review"]["verdict"], "not-run")
        self.assertNotIn("fixed_after_review_of", out)
        self.assertNotIn("needs_lead", out)
        self.assertNotIn("repair_review_incomplete", out["recap"])
        self.assertNotIn("fix completed", out["recap"])

    def test_long_must_reaches_the_fix_brief_whole(self):
        # r5: the fix brief got each [must] cut at 300 characters; the cut part held the fix the reviewer asked for
        must = ('[must] a.py:1 - "set x to 2" - ' +          # ASCII: an env var carries it to the fake reviewer
"the value is right but the loop maps blocked wrongly; " * 10
                + "map blocked to split and add a test for the split status (TAIL-MARK)")
        self.assertGreater(len(must), 600)
        env = {"FAKE_WRITE": f"{self.work / 'a.py'}=x = 2\n", "FAKE_REVIEW": "issues,pass", "FAKE_REVIEW_MUST": must}
        r = self.ccx("run", "--to", "codex", "--model", "gpt-6-luna", "--effort", "low", "--mode", "write",
                     "--no-fallback", "--review", "on", "change x to 2 in a.py", env=env)
        out = json.loads(r.stdout)
        fix = [c for c in self.calls() if c["agent"] == "codex" and c["argv"][:2] == ["exec", "resume"]]
        self.assertTrue(fix, self.calls())
        self.assertIn("- " + must + "\n", fix[-1]["prompt"])
        self.assertEqual(out["review"]["first_round"]["issues"][0], must[:300])   # the lead reads the short form

    def test_claude_reviewer_permission_denials_are_counted(self):
        # the denials Claude's result reports are kept per attempt (run.json) and summed in the ledger
        from ccx.config import Paths
        out = self.go("--check", "exit 0", env_extra={"FAKE_DENIALS": "2"})
        p = Paths(self.hub)
        rows = [json.loads(x) for x in p.ledger.read_text(encoding="utf-8").splitlines()]
        reviews = [x for x in rows if (x.get("label") or "").startswith("review:")]
        self.assertEqual([x.get("permission_denials") for x in reviews], [2], rows)
        rec = json.loads((p.runs / reviews[0]["run_id"] / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(rec["attempts"][-1]["permission_denials"], 2)
        builds = [x for x in rows if x.get("run_id") == out["run_id"]]
        self.assertTrue(builds and all("permission_denials" not in x for x in builds))   # Codex reports none

    def test_still_failing_after_fix(self):
        out = self.go("--review", "on", review_seq="issues")
        self.assertEqual(out["kind"], "review_failed")
        self.assertIn("independent review", out["hint"])
        self.assertIn("decide yourself", out["hint"])
        self.assertIn("fix the real ones yourself", out["hint"])    # the skill's rule; another round only on request
        self.assertNotIn("last resort", out["hint"])
        self.assertEqual(len(self.reviews()), 2)

    def test_cost_chain_after_a_fix_round_is_the_ledger_total(self):
        # plan I4: after a fix round the lead saw only the last run's cost; cost_chain sums the whole chain
        from ccx.config import Paths
        out = self.go("--review", "on", review_seq="issues")
        first, fix = out["fixed_after_review_of"], out["run_id"]
        rows = [json.loads(x) for x in Paths(self.hub).ledger.read_text(encoding="utf-8").splitlines()]
        mine = [r for r in rows if not r.get("type") and (r.get("run_id") in (first, fix)
                                                            or r.get("label") in (f"review:{first}", f"review:{fix}"))]
        self.assertEqual(len(mine), 4, rows)                    # two builder runs, two reviews
        self.assertIn("cost_chain", out, out.get("cost_chain_error"))
        cc = out["cost_chain"]
        self.assertEqual((cc["runs"], cc["reviews"]), ([first, fix], 2))
        self.assertAlmostEqual(cc["ae_usd"], sum(r["ae_usd"] or 0 for r in mine), places=6)
        self.assertGreater(cc["ae_usd"], sum(r["ae_usd"] or 0 for r in mine if r.get("run_id") == fix))
        for k in ("input", "cached", "output"):
            self.assertEqual(cc["tokens"][k], sum(r["usage"][k] for r in mine), k)
        self.assertNotEqual(cc["tokens"], out["tokens"])         # the run's own fields stay this run's
        self.assertIn(f"cost=~${cc['ae_usd']:.4f} (2 runs + 2 reviews)", out["recap"])
        shown = json.loads(self.ccx("show", first).stdout)       # the first id, no --wait: the chain's result
        self.assertEqual((shown["run_id"], shown["kind"], shown["cost_chain"]), (fix, "review_failed", cc))

    def test_fix_rereview_full_by_default(self):
        # [review] fix_rereview defaults to "full": the fix round's review is the plain brief and no end.json is kept
        from ccx.config import Paths
        out = self.go("--review", "on", review_seq="issues,pass")
        self.assertEqual(out["review"]["verdict"], "pass")
        second = self.reviews()[1]["prompt"]
        self.assertNotIn("The problems the first review found", second)
        self.assertNotIn("review of the fix round", second)
        self.assertNotIn("rereview", out["review"])
        self.assertFalse(list(Paths(self.hub).runs.glob("*/end.json")))

    def test_fix_rereview_focus_shows_the_fix_and_keeps_undo(self):
        from ccx.config import Paths
        runs = Paths(self.hub).runs
        (self.hub / "ccx").mkdir(parents=True, exist_ok=True)
        (self.hub / "ccx" / "tiers.toml").write_text('[review]\nfix_rereview = "focus"\n', encoding="utf-8")
        new = self.work / "b.py"
        env = {"FAKE_WRITE": f"{self.work / 'a.py'}=x = 2\n;{new}=y = 1\n",
               "FAKE_WRITE_RESUMED": f"{self.work / 'a.py'}=x = 3\n;{new}=y = 5\n", "FAKE_REVIEW": "issues,pass"}
        r = self.ccx("run", "--to", "codex", "--model", "gpt-6-luna", "--effort", "low", "--mode", "write",
                     "--no-fallback", "--review", "on", "change x to 2 in a.py", env=env)
        self.assertIn(r.returncode, (0, 2), r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out["review"]["verdict"], "pass", out)
        self.assertEqual(out["review"].get("rereview"), None)          # compact() keeps only its own keys
        fix_rec = json.loads((runs / out["run_id"] / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(fix_rec["review"]["rereview"], "focus")
        first_id = out["fixed_after_review_of"]
        rv = self.reviews()
        self.assertNotIn("The problems the first review found", rv[0]["prompt"])   # the first review is unchanged
        second = rv[1]["prompt"]
        whole, _, rest = second.partition("## The problems the first review found")
        self.assertIn("-x = 1", whole)                                     # the whole change is still there
        self.assertIn("+x = 3", whole)
        issues, _, fix = rest.partition("## The fix alone")
        self.assertIn("1. [must] a.py:3", issues)
        self.assertIn("off by one in the loop", issues)
        fix = fix.split("## Checks", 1)[0]
        self.assertIn("-x = 2", fix)                                       # only what the fix round changed
        self.assertIn("+x = 3", fix)
        self.assertIn("-y = 1", fix)                                       # a new file the first run made, too
        self.assertIn("+y = 5", fix)
        self.assertNotIn("-x = 1", fix)
        self.assertIn("review of the fix round", second.split("## Answer", 1)[1])
        # end.json is a file of its own: the undo snapshots are as before, and `ccx undo` of the fix round still
        # puts back the tree from before the whole chain (b.py moved aside, a.py back to x = 1)
        self.assertTrue((runs / first_id / "end.json").exists())
        snap1 = json.loads((runs / first_id / "undo.json").read_text(encoding="utf-8"))
        snap2 = json.loads((runs / out["run_id"] / "undo.json").read_text(encoding="utf-8"))
        self.assertNotIn("tree", snap1)
        self.assertEqual(snap1["base"], snap2["base"])
        self.assertEqual(snap2["chain_from"], first_id)
        u = self.ccx("undo", out["run_id"], "--apply")
        self.assertEqual(u.returncode, 0, u.stderr)
        self.assertEqual((self.work / "a.py").read_text(encoding="utf-8"), "x = 1\n")
        self.assertFalse(new.exists())
        st = subprocess.run(["git", "status", "--porcelain"], cwd=self.work, capture_output=True, text=True).stdout
        self.assertNotIn("a.py", st)

    def test_focus_brief_falls_back_to_the_fix_alone_past_the_cap(self):
        diff = "--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-x = 1\n+x = 2\n" + "+pad\n" * 50
        text = review.brief("r1", "task", "did it", diff, 120, focus={"issues": ["[must] a.py:1 — wrong"],
                                                                       "delta": "+x = 3\n"})
        self.assertNotIn("+pad", text)
        self.assertIn("the fix alone is shown below", text)
        self.assertIn("+x = 3", text)
        self.assertIn("1. [must] a.py:1 — wrong", text)
        plain = review.brief("r1", "task", "did it", diff, 12000)
        self.assertEqual(plain, review.brief("r1", "task", "did it", diff, 12000, focus=None))
        self.assertEqual(review.fix_rereview({}), "full")
        self.assertEqual(review.fix_rereview({"fix_rereview": "FOCUS"}), "focus")
        self.assertEqual(review.fix_rereview({"fix_rereview": "delta"}), "full")

    def test_resume_after_a_fix_run_reviews_and_undoes_the_whole_chain(self):
        # a fix run had no undo.json: resuming it reviewed an empty diff (--review on did nothing) and
        # `ccx undo FIX` said there was no snapshot. Now a resume or fix round inherits its chain's snapshot.
        from ccx.config import Paths
        runs = Paths(self.hub).runs
        fix = self.go("--review", "on", review_seq="issues")                # first run + one fix round, still failing
        self.assertEqual(fix["kind"], "review_failed")
        self.assertTrue((runs / fix["run_id"] / "undo.json").exists())
        r = self.ccx("resume", "--review", "on", fix["run_id"], "set x to 3 instead",
                     env={"FAKE_WRITE_RESUMED": f"{self.work / 'a.py'}=x = 3\n", "FAKE_REVIEW": "issues,issues,pass"})
        self.assertIn(r.returncode, (0, 2), r.stderr)
        again = json.loads(r.stdout or "null") or self.fail(r.stderr)
        self.assertEqual(again["review"]["verdict"], "pass", again)
        last = self.reviews()[-1]["prompt"]
        self.assertIn("-x = 1", last)                                       # diffed from the first run's snapshot
        self.assertIn("+x = 3", last)
        self.assertEqual(again["diffstat"], "1 file changed, 1 insertion(+), 1 deletion(-)")
        self.assertNotIn("you are the implementer", last)                   # the read-only reviewer is not told so
        u = self.ccx("undo", again["run_id"], "--apply")
        self.assertEqual(u.returncode, 0, u.stderr)
        self.assertEqual((self.work / "a.py").read_text(encoding="utf-8"), "x = 1\n")   # the whole chain rolled back
        self.assertIn("whole chain", json.loads(u.stdout)["warning"])         # and the person is told so

    def test_resume_after_the_lead_committed_does_not_inherit_the_chain_snapshot(self):
        # review: the lead accepted and committed run 1, then resumed it; `ccx undo FIX --apply` checked out the
        # pre-chain base and reverted the committed work. Now the fix run counts from its own start.
        from ccx.config import Paths
        runs = Paths(self.hub).runs
        first = self.go("--review", "off")
        g = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.run([*g, "commit", "-qam", "accept run 1"], cwd=self.work, check=True)
        r = self.ccx("resume", "--review", "off", first["run_id"], "set x to 3 instead",
                     env={"FAKE_WRITE_RESUMED": f"{self.work / 'a.py'}=x = 3\n"})
        self.assertIn(r.returncode, (0, 2), r.stderr)
        again = json.loads(r.stdout or "null") or self.fail(r.stderr)
        snap = json.loads((runs / again["run_id"] / "undo.json").read_text(encoding="utf-8"))
        self.assertIn("chain_broken", snap)
        self.assertNotIn("chain_from", snap)
        u = self.ccx("undo", again["run_id"], "--apply")
        self.assertEqual(u.returncode, 0, u.stderr)
        self.assertEqual((self.work / "a.py").read_text(encoding="utf-8"), "x = 2\n")   # the commit is kept

    def test_resume_after_the_lead_edited_does_not_inherit_the_chain_snapshot(self):
        from ccx.config import Paths
        runs = Paths(self.hub).runs
        first = self.go("--review", "off")
        (self.work / "b.py").write_text("y = 1\n", encoding="utf-8")       # the lead's own new file in between
        r = self.ccx("resume", "--review", "off", first["run_id"], "set x to 3 instead",
                     env={"FAKE_WRITE_RESUMED": f"{self.work / 'a.py'}=x = 3\n"})
        again = json.loads(r.stdout or "null") or self.fail(r.stderr)
        self.assertIn("chain_broken", json.loads((runs / again["run_id"] / "undo.json").read_text(encoding="utf-8")))
        self.ccx("undo", again["run_id"], "--apply")
        self.assertEqual((self.work / "a.py").read_text(encoding="utf-8"), "x = 2\n")
        self.assertTrue((self.work / "b.py").exists())                       # not moved aside as the run's file

    def test_reviewer_cache_ttl_is_opt_in_and_reviewer_only(self):
        def settings(call):
            a = call["argv"]
            return json.loads(a[a.index("--settings") + 1])
        self.go("--review", "on")
        self.assertNotIn("promptCacheTtl", settings(self.reviews()[-1]))            # default off
        (self.hub / "ccx" / "tiers.toml").write_text('[review]\ncache_ttl = "5m"\n', encoding="utf-8")
        (self.work / "a.py").write_text("x = 1\n", encoding="utf-8")                # so the next run changes it
        self.go("--review", "on", "--new")
        self.assertEqual(len(self.reviews()), 2)
        self.assertEqual(settings(self.reviews()[-1])["promptCacheTtl"], "5m")
        r = self.ccx("run", "--to", "claude", "--model", "haiku", "--effort", "low", "--mode", "write",
                     "--review", "off", "change x", env={"FAKE_WRITE": f"{self.work / 'a.py'}=x = 4\n"})
        self.assertEqual(r.returncode, 0, r.stderr)
        builder = [c for c in self.calls() if c["agent"] == "claude"][-1]
        self.assertNotIn("[ccx review", builder["prompt"])
        self.assertNotIn("promptCacheTtl", settings(builder))                        # a builder keeps the default

    def test_final_review_issues_is_not_ok_and_exits_2(self):
        # a final review_issues (no fix round ran, e.g. no session to resume): the [must] problems stand unfixed, so
        # the result is not ok and `ccx run` exits 2 (it exited 0 before)
        import contextlib
        import os
        from unittest import mock
        import io
        from ccx import cli, delegate
        rec = {"run_id": "20991231-100000-aaaa", "to": "codex", "tier": "T2", "ok": True, "state": "finished",
               "kind": "review_issues", "session_id": None, "mode": "write", "cwd": str(self.work),
               "result": {"status": "done", "summary": "did it"}, "review": {"verdict": "issues",
                                                                             "issues": ["[must] a.py:1 bug"]},
               "attempts": [{"agent": "codex", "model": "gpt-6-luna", "effort": "low", "usage4": {}, "seconds": 1,
                             "ok": True}]}
        self.assertFalse(delegate.compact(rec)["ok"])
        cwd, buf = os.getcwd(), io.StringIO()
        os.chdir(self.work)
        try:                                           # back before tearDown removes the folder (Windows)
            with mock.patch("ccx.commands.delegation.run", return_value=rec), contextlib.redirect_stdout(buf):
                code = cli.main(["run", "--from", "claude", "--to", "codex", "--model", "gpt-6-luna", "--effort",
                                 "low", "--mode", "write", "--no-fallback", "change x to 2 in a.py"])
        finally:
            os.chdir(cwd)
        out = json.loads(buf.getvalue())
        self.assertEqual((out["kind"], out["ok"], code), ("review_issues", False, 2), out)

    def test_edited_tests_flagged_without_a_review(self):
        # backlog 0a: a changed pre-existing test is shown for every write run, also with --review off
        g = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]
        (self.work / "test_a.py").write_text("import a\nassert a.x == 1\n", encoding="utf-8")
        subprocess.run([*g, "add", "test_a.py"], cwd=self.work, check=True)
        subprocess.run([*g, "commit", "-qm", "test"], cwd=self.work, check=True)
        env = {"FAKE_WRITE": f"{self.work / 'a.py'}=x = 2\n;{self.work / 'test_a.py'}=import a\nassert a.x == 2\n"}
        r = self.ccx("run", "--to", "codex", "--model", "gpt-6-luna", "--effort", "low", "--mode", "write",
                     "--no-fallback", "--review", "off", "change x to 2 in a.py", env=env)
        out = json.loads(r.stdout)
        self.assertNotIn("review", out)
        self.assertEqual(out["edited_tests"], ["test_a.py"])
        self.assertEqual(self.reviews(), [])

    def test_claude_worker_may_run_the_check(self):
        r = self.ccx("run", "--to", "claude", "--model", "haiku", "--effort", "low", "--mode", "write", "--review",
                     "off", "--check", '"C:\\py\\python.exe" -m unittest -q', "change x")
        self.assertEqual(r.returncode, 0, r.stderr)
        argv = [c["argv"] for c in self.calls() if c["agent"] == "claude"][-1]
        self.assertIn('Bash("C:\\py\\python.exe" -m unittest -q)', argv[argv.index("--allowed-tools") + 1])

    def test_off(self):
        out = self.go("--review", "off", "--risk", "critical")
        self.assertNotIn("review", out)


if __name__ == "__main__":
    unittest.main()
