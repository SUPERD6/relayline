"""Synthetic regressions for the first test-review diagnostic; no paid CLIs or benchmark tests."""
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
from unittest import mock

import pytest

from test_ccx import Env, ROOT
from ccx.config import Paths

EVAL = ROOT / "scripts/eval"
sys.path.insert(0, str(EVAL))
import p2_review_replay as replay
import preflight


class TestReviewDiagnostics(Env):
    def setUp(self):
        super().setUp()
        subprocess.run(["git", "init", "-q"], cwd=self.work, check=True)
        (self.work / "a.py").write_text("x = 1\n", encoding="utf-8")
        subprocess.run(["git", "add", "a.py"], cwd=self.work, check=True)
        subprocess.run(["git", "-c", "user.name=test", "-c", "user.email=test@example.invalid", "commit", "-qm", "initial"],
                       cwd=self.work, check=True, capture_output=True)

    def run_review(self, scenario="pass", task="change x to 2 in a.py", x=2, settings="", env=None):
        (self.work / "a.py").write_text("x = 1\n", encoding="utf-8")
        tiers = Paths(self.hub).user_tiers
        tiers.parent.mkdir(parents=True, exist_ok=True)
        tiers.write_text('[review]\nmode = "tests"\nfix_rounds = 0\n' + settings, encoding="utf-8")
        raw = self.hub / "task.txt"
        raw.write_text(task, encoding="utf-8")
        r = self.ccx("run", "--to", "codex", "--model", "gpt-6-luna", "--effort", "low", "--mode", "write",
                     "--review", "on", "--no-fallback", "--no-escalate", "--user-task-file", str(raw),
                     "change x to 2 in a.py", env={"FAKE_TEST_REVIEW": scenario,
                     "FAKE_WRITE": f"{self.work / 'a.py'}=x = {x}\n", **(env or {})})
        self.assertIn(r.returncode, (0, 2), r.stdout + r.stderr)
        out = json.loads(r.stdout)
        rec = json.loads((Paths(self.hub).runs / out["run_id"] / "run.json").read_text(encoding="utf-8"))
        return rec["review"]

    def test_checks_local_manifest_is_executed(self):
        rv = self.run_review("local-manifest")
        self.assertEqual((rv["verdict"], rv["tests_run"]), ("pass", 1), rv)
        self.assertTrue(Path(rv["manifest_path"]).is_file())

    def test_duplicate_file_with_valid_quotes_runs_once(self):
        rv = self.run_review("duplicate")
        self.assertEqual((rv["verdict"], rv["tests_run"]), ("pass", 1), rv)
        self.assertEqual(len(rv["evidence"][0]["task_quotes"]), 2)

    def test_duplicate_cannot_hide_out_of_task_quote(self):
        rv = self.run_review("invalid-duplicate")
        self.assertEqual((rv["verdict"], rv["tests_run"]), ("unknown", 1), rv)
        self.assertEqual(len(rv["manifest_rejections"]), 1)
        self.assertEqual(rv["manifest_rejections"][0]["reason"], "non-task quote")

    def test_confirmation_can_use_second_valid_quote_of_same_file(self):
        rv = self.run_review("duplicate", x=4, env={"FAKE_CONFIRM_QUOTE": "x to 2 in a.py"})
        self.assertEqual((rv["verdict"], rv["tests_run"]), ("issues", 1), rv)

    def test_markdown_whitespace_quote_is_executed_and_confirmed(self):
        rv = self.run_review(task="change `x` to\n**2** in a.py", x=4,
                             env={"FAKE_TEST_QUOTE": "x to 2", "FAKE_CONFIRM_QUOTE": "`x` to\n2"})
        self.assertEqual((rv["verdict"], rv["tests_run"], rv["tests_failed"]), ("issues", 1, 1), rv)

    def test_paraphrase_and_punctuation_only_quotes_are_rejected(self):
        for quote in ("x becomes 2", "...", "x to 3"):
            with self.subTest(quote=quote):
                rv = self.run_review(env={"FAKE_TEST_QUOTE": quote})
                self.assertEqual((rv["verdict"], rv["tests_run"]), ("unknown", 0), rv)

    def test_invalid_root_manifest_does_not_fall_back(self):
        rv = self.run_review("malformed-root")
        self.assertEqual((rv["verdict"], rv["tests_run"]), ("unknown", 0), rv)
        self.assertIn("JSONDecodeError", rv["manifest_error"])
        self.assertEqual(Path(rv["manifest_path"]).read_text(encoding="utf-8"), "invalid JSON")

    def test_missing_manifest_has_separate_diagnostic(self):
        rv = self.run_review("no-tests")
        self.assertIn("FileNotFoundError", rv["manifest_error"])

    def test_finish_assigns_execution_to_controller_for_both_calls(self):
        rv = self.run_review(x=4)
        calls = [c for c in self.calls() if "[ccx test review]" in c["prompt"]]
        self.assertEqual(len(calls), 2, rv)
        for call in calls:
            finish = call["prompt"].split("## Finish", 1)[1]
            self.assertIn("Do not run tests or builds", finish)
            self.assertNotIn("Before you finish, check your own work", finish)

    def test_confirmation_budget_error_is_retained_without_blocking(self):
        rv = self.run_review(x=4, env={"FAKE_TEST_CONFIRM_BUDGET": "1"})
        self.assertEqual(rv["verdict"], "unknown", rv)
        self.assertIn("maximum budget", rv["confirmation_error"])
        self.assertEqual(len(rv["reviewer_calls"]), 2)
        self.assertFalse(rv["reviewer_calls"][-1]["ok"])
        self.assertAlmostEqual(rv["native_usd"], 0.0633)

    def test_non_object_confirmations_are_unknown(self):
        rv = self.run_review(x=4, env={"FAKE_TEST_CONFIRM_INVALID": "1"})
        self.assertEqual(rv["verdict"], "unknown", rv)
        self.assertIn("assertion failures not confirmed as correct, in-scope tests", rv["unknown_reasons"])

    def test_empty_overrides_keep_existing_candidate(self):
        rv = self.run_review(settings='tests_model = ""\ntests_effort = ""\n')
        self.assertEqual(rv["by"], "claude:haiku:low", rv)

    def test_model_effort_config_set_and_both_requests(self):
        for key, value in (("tests_model", "sonnet"), ("tests_effort", "medium")):
            r = self.ccx("config", "set", "review." + key, value)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        # The helper writes only hub tiers; config set is read back independently.
        rv = self.run_review(x=4)
        self.assertEqual(rv["by"], "claude:sonnet:medium", rv)
        for call in [c for c in self.calls() if "[ccx test review]" in c["prompt"]]:
            self.assertEqual(call["argv"][call["argv"].index("--model") + 1], "sonnet")
            self.assertEqual(call["argv"][call["argv"].index("--effort") + 1], "medium")

    def test_replay_forwards_override_cap_and_read_permissions_to_fake_cli(self):
        archive = io.BytesIO()
        with tarfile.open(fileobj=archive, mode="w") as tar:
            data = b"x = 1\n"
            entry = tarfile.TarInfo("a.py")
            entry.size = len(data)
            tar.addfile(entry, io.BytesIO(data))
        case = {"index": 0, "implementer": "codex", "task_text": "change x to 2 in a.py",
                "stubs": archive.getvalue(), "solution": ["a.py"], "diff": ""}
        with mock.patch.object(preflight, "prepare", return_value=self.env):
            rv = replay.replay(case, self.hub / "replay", 0.4, reviewer_model="sonnet", reviewer_effort="medium")
        self.assertEqual(rv["by"], "claude:sonnet:medium", rv)
        calls = [c for c in self.calls() if "[ccx test review]" in c["prompt"]]
        self.assertEqual(len(calls), 2)
        for call in calls:
            args = call["argv"]
            self.assertEqual(args[args.index("--max-budget-usd") + 1], "0.2")
            self.assertEqual(args[args.index("--model") + 1], "sonnet")
        args = calls[-1]["argv"]
        self.assertEqual(args[args.index("--permission-mode") + 1], "dontAsk")
        self.assertEqual(args[args.index("--allowed-tools") + 1], "Read Grep Glob")
        job = json.loads((self.hub / "replay/p2-0/job.json").read_text(encoding="utf-8"))
        self.assertEqual((job["reviewer_model"], job["reviewer_effort"], job["unit_cap"]), ("sonnet", "medium", 0.4))


