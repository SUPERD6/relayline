"""Baseline-aware checks: deterministic fake CLIs and disposable local Git repositories only."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from test_adapters import AdapterEnv
from ccx import check_baseline as baseline
from ccx.config import Paths, load_config
from ccx.workspace import run_check


def git(root, *args):
    return subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", *args],
                          cwd=root, capture_output=True, text=True, encoding="utf-8", check=True).stdout.strip()


def repository(root):
    root.mkdir(parents=True, exist_ok=True)
    git(root, "init", "-q")
    git(root, "config", "core.autocrlf", "false")
    (root / ".gitignore").write_text(".ccx/\n__pycache__/\n", encoding="utf-8")
    (root / "state.txt").write_text("base", encoding="utf-8")
    (root / "check_run.py").write_text(
        "import pathlib, sys\n"
        "state = pathlib.Path('state.txt').read_text()\n"
        "if 'passbase' in sys.argv and state == 'base':\n"
        "    print('1 passed in 0.01s'); sys.exit(0)\n"
        "if 'opaque' in sys.argv:\n"
        "    print('opaque failure'); sys.exit(1)\n"
        "cases = ['tests/test_old.py::test_old']\n"
        "if state == 'new': cases += ['tests/test_new.py::test_new']\n"
        "for case in cases: print('FAILED ' + case + ' - AssertionError')\n"
        "print(str(len(cases)) + ' failed in 0.01s')\n"
        "print('diagnostic stderr', file=sys.stderr)\n"
        "sys.exit(1)\n", encoding="utf-8", newline="")
    git(root, "add", ".gitignore", "state.txt", "check_run.py")
    git(root, "commit", "-qm", "fixture")
    return root


@pytest.mark.parametrize("output,code,expected", [
    ("FAILED tests/a.py::test_a - assert\n1 failed in 0.1s", 1, ["tests/a.py::test_a"]),
    ("FAILED tests\\a.py::test_a - assert\n1 failed in 0.1s", 1, ["tests/a.py::test_a"]),
    ("FAILED tests/a.py::test_a[param with spaces] - assert\n1 failed, 2 passed in 0.1s", 1,
     ["tests/a.py::test_a[param with spaces]"]),
    ("FAILED tests/a.py::test_a - assert\n2 failed in 0.1s", 1, None),
    ("FAILED tests/a.py::test_a - assert", 1, None),
    ("opaque failure", 1, None),
    ("FAILED tests/a.py::test_a - assert\n1 failed in 0.1s", -1, None),
    ("1 error in 0.1s", 2, None),
    ("", 0, []),
])
def test_complete_failures_only(output, code, expected):
    assert baseline.failed_cases(output, code) == expected


def test_default_off():
    assert load_config(Paths(Path("unused-hub")))["check"]["baseline"] == "off"


@pytest.mark.parametrize("node", ["test_x[a - b]", "test_x[a - c]", "test_x[nested[a - b]]"])
def test_parameter_separator_is_part_of_case_name(node):
    case = "tests/a.py::" + node
    assert baseline.failed_cases(f"FAILED {case} - AssertionError\n1 failed in 0.1s", 1) == [case]


@pytest.mark.parametrize("node", ["test_x[a - b", "test_x[a - b]]", "test_x[a[b]"])
def test_unbalanced_parameter_is_unknown(node):
    assert baseline.failed_cases(f"FAILED tests/a.py::{node} - assert\n1 failed in 0.1s", 1) is None


def test_parameterized_new_failure_is_not_baseline_only(tmp_path, monkeypatch):
    before = baseline.failed_cases("FAILED tests/a.py::test_x[a - b] - assert\n1 failed", 1)
    after = baseline.failed_cases("FAILED tests/a.py::test_x[a - c] - assert\n1 failed", 1)
    monkeypatch.setattr(baseline, "run_baseline", lambda *a: {
        "status": "Fail", "seconds": 0, "check": {"failed_cases": before}})
    checks = baseline.Checks({"defaults": {}, "check": {"baseline": "on_fail"}}, tmp_path, tmp_path, {},
                             lambda *a, **k: {"passed": False, "failed_cases": after}, True, start={})
    assert checks("check")["baseline_comparison"] == "new_failures"


def test_baseline_removes_source_pythonpath_and_records_actual_imports(tmp_path, monkeypatch):
    root = repository(tmp_path / "repo")
    external = tmp_path / "external"
    external.mkdir()
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join([str(root), str(root / "src"), str(external)]))
    logs = tmp_path / "logs"
    logs.mkdir()
    def inspect(cmd, cwd, timeout, **kwargs):
        entries = kwargs["env"]["PYTHONPATH"].split(os.pathsep)
        assert str(root) not in entries and str(root / "src") not in entries
        assert str(external) in entries
        return run_check(cmd, cwd, timeout, **kwargs)
    out = baseline.run_baseline(baseline.capture(root), f'"{sys.executable}" check_run.py', logs, 30, inspect)
    assert out["status"] == "Fail"
    assert any(p.endswith("check_run.py") for p in out["import_origins"])
    assert not any(Path(p).is_relative_to(root) for p in out["import_origins"])


@pytest.mark.parametrize("source_entry", [False, True])
def test_entrypoint_origin_survives_main_file_cleanup(tmp_path, monkeypatch, source_entry):
    root = repository(tmp_path / "repo")
    script = root / "check_run.py"
    # Simulate CPython 3.13 removing this attribute before atexit on older Pythons.
    script.write_text("del __file__\n" + script.read_text(encoding="utf-8"), encoding="utf-8", newline="")
    git(root, "add", "check_run.py")
    git(root, "commit", "-qm", "main cleanup fixture")
    argument = "check_run.py"
    if source_entry:
        monkeypatch.setenv("BASELINE_ENTRY", str(script))
        argument = '"%BASELINE_ENTRY%"' if os.name == "nt" else '"$BASELINE_ENTRY"'
    out = baseline.run_baseline(baseline.capture(root), f'"{sys.executable}" {argument}',
                                tmp_path, 30, run_check)
    assert any(p.endswith("check_run.py") for p in out["import_origins"])
    if source_entry:
        assert out["status"] == "Unknown"
        assert str(script.resolve()) in out["import_origins"]
    else:
        assert out["status"] == "Fail"
        assert not any(Path(p).is_relative_to(root) for p in out["import_origins"])


def test_editable_import_from_source_cannot_mask_new_failure(tmp_path, monkeypatch):
    root = repository(tmp_path / "repo")
    (root / "editable_target.py").write_text("value = 1\n", encoding="utf-8")
    # Emulate a PEP 660 editable finder without installing anything in the host environment.
    script = root / "check_run.py"
    script.write_text("import importlib.util\nimport sys\n"
                      "spec = importlib.util.spec_from_file_location('editable_target', sys.argv[1])\n"
                      "module = importlib.util.module_from_spec(spec)\n"
                      "sys.modules['editable_target'] = module\nspec.loader.exec_module(module)\n"
                      "print('FAILED tests/a.py::test_a - assert')\nprint('1 failed in 0.1s')\nsys.exit(1)\n",
                      encoding="utf-8", newline="")
    git(root, "add", ".")
    git(root, "commit", "-qm", "editable fixture")
    monkeypatch.setenv("EDITABLE_SOURCE", str(root / "editable_target.py"))
    # Expansion happens in the shell, so the command itself has no absolute source reference.
    argument = '"%EDITABLE_SOURCE%"' if os.name == "nt" else '"$EDITABLE_SOURCE"'
    out = baseline.run_baseline(baseline.capture(root), f'"{sys.executable}" check_run.py {argument}',
                                tmp_path, 30, run_check)
    assert out["status"] == "Unknown"
    assert str(root / "editable_target.py") in out["import_origins"]


def test_unobservable_baseline_imports_are_unknown(tmp_path):
    root = repository(tmp_path / "repo")
    out = baseline.run_baseline(baseline.capture(root), f'"{sys.executable}" -S check_run.py',
                                tmp_path, 30, run_check)
    assert out["status"] == "Unknown" and out["import_origins"] == []


def test_baseline_stop_is_not_a_clean_piece_or_ability_failure():
    from ccx import lanes, merge, ui
    assert baseline.BASELINE_FAILED in lanes.BAD_KINDS
    assert baseline.BASELINE_FAILED in merge.NOT_DONE
    assert baseline.BASELINE_FAILED in ui.NOT_WRONG


def test_clean_snapshot_and_isolation(tmp_path):
    root = repository(tmp_path / "repo with spaces")
    start = baseline.capture(root)
    assert start["status"] == "ready"
    (root / "state.txt").write_text("new", encoding="utf-8")
    logs = tmp_path / "run"
    logs.mkdir()
    before = git(root, "status", "--porcelain")
    registry = git(root, "worktree", "list", "--porcelain")
    out = baseline.run_baseline(start, f'"{sys.executable}" check_run.py', logs, 30, run_check)
    assert out["status"] == "Fail"
    assert out["check"]["failed_cases"] == ["tests/test_old.py::test_old"]
    assert isinstance(out["seconds"], (int, float))
    assert not list(logs.glob("baseline-tree-*"))
    assert git(root, "status", "--porcelain") == before
    assert git(root, "worktree", "list", "--porcelain") == registry
    assert (root / "state.txt").read_text() == "new"


def test_dirty_and_untracked_start_unknown(tmp_path):
    root = repository(tmp_path / "repo")
    (root / "untracked").write_text("keep", encoding="utf-8")
    assert baseline.capture(root)["status"] == "Unknown"
    (root / "untracked").unlink()
    (root / "state.txt").write_text("dirty", encoding="utf-8")
    assert baseline.capture(root)["status"] == "Unknown"
    assert baseline.capture(tmp_path)["status"] == "Unknown"


def test_capture_does_not_refresh_the_source_index(tmp_path):
    root = repository(tmp_path / "repo")
    logs = tmp_path / "logs"
    logs.mkdir()
    # Same content, different stat cache: ordinary `git status` would refresh the index.
    os.utime(root / "state.txt", ns=(1_000_000_000_000, 1_000_000_000_000))
    index = root / ".git" / "index"
    before = index.read_bytes()
    assert baseline.capture(root, logs)["status"] == "ready"
    assert index.read_bytes() == before


def test_cleanup_failure_is_unknown_and_retains_evidence(tmp_path, monkeypatch):
    root = repository(tmp_path / "repo")
    logs = tmp_path / "run"
    logs.mkdir()
    def fail(path):
        raise PermissionError("simulated locked directory")
    monkeypatch.setattr(baseline, "_remove_tree", fail)
    out = baseline.run_baseline(baseline.capture(root), f'"{sys.executable}" check_run.py', logs, 30, run_check)
    assert out["status"] == "Unknown" and out["reason"] == "baseline cleanup failed"
    assert Path(out["cleanup_path"]).parent == logs
    assert Path(out["check"]["stdout_path"]).is_file()
    assert git(root, "status", "--porcelain") == ""


def test_checkout_failure_still_cleans(tmp_path, monkeypatch):
    root = repository(tmp_path / "repo")
    start = baseline.capture(root)
    logs = tmp_path / "run"
    logs.mkdir()
    real = baseline._git
    def fail(cwd, *args):
        if args[0] == "checkout":
            raise OSError("simulated checkout failure")
        return real(cwd, *args)
    monkeypatch.setattr(baseline, "_git", fail)
    out = baseline.run_baseline(start, "unused", logs, 30, run_check)
    assert out["status"] == "Unknown"
    assert not list(logs.glob("baseline-tree-*"))


def test_absolute_source_reference_is_unknown(tmp_path):
    root = repository(tmp_path / "repo")
    out = baseline.run_baseline(baseline.capture(root), f'python "{root}/check_run.py"', tmp_path, 30, run_check)
    assert out["status"] == "Unknown" and "absolute" in out["reason"]


def test_stream_logs_are_separate_and_bounded(tmp_path):
    out = {}
    baseline.save_logs(out, "x" * (baseline.LOG_BYTES + 1), "diagnostic", tmp_path, "check.1")
    assert Path(out["stdout_path"]).stat().st_size == baseline.LOG_BYTES
    assert out["stdout_truncated"] and not out["stderr_truncated"]
    assert Path(out["stderr_path"]).read_text() == "diagnostic"
    baseline.save_logs(out, "中" * (baseline.LOG_BYTES // 3 + 1), "", tmp_path, "unicode")
    assert Path(out["stdout_path"]).stat().st_size <= baseline.LOG_BYTES
    assert Path(out["stdout_path"]).read_text(encoding="utf-8").endswith("中")


def test_subdirectory_and_dispatch_commit_are_pinned(tmp_path):
    root = repository(tmp_path / "repo")
    (root / "sub").mkdir()
    (root / "sub" / "kept.txt").write_text("original", encoding="utf-8")
    git(root, "add", "sub/kept.txt")
    git(root, "commit", "-qm", "subdir")
    start = baseline.capture(root / "sub")
    (root / "sub" / "kept.txt").write_text("worker commit", encoding="utf-8")
    git(root, "add", "sub/kept.txt")
    git(root, "commit", "-qm", "worker")
    logs = tmp_path / "logs"
    logs.mkdir()
    def inspect(cmd, cwd, timeout, **kwargs):
        assert cwd.name == "sub"
        assert (cwd / "kept.txt").read_text() == "original"
        assert git(cwd, "rev-parse", "HEAD") == start["head"]
        return {"passed": True, "exit": 0}
    assert baseline.run_baseline(start, "inspect", logs, 30, inspect)["status"] == "Pass"
    assert (root / "sub" / "kept.txt").read_text() == "worker commit"


def test_real_pytest_summary_is_identified(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    monkeypatch.delenv("PYTEST_ADDOPTS", raising=False)
    (tmp_path / "test_sample.py").write_text("def test_broken():\n    assert False\n", encoding="utf-8", newline="")
    check = run_check(f'"{sys.executable}" -m pytest -q -p no:cacheprovider test_sample.py', tmp_path,
                      log_dir=tmp_path)
    assert check["failed_cases"] == ["test_sample.py::test_broken"]


def test_timeout_keeps_partial_logs(tmp_path, monkeypatch):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("check", 2, output=b"partial stdout", stderr=b"partial stderr")
    monkeypatch.setattr(subprocess, "run", timeout)
    check = run_check("check", tmp_path, 2, log_dir=tmp_path)
    assert check["exit"] == -1 and check["failed_cases"] is None
    assert Path(check["stdout_path"]).read_text() == "partial stdout"
    assert Path(check["stderr_path"]).read_text() == "partial stderr"


@pytest.mark.parametrize("ending", [b"\n", b"\r\n"])
def test_checkout_preserves_dispatch_bytes_even_when_git_normalizes_them(tmp_path, ending):
    root = repository(tmp_path / "repo")
    (root / " leading file.txt").write_text("kept", encoding="utf-8")
    git(root, "add", "--", " leading file.txt")
    git(root, "commit", "-qm", "spaced filename")
    git(root, "config", "core.autocrlf", "true")
    original = (root / "check_run.py").read_bytes().replace(b"\r\n", b"\n").replace(b"\n", ending)
    (root / "check_run.py").write_bytes(original)
    git(root, "add", "--renormalize", "check_run.py")
    assert git(root, "status", "--porcelain") == ""
    logs = tmp_path / "logs"
    logs.mkdir()
    start = baseline.capture(root, logs)
    assert start["status"] == "ready"
    (root / "check_run.py").write_bytes(b"worker changed this")
    def inspect(cmd, cwd, timeout, **kwargs):
        assert (cwd / "check_run.py").read_bytes() == original
        assert (cwd / " leading file.txt").read_text() == "kept"
        assert git(cwd, "rev-parse", "HEAD") == start["head"]
        assert git(cwd, "status", "--porcelain") == ""
        return {"passed": True, "exit": 0}
    assert baseline.run_baseline(start, "inspect", logs, 30, inspect)["status"] == "Pass"


class TestBaselineCommand(AdapterEnv):
    def setUp(self):
        super().setUp()
        repository(self.work)

    def run_checked(self, extra="", env=None):
        return self.j("run", "--from", "claude", "--to", "codex", "--tier", "T1", "--mode", "write",
                      "--review", "off", "--no-fallback", "--check", f'"{sys.executable}" check_run.py {extra}',
                      "fix state.txt", env=env or {"FAKE_WRITE": "state.txt=edited"})

    def enable(self):
        self.j("config", "set", "check.baseline", "on_fail")

    def test_baseline_only_does_not_climb_or_learn_task_failure(self):
        self.enable()
        out = self.run_checked()
        rec = self.rec(out["run_id"])
        assert out["kind"] == "check_baseline_failed"
        assert len(rec["attempts"]) == 1
        assert rec["learned"] is None
        assert rec["check_baseline_seconds"] >= 0
        rows = [json.loads(line) for line in (self.hub / "ccx" / "ledger.jsonl").read_text(encoding="utf-8").splitlines()]
        row = next(row for row in rows if row.get("run_id") == out["run_id"] and not row.get("type"))
        assert row["check_baseline_seconds"] == rec["check_baseline_seconds"]
        assert rec["check_baseline"]["check"]["exit"] == 1
        assert out["check"]["baseline_comparison"] == "baseline_only"
        assert "no check repair or escalation" in out["recap"]
        assert "outcome=check_baseline_failed" in out["recap"]
        assert Path(out["check"]["stdout_path"]).is_file()
        assert Path(out["check_baseline"]["check"]["stderr_path"]).is_file()
        assert not list((self.hub / "ccx" / "runs" / out["run_id"]).glob("baseline-tree-*"))
        assert (self.work / "state.txt").read_text() == "edited"

    def test_default_off_keeps_existing_climb_and_exit(self):
        out = self.run_checked()
        rec = self.rec(out["run_id"])
        assert out["kind"] == "check_failed" and len(rec["attempts"]) == 2
        assert "check_baseline" not in rec
        assert len(rec["checks"]) == 2
        assert rec["checks"][0]["stdout_path"] != rec["checks"][1]["stdout_path"]

    def test_new_failure_retries_only_new_cases_and_runs_baseline_once(self):
        self.enable()
        self.j("config", "set", "defaults.focused_retry", "true")
        out = self.run_checked(env={"FAKE_WRITE": "state.txt=new", "FAKE_WRITE_RESUMED": "state.txt=edited"})
        rec = self.rec(out["run_id"])
        assert len(rec["attempts"]) == 2
        assert out["kind"] == "check_baseline_failed"
        assert rec["checks"][0]["new_failures"] == ["tests/test_new.py::test_new"]
        prompt = [c for c in self.calls() if c["agent"] == "codex"][-1]["prompt"]
        assert "test_new" in prompt and "test_old" not in prompt
        assert len(list((self.hub / "ccx" / "runs" / out["run_id"]).glob("check.baseline.stdout.log"))) == 1

    def test_baseline_pass_keeps_existing_retry(self):
        self.enable()
        out = self.run_checked(extra="passbase")
        rec = self.rec(out["run_id"])
        assert out["kind"] == "check_failed" and len(rec["attempts"]) == 2
        assert out["check_baseline"]["status"] == "Pass"

    def test_equal_exit_with_unknown_cases_does_not_mask_failure(self):
        self.enable()
        out = self.run_checked(extra="opaque")
        rec = self.rec(out["run_id"])
        assert out["kind"] == "check_failed" and len(rec["attempts"]) == 2
        assert out["check"]["baseline_comparison"] == "Unknown"

    def test_dirty_dispatch_does_not_test_head_as_baseline(self):
        self.enable()
        (self.work / "state.txt").write_text("dirty", encoding="utf-8")
        out = self.run_checked()
        assert out["kind"] == "check_failed"
        assert out["check_baseline"]["status"] == "Unknown"
        assert "not clean" in out["check_baseline"]["reason"]

    def test_config_rejects_unknown_mode(self):
        result = self.ccx("config", "set", "check.baseline", "guess")
        assert result.returncode != 0

    def test_queue_baseline_failure_waits_for_lead(self):
        self.enable()
        item = self.j("q", "add", "fix state", "--brief", "fix state.txt", "--minutes", "5", "--to", "codex",
                      "--check", f'"{sys.executable}" check_run.py')
        out = self.j("q", "run", "--max", "1", env={"FAKE_WRITE": "state.txt=edited"})
        assert out["results"][0]["status"] == "blocked"
        assert item["id"] in out["open"]
        rec = self.rec(out["results"][0]["run"])
        assert rec["kind"] == "check_baseline_failed" and len(rec["attempts"]) == 1
        from ccx.commands.workqueue import restored
        assert restored(rec["run_id"], rec) == "decide"

    def merged(self, extra="", env=None):
        command = f'"{sys.executable}" check_run.py'
        tasks = [{"id": f"p{i}", "to": "codex", "tier": "T1", "mode": "write", "review": "off",
                  "minutes": 2, "brief": f"piece {i}", "cwd": str(self.work),
                  "check": command + (extra if i else "")} for i in range(2)]
        plan = self.hub / "plan.json"                 # leave the dispatch repository clean
        plan.write_text(json.dumps({"tasks": tasks}), encoding="utf-8")
        return self.j("batch", str(plan), "--from", "claude", "--merge", code=2,
                      env=env or {"FAKE_WRITE": "state.txt=edited"})

    def test_merged_baseline_failure_does_not_fix_or_spin_off(self):
        self.enable()
        out = self.merged()
        assert all(r["kind"] == "check_baseline_failed" for r in out["results"])
        rec = self.rec(out["results"][0]["run_id"])
        assert rec["kind"] == "check_baseline_failed"
        shown = self.j("show", rec["run_id"])
        assert shown["kind"] == "check_baseline_failed" and "check_baseline" in shown
        assert "no check repair or escalation" in shown["recap"]
        assert len(rec["check_baselines"]) == 1       # same command, one baseline execution
        assert len(rec["checks"]) == 2
        assert rec["checks"][0]["stdout_path"] != rec["checks"][1]["stdout_path"]
        assert out["merged"][0]["fix_run"] is None and not out["merged"][0]["spun_off"]
        assert len([c for c in self.calls() if c["agent"] == "codex"]) == 1
        assert all(Path(r["check"]["stdout_path"]).is_file() for r in out["results"])
        # A merged run has no single check field: its self-report must not produce a later soft success.
        from ccx import ledger
        from ccx.verdicts import soft_verdicts
        rec["result"]["verification"] = "self-check reported"
        ledger.write_record(Paths(self.hub).runs / rec["run_id"], rec)
        assert soft_verdicts(Paths(self.hub), min_age_h=0, now=rec["ts"] + 3600) == []

    def test_merged_distinct_commands_keep_distinct_baselines(self):
        self.enable()
        out = self.merged(extra=" other")
        rec = self.rec(out["results"][0]["run_id"])
        assert len(rec["check_baselines"]) == 2
        paths = [r["check_baseline"]["check"]["stdout_path"] for r in out["results"]]
        assert paths[0] != paths[1] and all(Path(p).is_file() for p in paths)
        assert rec["check_baseline_seconds"] == round(sum(b["seconds"] for b in rec["check_baselines"]), 3)

    def test_merged_retry_only_mentions_new_failures(self):
        self.enable()
        out = self.merged(env={"FAKE_WRITE": "state.txt=new", "FAKE_WRITE_RESUMED": "state.txt=edited"})
        calls = [c for c in self.calls() if c["agent"] == "codex"]
        assert len(calls) == 2
        assert "test_new" in calls[-1]["prompt"] and "test_old" not in calls[-1]["prompt"]
        assert all(r["kind"] == "check_baseline_failed" for r in out["results"])
        assert not out["merged"][0]["spun_off"]
