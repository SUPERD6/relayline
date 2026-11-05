"""R2 regressions with synthetic interfaces and fake CLIs; no benchmark assertions."""
import json
from pathlib import Path
import subprocess
import sys
from unittest import mock

import pytest

from test_ccx import Env, ROOT
from ccx import review_contract, review_tests
from ccx.config import Paths
from ccx.delegate import Request

sys.path.insert(0, str(ROOT / "scripts/eval"))
import p2_review_replay as replay


class TestR2Review(Env):
    def setUp(self):
        super().setUp()
        subprocess.run(["git", "init", "-q"], cwd=self.work, check=True)
        (self.work / "a.py").write_text('x = 1\ndef value(unit: str = "items") -> int:\n'
                                        '    """Return the item count."""\n    pass\n', encoding="utf-8")
        (self.work / "test_hidden.py").write_text("# never copy this test", encoding="utf-8")
        subprocess.run(["git", "add", "a.py", "test_hidden.py"], cwd=self.work, check=True)
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-qm", "stub"],
                       cwd=self.work, check=True, capture_output=True)

    def test_original_interfaces_checklist_and_markdown_confirmation_through_cli(self):
        tiers = Paths(self.hub).user_tiers
        tiers.parent.mkdir(parents=True, exist_ok=True)
        tiers.write_text('[review]\nmode = "tests"\nfix_rounds = 0\n', encoding="utf-8")
        task = 'change x to 2; use the [raise statement](https://example.invalid/reference#raise).'
        r = self.ccx("run", "--to", "codex", "--model", "gpt-6-luna", "--effort", "low", "--mode", "write",
                     "--review", "on", "--no-fallback", "--no-escalate", task,
                     env={"FAKE_WRITE": f"{self.work / 'a.py'}=x = 4\n", "FAKE_TEST_REVIEW": "fail",
                          "FAKE_TEST_QUOTE": "use the raise statement", "FAKE_CONFIRM_QUOTE": "use the raise statement"})
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        result = json.loads(r.stdout)
        self.assertEqual(result["review"]["verdict"], "issues", result)
        run = Paths(self.hub).runs / result["run_id"]
        interface = (run / "review-tests/interface.md").read_text(encoding="utf-8")
        self.assertIn("unit: str='items'", interface)
        self.assertIn("-> int", interface)
        self.assertNotIn("x = 4", interface)
        self.assertNotIn("test_hidden", interface)
        self.assertTrue((run / "review-tests/behaviors.json").is_file())
        calls = [c for c in self.calls() if "[ccx test review]" in c["prompt"]]
        self.assertEqual(len(calls), 2)
        for c in calls:
            self.assertIn(task, c["prompt"])
            self.assertIn(interface, c["prompt"])
        self.assertIn("First write ./behaviors.json", calls[0]["prompt"])
        self.assertIn("expected return type/shape/units", calls[0]["prompt"])
        self.assertNotIn("List each test file once", calls[0]["prompt"])

    def test_explicit_codex_pin_still_rejects_same_vendor_without_call(self):
        record = {"run_id": "synthetic"}
        never = mock.Mock(side_effect=AssertionError("must not launch a model"))
        review_tests.run_review(Request(to="codex", brief="x to 2"), Paths(self.hub),
                                {"review": {"tests_model": "codex:gpt-6.1-sol"}}, record, self.work, self.hub,
                                [("claude", "haiku", "low")], "asked", run_agent=never)
        self.assertEqual(record["review"]["by"], "codex:gpt-6.1-sol:low")
        self.assertFalse(record["review"]["independent"])
        self.assertEqual(record["review"]["verdict"], "unknown")
        never.assert_not_called()

    def test_claude_work_can_be_reviewed_by_pinned_codex_through_fake_cli(self):
        tiers = Paths(self.hub).user_tiers
        tiers.parent.mkdir(parents=True, exist_ok=True)
        tiers.write_text('[review]\nmode = "tests"\ntests_model = "codex:gpt-6.1-sol:medium"\n', encoding="utf-8")
        r = self.ccx("run", "--to", "claude", "--model", "haiku", "--effort", "low", "--mode", "write",
                     "--review", "on", "--no-fallback", "--no-escalate", "change x to 2 in a.py",
                     env={"FAKE_WRITE": f"{self.work / 'a.py'}=x = 2\n"})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        rv = json.loads(r.stdout)["review"]
        self.assertEqual(rv["by"], "codex:gpt-6.1-sol:medium", rv)
        self.assertEqual(rv["verdict"], "pass", rv)
        self.assertTrue(rv["independent"])

    def test_unicode_original_interface_and_context_limit(self):
        name = "接口.py"
        (self.work / name).write_text('def count() -> int:\n    """Original units."""\n    pass\n', encoding="utf-8")
        subprocess.run(["git", "add", "--", name], cwd=self.work, check=True)
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-qm", "interface"],
                       cwd=self.work, check=True, capture_output=True)
        (self.work / name).write_text("# changed implementation\n", encoding="utf-8")
        record = {"run_id": "synthetic", "review_interface_base": "HEAD"}
        contract = review_contract.before_change(Paths(self.hub), record, self.work)
        self.assertIn(name, contract)
        self.assertIn("def count() -> int", contract)
        self.assertTrue(contract.startswith("### " + name))
        self.assertIn("Unknown: remaining", review_contract.before_change(Paths(self.hub), record, self.work, limit=1))