@pytest.mark.parametrize("values,model,cap", [(None, "", 0.1), (["0.2"], "", 0.2),
    (["0.2", "sonnet=0.4", "haiku=0.1"], "sonnet", 0.4), (["sonnet=0.4"], "haiku", 0.1)])
def test_model_unit_caps(values, model, cap):
    assert replay.unit_cap(values, model) == cap


@pytest.mark.parametrize("values,model", [(["nan"], ""), (["0"], ""), (["-1"], ""),
    (["sonnet=0.4"], ""), (["=0.4"], "sonnet"), (["sonnet=inf"], "sonnet")])
def test_invalid_unit_caps(values, model):
    with pytest.raises(ValueError):
        replay.unit_cap(values, model)


def test_replay_flags_from_outside_repo_dry_run(tmp_path):
    r = subprocess.run([sys.executable, str(EVAL / "p2_review_replay.py"), "--dry-run", "--results",
        str(tmp_path / "absent.jsonl"), "--artifacts", str(tmp_path / "absent"), "--reviewer-model", "sonnet",
        "--reviewer-effort", "medium", "--unit-cap", "0.1", "--unit-cap", "sonnet=0.4"],
        cwd=tmp_path, capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    assert "reviewer model=sonnet effort=medium; unit-cap=$0.400" in r.stdout


def test_replay_records_overrides_and_reserves_selected_model_cap(tmp_path, monkeypatch):
    cases = [{"index": i, "task": str(i), "hidden_ok": True, "implementer": "codex", "source_row": {},
              "missing": [], "task_text": "x to 2"} for i in range(29)]
    monkeypatch.setattr(replay, "audit", lambda *args: (cases, []))
    monkeypatch.setattr(replay.subprocess, "check_output", lambda *args, **kw: "pin\n")
    monkeypatch.setattr(replay.subprocess, "run", lambda *args, **kw: subprocess.CompletedProcess([], 0))
    calls = []
    def fake_replay(case, base, cap, **kw):
        calls.append((cap, kw))
        return {"verdict": "pass", "unknown_reasons": [], "usd": 0.01}
    monkeypatch.setattr(replay, "replay", fake_replay)
    out = tmp_path / "out.jsonl"
    assert replay.main(["--run", "--pin-commit", "pin", "--budget", "0.4", "--reviewer-model", "sonnet",
        "--reviewer-effort", "medium", "--unit-cap", "0.1", "--unit-cap", "sonnet=0.4", "--out", str(out),
        "--work", str(tmp_path / "work")]) == 0
    rows = replay.read_rows(out)
    assert calls == [(0.4, {"reviewer_model": "sonnet", "reviewer_effort": "medium"})]
    assert len(rows) == 29
    assert all((r["reviewer_model"], r["reviewer_effort"], r["unit_cap"]) == ("sonnet", "medium", 0.4) for r in rows)
    assert all(r["reserved_usd"] == 0.4 for r in rows)
