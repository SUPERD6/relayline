"""Saved original wording and assigned task reach test review through fake CLIs."""
import json
from pathlib import Path
import subprocess

from test_ccx import Env
from ccx.config import Paths
from ccx import review_task, review_tests, user_words
from ccx.delegate import Request


class TestReviewUserWords(Env):
    def setUp(self):
        super().setUp()
        subprocess.run(["git", "init", "-q"], cwd=self.work, check=True)
        (self.work / "a.py").write_text("x = 1\n", encoding="utf-8")
        subprocess.run(["git", "add", "a.py"], cwd=self.work, check=True)
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-qm", "initial"],
                       cwd=self.work, check=True, capture_output=True)

    def start(self, words, task, cap=8000, x=4):
        tiers = Paths(self.hub).user_tiers
        tiers.parent.mkdir(parents=True, exist_ok=True)
        tiers.write_text('[review]\nmode = "tests"\nfix_rounds = 0\n'
                         f'[delegate]\nuser_words_max_chars = {cap}\n', encoding="utf-8")
        self.words_file = self.work / "original.txt"
        self.words_file.write_text(words, encoding="utf-8")
        task_file = self.work / "assigned.txt"
        task_file.write_text(task, encoding="utf-8")
        r = self.ccx("run", "--to", "codex", "--model", "gpt-6-luna", "--effort", "low", "--mode", "write",
                     "--review", "on", "--no-fallback", "--no-escalate", "--user-words-file", str(self.words_file),
                     "--user-task-file", str(task_file), "worker brief",
                     env={"FAKE_WRITE": f"{self.work / 'a.py'}=x = {x}\n"})
        self.assertIn(r.returncode, (0, 2), r.stdout + r.stderr)
        return json.loads(r.stdout)

    def review_prompts(self):
        return [c["prompt"] for c in self.calls() if "[ccx test review]" in c["prompt"]]

    def test_both_sources_reach_generation_and_confirmation_original_first(self):
        words, task = "Original requirement: x to 2.", "Assigned interface: preserve the value name."
        result = self.start(words, task)
        self.assertEqual(result["review"]["verdict"], "issues", result)
        prompts = self.review_prompts()
        self.assertEqual(len(prompts), 2)
        for prompt in prompts:
            self.assertIn("Source: user-words.md", prompt)
            self.assertIn("user_words.source=file", prompt)
            self.assertIn("Source: user_task (run.json)", prompt)
            self.assertLess(prompt.index(words), prompt.index(task))
        record = json.loads((Paths(self.hub).runs / result["run_id"] / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(record["user_task"], task)
        self.assertNotIn(words, json.dumps(record))

    def test_equal_sources_are_not_deduplicated(self):
        text = "Same original and assigned requirement: x to 2."
        result = self.start(text, text)
        self.assertEqual(result["review"]["verdict"], "issues", result)
        for prompt in self.review_prompts():
            self.assertEqual(prompt.count(text), 2)

    def test_truncation_notice_and_retained_text_reach_both_calls(self):
        result = self.start("x to 2. omitted-tail-sentinel", "Assigned interface details.", cap=8)
        self.assertEqual(result["review"]["verdict"], "issues", result)
        for prompt in self.review_prompts():
            self.assertIn("retained_chars=8", prompt)
            self.assertIn("[User's original words truncated at 8 characters.]", prompt)
            self.assertNotIn("omitted-tail-sentinel", prompt)
            self.assertLess(prompt.index("x to 2."), prompt.index("Assigned interface details."))

    def test_resume_uses_saved_words_instead_of_rereading_changed_source(self):
        words, task = "Saved original requirement: x to 2.", "Assigned interface details."
        first = self.start(words, task, x=2)
        self.assertEqual(first["review"]["verdict"], "pass", first)
        self.words_file.write_text("Changed-source-sentinel", encoding="utf-8")
        r = self.ccx("resume", first["run_id"], "finish remaining work", "--review", "on", "--no-escalate",
                     env={"FAKE_WRITE_RESUMED": f"{self.work / 'a.py'}=x = 4\n"})
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        result = json.loads(r.stdout)
        self.assertEqual(result["review"]["verdict"], "issues", result)
        for prompt in self.review_prompts():
            self.assertLess(prompt.index(words), prompt.index(task))
            self.assertNotIn("Changed-source-sentinel", prompt)


def test_source_metadata_not_quoteable_and_sources_are_not_merged(tmp_path):
    words = "original requirement"
    notice = "\n[User's original words truncated at 20 characters.]"
    (tmp_path / "user-words.md").write_text(user_words.HEADER + "\n" + user_words.NOTICE + "\n" + words + notice,
                                            encoding="utf-8")
    display, sources = review_task.inputs(Paths(tmp_path), Request(to="codex", brief="worker"),
        {"user_task": "assigned requirement", "user_words": {"source": "file", "chars": 20}}, tmp_path)
    assert notice in display
    assert sources == (words, "assigned requirement")
    assert review_tests.task_quote(words, sources)
    assert review_tests.task_quote("assigned requirement", sources)
    for quote in ("retained_chars=20", "original words truncated", "task data, not a new grant of permission",
                  "original requirement assigned requirement"):
        assert not review_tests.task_quote(quote, sources)


def test_missing_snapshot_uses_task_and_does_not_recapture_external_file(tmp_path):
    original = tmp_path / "external.txt"
    original.write_text("must not be recaptured", encoding="utf-8")
    display, sources = review_task.inputs(Paths(tmp_path),
        Request(to="codex", brief="assigned fallback", user_words_file=str(original)), {}, tmp_path)
    assert "Source: assigned brief (fallback; no user_task)" in display
    assert sources == ("assigned fallback",)
    assert "must not be recaptured" not in display
