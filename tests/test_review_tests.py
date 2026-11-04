"""Independent test review: actual subprocess tests, fake model CLIs only."""
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
from unittest import mock

from test_ccx import Env, ROOT
from ccx import review, review_tests
from ccx.config import Paths, load_config
from ccx.delegate import Request

EVAL = ROOT / "scripts" / "eval"
sys.path.insert(0, str(EVAL))
import p2_review_replay as replay  # noqa: E402
import r5  # noqa: E402


class TestTestReview(Env):
    def setUp(self):
        super().setUp()
        subprocess.run(["git", "init", "-q"], cwd=self.work, check=True)
        (self.work / "a.py").write_text("x = 1\n", encoding="utf-8")
        (self.work / "test_builder.py").write_text("raise RuntimeError('builder yardstick')", encoding="utf-8")
        self.git("add", "a.py", "test_builder.py")
        self.git("commit", "-qm", "initial")
        self.tiers = Paths(self.hub).user_tiers
        self.tiers.parent.mkdir(parents=True, exist_ok=True)

    def git(self, *args):
        return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
                              cwd=self.work, check=True, capture_output=True)

    def go(self, scenario="pass", x=2, mode="tests"):
        self.tiers.write_text(f'[review]\nmode = "{mode}"\nfix_rounds = 0\n', encoding="utf-8")
        r = self.ccx("run", "--to", "codex", "--model", "gpt-6-luna", "--effort", "low", "--mode", "write",
                     "--review", "on", "--no-fallback", "--no-escalate", "change x to 2 in a.py",
                     env={"FAKE_WRITE": f"{self.work / 'a.py'}=x = {x}\n", "FAKE_TEST_REVIEW": scenario})
        self.assertIn(r.returncode, (0, 2), r.stderr + r.stdout)
        out = json.loads(r.stdout)
        rec = json.loads((Paths(self.hub).runs / out["run_id"] / "run.json").read_text(encoding="utf-8"))
        return out, rec, r.returncode

    def test_pass_executes_independent_tests_and_no_builder_tests(self):
        (self.work / "hidden-pytest.txt").write_text("hidden answers", encoding="utf-8")
        # Hidden material belongs in .ccx; arbitrary untracked non-source data is not copied either.
        self.git("add", "hidden-pytest.txt")
        out, rec, code = self.go()
        self.assertEqual((code, out["review"]["verdict"]), (0, "pass"), out)
        self.assertEqual(rec["review_mode"], "on")  # existing trigger field keeps its old meaning
        self.assertEqual(rec["review"]["review_mode"], "tests")
        rv = rec["review"]
        self.assertEqual((rv["tests_written"], rv["tests_run"], rv["tests_failed"]), (1, 1, 0))
        self.assertTrue(rv["independent"])
        self.assertIn("OK", Path(rv["evidence"][0]["output"]).read_text(encoding="utf-8"))
        self.assertFalse((self.work / "checks").exists())
        ledger = Paths(self.hub).ledger.read_text(encoding="utf-8")
        self.assertNotIn("self.assertEqual", ledger)

    def test_confirmed_failure_blocks_with_file_and_real_output(self):
        out, rec, code = self.go("fail", x=4)
        self.assertEqual((code, rec["kind"], out["review"]["verdict"]), (2, "review_failed", "issues"), out)
        self.assertEqual(rec["review"]["tests_failed"], 1)
        ev = rec["review"]["evidence"][0]
        self.assertTrue(Path(ev["file"]).is_file())
        self.assertIn("4 != 2", Path(ev["output"]).read_text(encoding="utf-8"))
        self.assertIn(ev["output"], out["review"]["issues"][0])

    def test_environment_error_is_unknown_without_blocking(self):
        out, rec, code = self.go("error")
        self.assertEqual((code, out["review"]["verdict"]), (0, "unknown"), out)
        self.assertEqual(rec["review"]["tests_failed"], 0)
        self.assertIn("Unknown", out["needs_lead"])

    def test_implementation_crash_is_confirmed_and_blocked(self):
        self.tiers.write_text('[review]\nmode = "tests"\nfix_rounds = 0\n', encoding="utf-8")
        source = "x = 2\ndef value():\n    raise RuntimeError('implementation crash')\n"
        r = self.ccx("run", "--to", "codex", "--model", "gpt-6-luna", "--effort", "low", "--mode", "write",
                     "--review", "on", "--no-fallback", "--no-escalate", "change x to 2 in a.py; value() must return x",
                     env={"FAKE_WRITE": f"{self.work / 'a.py'}={source}", "FAKE_TEST_REVIEW": "crash"})
        self.assertEqual(r.returncode, 2, r.stderr + r.stdout)
        out = json.loads(r.stdout)
        self.assertEqual(out["review"]["verdict"], "issues", out)
        self.assertEqual(out["review"]["tests_failed"], 1)
        ev = out["review"]["evidence"][0]
        self.assertIn("RuntimeError: implementation crash", Path(ev["output"]).read_text(encoding="utf-8"))
        confirmations = [c for c in self.calls() if "Actual test execution" in c["prompt"]]
        self.assertEqual(len(confirmations), 1)

    def test_wrong_test_does_not_block(self):
        out, rec, code = self.go("wrong-test")
        self.assertEqual((code, out["review"]["verdict"]), (0, "unknown"), out)
        self.assertEqual(rec["review"]["tests_failed"], 1)

    def test_unwritten_tests_are_unknown(self):
        out, rec, code = self.go("no-tests")
        self.assertEqual(out["review"]["verdict"], "unknown", out)
        self.assertEqual(rec["review"]["tests_run"], 0)

    def test_out_of_scope_tests_are_not_executed_or_blocking(self):
        out, rec, code = self.go("out-of-scope")
        self.assertEqual((code, out["review"]["verdict"]), (0, "unknown"), out)
        self.assertEqual(rec["review"]["tests_run"], 0)

    def test_read_mode_keeps_exact_old_brief_and_fields(self):
        out, rec, code = self.go(mode="read")
        self.assertEqual(out["review"]["verdict"], "pass")
        self.assertEqual(rec["review_mode"], "on")
        self.assertNotIn("review_test_mode", rec)
        self.assertNotIn("tests_run", rec["review"])
        prompts = [c["prompt"] for c in self.calls() if c["agent"] == "claude" and "[ccx review" in c["prompt"]]
        self.assertEqual(len(prompts), 1)
        self.assertIn("You cannot run commands", prompts[0])
        # The review brief itself remains exactly the existing generator's bytes.
        req = Request(to="codex", brief="change x to 2 in a.py", review="on", cwd=self.work)
        cfg = load_config(Paths(self.hub))
        captured = []
        def fake_run(req, p):
            captured.append(req.brief)
            return {"ok": True, "run_id": "fake", "result": {"summary": "REVIEW: pass"}}
        record = {"run_id": "r", "result": {"summary": "done"}}
        with mock.patch("ccx.workspace.run_snapshot", return_value={"base": "HEAD"}), \
                mock.patch.object(review, "changes", return_value=(["a.py"], "+x = 2\n")), \
                mock.patch.object(review, "reviewers", return_value=[("claude", "haiku", "low")]), \
                mock.patch("ccx.delegate.run", side_effect=fake_run):
            review.review_run(req, Paths(self.hub), cfg, record, self.work, self.hub)
        expected = review.brief("r", req.brief, "done", "+x = 2\n", cfg["review"]["max_diff_chars"])
        self.assertEqual(captured, [expected])

    def test_same_vendor_explicitly_not_independent(self):
        rec = {"run_id": "r"}
        review_tests.run_review(Request(to="codex", brief="x to 2"), Paths(self.hub), {}, rec, self.work,
                                self.hub, [("codex", "gpt-6-luna", "low")], "asked",
                                run_agent=mock.Mock(side_effect=AssertionError("must not call same vendor")))
        self.assertFalse(rec["review"]["independent"])
        self.assertEqual(rec["review"]["verdict"], "unknown")

    def test_original_task_preferred_over_brief(self):
        self.assertEqual(review_tests.task_text(Paths(self.hub), Request(to="codex", brief="rewritten"),
                                               {"user_task": "original exact task"}), "original exact task")

    def test_cli_original_task_file_reaches_review_and_resume(self):
        self.tiers.write_text('[review]\nmode = "tests"\nfix_rounds = 0\n', encoding="utf-8")
        original = "Original exact request: change x to 2 in a.py.\n"
        raw = self.hub / "original-task.txt"
        raw.write_text(original, encoding="utf-8", newline="")
        r = self.ccx("run", "--to", "codex", "--model", "gpt-6-luna", "--effort", "low", "--mode", "write",
                     "--review", "on", "--no-fallback", "--no-escalate", "--user-task-file", str(raw),
                     "worker rewritten brief", env={"FAKE_WRITE": f"{self.work / 'a.py'}=x = 2\n"})
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        out = json.loads(r.stdout)
        runs = Paths(self.hub).runs
        rec = json.loads((runs / out["run_id"] / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(rec["user_task"], original)
        self.assertEqual(out["review"]["verdict"], "pass", out)
        reviews = [c["prompt"] for c in self.calls() if "[ccx test review]" in c["prompt"]]
        self.assertIn(original, reviews[0])
        self.assertNotIn("worker rewritten brief", reviews[0])
        r = self.ccx("resume", out["run_id"], "finish remaining changes", "--review", "on", "--no-escalate",
                     env={"FAKE_WRITE_RESUMED": f"{self.work / 'a.py'}=x = 3\n"})
        self.assertIn(r.returncode, (0, 2), r.stderr + r.stdout)
        resumed = json.loads(r.stdout)
        rec = json.loads((runs / resumed["run_id"] / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(rec["user_task"], original)

    def test_cli_captures_original_before_role_template(self):
        self.tiers.write_text('[review]\nmode = "tests"\nfix_rounds = 0\n', encoding="utf-8")
        config = self.work / ".ccx"
        (config / "briefs" / "templates").mkdir(parents=True)
        (config / "roles.toml").write_text('[roles]\nbuild = "codex:gpt-6-luna:low"\n', encoding="utf-8")
        (config / "briefs" / "templates" / "build.md").write_text("role wrapper\n{task}\n", encoding="utf-8")
        original = "change x to 2 in a.py"
        r = self.ccx("run", "--role", "build", "--mode", "write", "--review", "on", "--no-escalate",
                     "--no-fallback", original, env={"FAKE_WRITE": f"{self.work / 'a.py'}=x = 2\n"})
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        out = json.loads(r.stdout)
        run_dir = Paths(self.hub).runs / out["run_id"]
        self.assertIn("role wrapper", (run_dir / "brief.md").read_text(encoding="utf-8"))
        self.assertEqual(json.loads((run_dir / "run.json").read_text(encoding="utf-8"))["user_task"], original)
        prompts = [c["prompt"] for c in self.calls() if "[ccx test review]" in c["prompt"]]
        self.assertIn(original, prompts[0])
        self.assertNotIn("role wrapper", prompts[0])

    def test_replay_original_task_reaches_actual_reviewer(self):
        self.tiers.write_text('[review]\nmode = "tests"\n', encoding="utf-8")
        raw = "Replay original: change x to 2 in a.py.\n"
        job = self.hub / "original-replay.json"
        job.write_text(json.dumps({"key": "raw-replay", "hub": str(self.hub), "tree": str(self.work),
                                   "evidence": str(self.hub / "evidence"), "implementer": "codex",
                                   "task_text": "rewritten worker brief", "user_task": raw}), encoding="utf-8")
        r = subprocess.run([sys.executable, str(EVAL / "p2_review_replay.py"), "--one", str(job)], cwd=self.work,
                           env=self.env, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 0, r.stderr)
        result = json.loads(r.stdout)
        self.assertEqual(result["tests_run"], 1, result)
        prompts = [c["prompt"] for c in self.calls() if "[ccx test review]" in c["prompt"]]
        self.assertIn(raw, prompts[0])
        self.assertNotIn("rewritten worker brief", prompts[0])

    def test_replay_driver_forwards_original_through_job(self):
        archive = io.BytesIO()
        with tarfile.open(fileobj=archive, mode="w") as tar:
            data = b"x = 1\n"
            entry = tarfile.TarInfo("a.py")
            entry.size = len(data)
            tar.addfile(entry, io.BytesIO(data))
        raw = "Saved receipt original: change x to 2 in a.py.\n"
        case = {"index": 0, "implementer": "codex", "task_text": "worker brief without task words", "user_task": raw,
                "stubs": archive.getvalue(), "solution": ["a.py"], "diff": ""}
        with mock.patch.object(r5.PF, "prepare", return_value=self.env):
            result = replay.replay(case, self.hub / "replay", 0.10)
        self.assertEqual(result["tests_run"], 1, result)
        job = json.loads((self.hub / "replay" / "p2-0" / "job.json").read_text(encoding="utf-8"))
        self.assertEqual(job["user_task"], raw)
        prompts = [c["prompt"] for c in self.calls() if "[ccx test review]" in c["prompt"]]
        self.assertIn(raw, prompts[0])
        self.assertNotIn("worker brief without task words", prompts[0])

    def test_r5_opt_in_sets_and_asserts_effective_mode(self):
        self.tiers.write_text('[review]\nmode = "on"\n[defaults]\nnamecheck = "warn"\n', encoding="utf-8")
        self.assertEqual(r5.set_test_review(self.hub), "tests")
        self.assertIn("ccx2rt", r5.OPT_IN_ARMS)
        self.assertEqual(r5.lead_how("ccx2rt", "label"), r5.lead_how("ccx2", "label"))

    def test_replay_worker_entrypoint_uses_fake_cli_native_caps(self):
        self.tiers.write_text('[review]\nmode = "tests"\n[permissions.claude]\n'
                              'write = ["--permission-mode", "acceptEdits", "--max-budget-usd", "0.05"]\n'
                              'read = ["--permission-mode", "plan", "--max-budget-usd", "0.05"]\n',
                              encoding="utf-8")
        job = self.hub / "job.json"
        job.write_text(json.dumps({"key": "replay-test", "hub": str(self.hub), "tree": str(self.work),
                                   "evidence": str(self.hub / "evidence"), "implementer": "codex",
                                   "task_text": "change x to 2 in a.py"}), encoding="utf-8")
        r = subprocess.run([sys.executable, str(EVAL / "p2_review_replay.py"), "--one", str(job)], cwd=self.work,
                           env=self.env, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 0, r.stderr)
        result = json.loads(r.stdout)
        self.assertEqual(result["verdict"], "issues", result)
        calls = [c for c in self.calls() if "[ccx test review]" in c["prompt"]]
        self.assertEqual(len(calls), 2)
        for call in calls:
            self.assertIn("--max-budget-usd", call["argv"])
            self.assertEqual(call["argv"][call["argv"].index("--max-budget-usd") + 1], "0.05")


def test_replay_scores_keep_unknown_denominators():
    s = replay.score([{"hidden_ok": False, "verdict": "issues"}, {"hidden_ok": False, "verdict": "unknown"},
                      {"hidden_ok": True, "verdict": "pass"}, {"hidden_ok": True, "verdict": "unknown"}])
    assert s["catch"] == {"numerator": 1, "denominator": 2, "rate": 0.5}
    assert s["false_block"]["denominator"] == 2
    assert s["worst_false_block"]["numerator"] == 1
    assert s["unknown"] == 2
    assert replay.score([])["catch"]["rate"] is None


def test_replay_dry_run_from_outside_repo_reports_missing_without_cli(tmp_path):
    out = tmp_path / "output.jsonl"
    r = subprocess.run([sys.executable, str(EVAL / "p2_review_replay.py"), "--dry-run", "--results",
                        str(tmp_path / "missing.jsonl"), "--artifacts", str(tmp_path / "missing-artifacts"),
                        "--out", str(out)], cwd=tmp_path, capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    assert "units=0" in r.stdout
    assert "Unknown" in r.stdout
    assert not out.exists()


def test_replay_rebuild_applies_only_solution_hunks(tmp_path):
    tree = tmp_path / "tree"
    tree.mkdir()
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w") as tar:
        data = b"x = 1\n"
        entry = tarfile.TarInfo("a.py")
        entry.size = len(data)
        tar.addfile(entry, io.BytesIO(data))
    patch = ("diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-x = 1\n+x = 4\n"
             "diff --git a/test_builder.py b/test_builder.py\nnew file mode 100644\n--- /dev/null\n"
             "+++ b/test_builder.py\n@@ -0,0 +1 @@\n+raise RuntimeError('hidden_or_builder_test')\n")
    replay.rebuild({"stubs": archive.getvalue(), "solution": ["a.py"], "diff": patch}, tree)
    assert (tree / "a.py").read_text(encoding="utf-8") == "x = 4\n"
    assert not (tree / "test_builder.py").exists()
    review_tests.copy_source(tree, tmp_path / "reviewer")
    assert sorted(f.name for f in (tmp_path / "reviewer").rglob("*") if f.is_file()) == ["a.py"]


def test_replay_audit_preserves_missing_membership_and_vendor(tmp_path):
    results = tmp_path / "results.jsonl"
    artifacts = tmp_path / "artifacts"
    unit = artifacts / "unit"
    unit.mkdir(parents=True)
    (unit / "final.diff").write_text("patch", encoding="utf-8")
    (unit / "hidden-pytest.txt").write_text("secret hidden assertion", encoding="utf-8")
    rows = [{"task": "one", "ok": False, "artifacts": {"dir": "unit"}},
            {"task": "two", "ok": True, "kind": "review_failed"}]
    results.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    cases, problems = replay.audit(results, artifacts, None)
    assert len(cases) == 1
    assert cases[0]["hidden_ok"] is False
    assert cases[0]["implementer"] is None
    assert any("receipt kind" in p for p in cases[0]["missing"])
    assert any("task instructions" in p for p in cases[0]["missing"])
    assert "secret hidden assertion" not in json.dumps(cases)
    assert problems


def test_replay_worker_reads_implementer_not_reviewer():
    row = {"switches_applied": {"runs": [{"review": False, "agents": ["codex"]},
                                          {"review": True, "agents": ["claude"]}]}}
    assert replay.worker(row) == "codex"
    assert replay.worker({"ccx_agents": ["claude", "codex"]}) is None


def test_pg3b_receipt_inference_requires_one_terminal_failed_review():
    rows = [{"task": task, "tag": "pg3b", "switches_applied": {"runs": [
        {"run": "builder-1", "review": False}, {"run": "builder-2", "review": False}]}, "must_categories": []}
            for task in r5.tasks_polyglot.IDS]
    bowling = next(i for i, row in enumerate(rows) if row["task"] == "pg-bowling")
    rows[bowling]["must_categories"] = [{"run_id": "builder-2", "verdict": "issues", "fixed_by": None}]
    kinds, excluded = replay.pg3b_receipts(rows)
    assert excluded == "pg-bowling"
    assert kinds[bowling] == "review_failed"
    assert sum(kind == "ok_self_checked" for kind in kinds.values()) == 29
    # A historical issues review that was repaired is not a final failed receipt.
    rows[0]["must_categories"] = [{"run_id": "builder-1", "verdict": "issues", "fixed_by": "builder-2"}]
    assert replay.pg3b_receipts(rows)[1] == "pg-bowling"
    rows[0]["must_categories"] = [{"run_id": "builder-2", "verdict": "issues", "fixed_by": None}]
    assert replay.pg3b_receipts(rows) == ({}, None)


def test_replay_ext_cache_reuses_existing_clone_without_fetch(tmp_path):
    cache = tmp_path / "cache"
    clone = cache / "polyglot.git"
    clone.mkdir(parents=True)
    (clone / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    assert replay.exercise_source(None, cache, tmp_path) == clone


def test_replay_ext_cache_accepts_polyglot_benchmark_clone_name(tmp_path):
    cache = tmp_path / "cache"
    clone = cache / "polyglot-benchmark.git"
    clone.mkdir(parents=True)
    (clone / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    assert replay.exercise_source(None, cache, tmp_path) == clone


def test_replay_solution_patch_filters_binary_cache_blocks(tmp_path):
    solution = "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-x = 1\n+x = 4\n"
    binary = ("diff --git a/__pycache__/a.cpython-311.pyc b/__pycache__/a.cpython-311.pyc\n"
              "GIT binary patch\nliteral 123\nnot a valid binary patch\n")
    assert replay.solution_diff(binary + solution, ["a.py"]) == solution
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w") as tar:
        data = b"x = 1\n"
        entry = tarfile.TarInfo("a.py")
        entry.size = len(data)
        tar.addfile(entry, io.BytesIO(data))
    replay.rebuild({"stubs": archive.getvalue(), "solution": ["a.py"], "diff": binary + solution}, tmp_path)
    assert (tmp_path / "a.py").read_text(encoding="utf-8") == "x = 4\n"
    assert not (tmp_path / "__pycache__").exists()


def test_replay_budget_retains_all_rows_without_launching(tmp_path, monkeypatch):
    cases = [{"index": i, "task": str(i), "hidden_ok": i % 2 == 0, "implementer": "codex",
              "source_row": {"task": str(i), "raw": "preserved"}, "missing": [], "task_text": "x to 2"}
             for i in range(29)]
    monkeypatch.setattr(replay, "audit", lambda *a: (cases, []))
    monkeypatch.setattr(replay.subprocess, "check_output", lambda *a, **kw: "pinned\n")
    monkeypatch.setattr(replay.subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess([], 0))
    calls = []
    def fake_replay(case, base, cap):
        calls.append(case["index"])
        return {"verdict": "pass", "usd": 0.01, "unknown_reasons": []}
    monkeypatch.setattr(replay, "replay", fake_replay)
    output = tmp_path / "replay.jsonl"
    assert replay.main(["--run", "--pin-commit", "pinned", "--budget", "0.1", "--unit-cap", "0.1",
                        "--work", str(tmp_path / "work"), "--out", str(output)]) == 0
    rows = replay.read_rows(output)
    assert len(rows) == 29
    assert calls == [0]
    assert sum(r["verdict"] == "unknown" for r in rows) == 28
    assert all(r["source_row"]["raw"] == "preserved" for r in rows)
    assert max(r["reserved_usd"] for r in rows) <= 0.1


def test_execute_invalid_test_file_is_unknown(tmp_path):
    tree, evidence = tmp_path / "tree", tmp_path / "evidence"
    (tree / "checks").mkdir(parents=True)
    (tree / "manifest.json").write_text(json.dumps({"cases": [{"file": "test_bad.py", "task_quote": "x to 2"}]}),
                                         encoding="utf-8")
    (tree / "checks" / "test_bad.py").write_text("not valid python !!", encoding="utf-8")
    result = review_tests.execute(tree, evidence, "x to 2")
    assert result["verdict"] == "unknown"
    assert result["tests_failed"] == 0
    assert "SyntaxError" in (evidence / "test_bad.py.txt").read_text(encoding="utf-8")


def test_execute_timeout_counts_are_unknown_not_zero(tmp_path):
    tree, evidence = tmp_path / "tree", tmp_path / "evidence"
    (tree / "checks").mkdir(parents=True)
    (tree / "checks" / "test_slow.py").write_text("import unittest\n", encoding="utf-8")
    (tree / "manifest.json").write_text(json.dumps({"cases": [{"file": "test_slow.py", "task_quote": "x to 2"}]}),
                                         encoding="utf-8")
    with mock.patch.object(review_tests.subprocess, "run", side_effect=subprocess.TimeoutExpired("test", 60)):
        result = review_tests.execute(tree, evidence, "x to 2")
    assert result["verdict"] == "unknown"
    assert result["tests_run"] is None
    assert result["tests_failed"] is None
    assert "no tests executed" not in result["unknown_reasons"]


def test_generated_checks_do_not_inherit_parent_credentials(tmp_path):
    tree, evidence = tmp_path / "tree", tmp_path / "evidence"
    (tree / "checks").mkdir(parents=True)
    (tree / "manifest.json").write_text(json.dumps({"cases": [{"file": "test_env.py", "task_quote": "run safely"}]}),
                                         encoding="utf-8")
    (tree / "checks" / "test_env.py").write_text(
        "import os, unittest\nclass Credentials(unittest.TestCase):\n"
        "    def test_no_credentials(self):\n"
        "        for key in ('EXAMPLE_API_KEY', 'ARBITRARY_SECRET', 'CLAUDE_CODE_OAUTH_TOKEN', 'PYTHONPATH'):\n"
        "            self.assertNotIn(key, os.environ)\n"
        "        self.assertEqual(os.environ['PYTHONDONTWRITEBYTECODE'], '1')\n", encoding="utf-8")
    with mock.patch.dict(review_tests.os.environ, {"EXAMPLE_API_KEY": "fake-only-key", "ARBITRARY_SECRET": "fake-secret",
                                                   "CLAUDE_CODE_OAUTH_TOKEN": "fake-only-token", "PYTHONPATH": "fake-path"}):
        result = review_tests.execute(tree, evidence, "run safely")
    assert result["tests_run"] == 1, result
    assert result["tests_failed"] == 0, result
    assert not result["unknown_reasons"], result
    assert "OK" in (evidence / "test_env.py.txt").read_text(encoding="utf-8")