@pytest.mark.parametrize("task,quote", [
    ('use the [raise statement](https://example.invalid/errors#raise) to "throw" a `ValueError`',
     'use the raise statement to "throw" a ValueError'),
    ('custom exception to be [raised (thrown)](https://example.invalid/errors) when empty',
     'custom exception to be raised thrown when empty'),
    ('custom exception to be [raised][raise docs]/"thrown" when empty',
     'custom exception to be raised thrown when empty'),
])
def test_markdown_link_labels_match_verbatim_words(task, quote):
    assert review_tests.task_quote(quote, task)
    assert not review_tests.task_quote(quote.replace("raise", "ignore"), task)


def test_contract_outline_is_from_public_declarations_not_function_bodies():
    text = 'class Shelf:\n    """Public interface."""\n    label: str\n    @property\n    def count(self) -> int:\n'
    text += '        """Number of items."""\n        return secret_builder_choice()\n'
    result = review_contract.outline(text)
    assert "@property" in result and "count(self) -> int" in result
    assert "Number of items." in result
    assert "label: str" in result
    assert "secret_builder_choice" not in result


def test_missing_original_interface_is_explicit_unknown(tmp_path):
    with mock.patch("ccx.review._git", return_value=""), mock.patch("ccx.workspace.run_snapshot", return_value=None):
        assert review_contract.before_change(Paths(tmp_path), {}, tmp_path).startswith("Unknown:")


@pytest.mark.parametrize("pin,expected", [("sonnet", ("claude", "sonnet", "low")),
    ("claude:sonnet:medium", ("claude", "sonnet", "medium")),
    ("codex:gpt-6.1-sol", ("codex", "gpt-6.1-sol", "low"))])
def test_qualified_model_keeps_legacy_model_strings(pin, expected):
    assert review_contract.reviewer([("claude", "haiku", "low")], {"tests_model": pin}) == expected


@pytest.mark.parametrize("worker,reason", [("codex", "same vendor"), ("claude", "native USD budget")])
def test_replay_codex_selection_retains_independence_and_native_budget_guards(tmp_path, capsys, worker, reason):
    p = Paths(tmp_path / "hub")
    p.user_tiers.parent.mkdir(parents=True)
    p.user_tiers.write_text('[review]\ntests_model = "codex:gpt-6.1-sol"\n', encoding="utf-8")
    job = tmp_path / "job.json"
    job.write_text(json.dumps({"key": "synthetic", "hub": str(p.hub), "implementer": worker}), encoding="utf-8")
    with mock.patch("ccx.review.reviewers", return_value=[("codex", "gpt-6-luna", "low")]), \
            mock.patch("ccx.review_tests.run_review", side_effect=AssertionError("no paid call")):
        replay.one(job)
    result = json.loads(capsys.readouterr().out)
    assert result["verdict"] == "unknown"
    assert reason in result["unknown_reasons"][0]
    assert result["usd"] == 0


@pytest.mark.parametrize("model", ["claude:sonnet", "codex:gpt-6.1-sol"])
def test_review_model_alias_and_estimate_from_outside_repo(tmp_path, model):
    result = subprocess.run([sys.executable, str(ROOT / "scripts/eval/p2_review_replay.py"), "--dry-run",
        "--results", str(tmp_path / "absent.jsonl"), "--artifacts", str(tmp_path / "absent"),
        "--review-model", model, "--unit-cap", f"{model}=0.4"], cwd=tmp_path,
        capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr
    assert f"reviewer model={model}" in result.stdout
    assert "unit-cap=$0.400" in result.stdout
    if model.startswith("codex:"):
        assert "no paid Codex calls will be launched" in result.stdout
