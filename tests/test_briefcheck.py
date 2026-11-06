"""Conservative pre-dispatch checks, including CLI wiring from outside the checkout."""
import json
import os
import io
from pathlib import Path
from unittest.mock import Mock

import pytest

from ccx import briefcheck, cli, leadview
from test_ccx import Env


@pytest.mark.parametrize("text", [
    "Write report.md", "Create a file called report.md", "Edit the file ccx/a.py",
    "Please open a PR", "Create a pull request", "gh pr create --title fix",
    "修改文件 ccx/a.py", "创建 PR", "Write files in the workspace",
])
def test_explicit_read_write_conflicts(tmp_path, text):
    assert "read_requires_write" in {w["code"] for w in briefcheck.check(text, "read", tmp_path)}


@pytest.mark.parametrize("text", [
    "Review the change and suggest how to write report.md",
    "Explain how to create a PR", "Do not write report.md", "Do not open a PR",
    "Read-only review; no edits; suggest a patch in your response",
    "检查这次修改，提出建议", "不要修改文件", "Write a summary in your response",
    "Read https://example.org/file.md", "Read `docs/*.md`", "Read `<project>/a.py`",
    "Read `$ROOT/a.py`", "Read `~/.codex/config.toml`", "Read `.ccx/eval-codex-home/a.py`",
    "Create `new/output.md`",  # new outputs do not have to exist yet
    "Readme.md describes the project", "OpenAI.md is the reference",
    "Read `optional.md` if it exists", "Read `optional.md` if present",
    "Do not execute the following example:\n```sh\ngh pr create --title example\n```",
    "Explain this example:\n~~~text\nWrite report.md\n~~~",
    "> Write report.md\nExplain the quoted instruction",
])
def test_false_positive_examples(tmp_path, text):
    assert briefcheck.check(text, "read" if not text.startswith("Create") else "write", tmp_path) == []


def test_missing_input_uses_cwd_and_deduplicates(tmp_path):
    (tmp_path / "present.md").write_text("ok", encoding="utf-8")
    warnings = briefcheck.check("Read `present.md`; Read `docs/missing.md`; Read `docs/missing.md`",
                                "write", tmp_path)
    assert [(w["code"], w["path"]) for w in warnings] == [("missing_input", "docs/missing.md")]


@pytest.mark.parametrize("text", [
    "阅读docs/a.md，并总结", "阅读docs/a.md；然后总结", "阅读`docs/a.md`，并总结",
    "读取docs/a.md：总结内容", "阅读docs/a.md（只读）",
])
def test_chinese_punctuation_does_not_become_part_of_input(tmp_path, text):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "a.md").write_text("ok", encoding="utf-8")
    assert briefcheck.check(text, "read", tmp_path) == []


def test_missing_path_before_chinese_punctuation_still_warns(tmp_path):
    warnings = briefcheck.check("阅读docs/a.md，并总结", "read", tmp_path)
    assert [(w["code"], w["path"]) for w in warnings] == [("missing_input", "docs/a.md")]


@pytest.mark.parametrize("value", ["os.path", "3.11", "package.module", "foo.unknown"])
def test_dotted_words_are_not_files(tmp_path, value):
    assert briefcheck.check(f"Read `{value}`", "read", tmp_path) == []


@pytest.mark.parametrize("suffix", ["py", "md", "json", "toml", "txt", "yaml", "yml", "cfg", "ini", "js", "ts"])
def test_common_bare_file_extensions_still_checked(tmp_path, suffix):
    warnings = briefcheck.check(f"Read `missing.{suffix}`", "read", tmp_path)
    assert warnings[0]["code"] == "missing_input"


@pytest.mark.parametrize("text", ["写一个报告文件", "写个报告文件", "Write the report to out.md",
                                  "Write a report to `docs/out.txt`"])
def test_report_file_requests_need_write(tmp_path, text):
    assert [w["code"] for w in briefcheck.check(text, "read", tmp_path)] == ["read_requires_write"]
    assert briefcheck.check(text, "write", tmp_path) == []


@pytest.mark.parametrize("text", ["不要写报告", "报告给我", "Write the report to me",
                                  "Explain how to write the report to out.md", "说明怎么写一个报告文件"])
def test_report_prose_is_not_a_write_request(tmp_path, text):
    assert briefcheck.check(text, "read", tmp_path) == []


def test_strict_stdin_reads_exactly_once(tmp_path, monkeypatch, capsys):
    class Once(io.StringIO):
        reads = 0

        def read(self, *args, **kwargs):
            self.reads += 1
            assert self.reads == 1, "stdin must not be consumed again after preflight"
            return super().read(*args, **kwargs)

    stdin = Once("写一个报告文件")
    monkeypatch.setattr("sys.stdin", stdin)
    assert cli.main(["run", "--mode", "read", "--strict-brief", "--cwd", str(tmp_path)]) == 2
    assert stdin.reads == 1
    assert json.loads(capsys.readouterr().out)["brief_warnings"][0]["code"] == "read_requires_write"


def test_strict_clean_stdin_read_once_through_dispatch(tmp_path, monkeypatch):
    class ReachedDispatch(Exception):
        pass

    stdin = io.StringIO("Explain the algorithm from stdin")
    read = Mock(wraps=stdin.read)
    monkeypatch.setattr(stdin, "read", read)
    monkeypatch.setattr("sys.stdin", stdin)

    def dispatch(req, paths):
        assert req.brief == "Explain the algorithm from stdin"
        raise ReachedDispatch

    monkeypatch.setattr("ccx.commands.delegation.run", dispatch)
    with pytest.raises(ReachedDispatch):
        cli.main(["run", "--from", "claude", "--to", "codex", "--tier", "T1", "--force", "--new",
                  "--mode", "read", "--strict-brief", "--cwd", str(tmp_path)])
    assert read.call_count == 1


def test_foreign_paths_are_unknown(tmp_path):
    assert briefcheck.check(r"Read `C:\project\input.md`", "read", tmp_path, platform="posix") == []
    assert briefcheck.check("Read `/tmp/input.md`", "read", tmp_path, platform="nt") == []


@pytest.mark.parametrize("platform,command", [
    ("nt", "export TEST=1; python -m unittest"), ("nt", "TEST=1 python -m unittest"),
    ("nt", "./tests/check.sh"), ("posix", r".\tests\check.ps1"),
    ("posix", "$env:TEST=1; python -m unittest"), ("posix", r"C:\tools\check.exe"),
])
def test_obvious_platform_mismatches(tmp_path, platform, command):
    assert [w["code"] for w in briefcheck.check("Inspect results", "read", tmp_path, command,
                                                platform=platform)] == ["platform_command"]


@pytest.mark.parametrize("command", [
    "python -m unittest", "python -m pytest && python -m unittest",
    "bash tests/check.sh", "wsl ./tests/check.sh", "powershell -File tests/check.ps1",
    "pwsh -Command '$env:TEST=1'", 'python -c "print(\'export TEST=1\')"',
])
def test_wrapped_or_portable_commands_not_flagged(tmp_path, command):
    for platform in ("nt", "posix"):
        assert briefcheck.check("Inspect results", "read", tmp_path, command, platform=platform) == []


@pytest.mark.parametrize("text", [
    "Run `export TEST=1`", "Run `export TEST=1; python -m unittest`",
    "1. Run `export TEST=1`", "Please run `export TEST=1`",
    "Inspect results; Run `export TEST=1`",
])
def test_brief_check_command_is_checked(tmp_path, text):
    assert briefcheck.check(text, "read", tmp_path, platform="nt")[0]["code"] == "platform_command"


def test_commands_in_fenced_examples_are_skipped(tmp_path):
    assert briefcheck.check("Explain this:\n```sh\nRun `export TEST=1`\n```", "read", tmp_path,
                            platform="nt") == []


def test_warning_keeps_full_receipt():
    res = {"ok": True, "status": "done", "check": {"passed": True},
           "brief_warnings": [{"code": "missing_input"}]}
    assert not leadview.clean(res)


class TestBriefCLI(Env):
    def run_args(self, *args, **kwargs):
        return self.ccx("run", "--from", "claude", "--to", "codex", "--tier", "T1",
                        "--review", "off", "--mode", "read", *args, **kwargs)

    def test_default_warns_runs_and_persists_in_show(self):
        r = self.run_args("Read `docs/missing.md`")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        out = json.loads(r.stdout)
        self.assertIn("brief warning [missing_input]", r.stderr)
        self.assertEqual(out["brief_warnings"][0]["code"], "missing_input")
        self.assertEqual(len(self.calls()), 1)
        shown = self.ccx("show", out["run_id"])
        self.assertEqual(shown.returncode, 0, shown.stderr)
        self.assertEqual(json.loads(shown.stdout)["brief_warnings"], out["brief_warnings"])

    def test_strict_blocks_before_fake_cli_or_run(self):
        r = self.run_args("--strict-brief", "Write report.md")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        out = json.loads(r.stdout)
        self.assertFalse(out["delegated"])
        self.assertEqual(out["brief_warnings"][0]["code"], "read_requires_write")
        self.assertEqual(self.calls(), [])
        self.assertFalse(list((self.hub / "ccx" / "runs").glob("*/run.json")))

    def test_strict_blocks_background_before_detaching(self):
        r = self.run_args("--bg", "--strict-brief", "Open a PR")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertFalse(json.loads(r.stdout)["delegated"])
        self.assertEqual(self.calls(), [])

    def test_strict_blocks_missing_input(self):
        r = self.run_args("--strict-brief", "Read `missing.md`")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertEqual(json.loads(r.stdout)["brief_warnings"][0]["code"], "missing_input")
        self.assertEqual(self.calls(), [])

    def test_strict_blocks_incompatible_check_before_execution(self):
        command = "export TEST=1" if os.name == "nt" else "$env:TEST=1"
        r = self.run_args("--strict-brief", "--check", command, "Explain results")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertEqual(json.loads(r.stdout)["brief_warnings"][0]["code"], "platform_command")
        self.assertEqual(self.calls(), [])

    def test_strict_clean_brief_keeps_default_receipt(self):
        r = self.run_args("--strict-brief", "Explain the algorithm")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("brief_warnings", json.loads(r.stdout))
        self.assertEqual(len(self.calls()), 1)

    def test_stdin_is_not_consumed_twice(self):
        r = self.run_args(stdin="Explain the algorithm")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("Explain the algorithm", self.calls()[-1]["prompt"])

    def test_strict_stdin_keeps_the_brief_through_dispatch(self):
        r = self.run_args("--strict-brief", stdin="Explain the algorithm from stdin")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("Explain the algorithm from stdin", self.calls()[-1]["prompt"])

    def test_background_warning_emitted_only_by_parent(self):
        r = self.run_args("--bg", "Read `missing.md`")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(r.stderr.count("brief warning [missing_input]"), 1)
        shown = self.ccx("show", out["run_id"], "--wait")
        self.assertEqual(shown.returncode, 0, shown.stdout + shown.stderr)
        self.assertEqual(json.loads(shown.stdout)["brief_warnings"], out["brief_warnings"])
        # after --wait the child has finished; its log must not repeat the parent's diagnostic.
        log = Path(out["log"]).read_text(encoding="utf-8")
        self.assertNotIn("ccx: brief warning [", log)

    def test_background_warning_in_initial_and_final_receipt(self):
        r = self.run_args("--bg", "Read `missing.md`")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out["brief_warnings"][0]["code"], "missing_input")
        shown = self.ccx("show", out["run_id"], "--wait")
        self.assertEqual(shown.returncode, 0, shown.stdout + shown.stderr)
        self.assertEqual(json.loads(shown.stdout)["brief_warnings"], out["brief_warnings"])

    def test_brief_file_uses_target_cwd(self):
        target = self.work / "target"
        target.mkdir()
        (target / "input.md").write_text("ok", encoding="utf-8")
        brief = self.work / "brief.md"
        brief.write_text("Read `input.md`", encoding="utf-8")
        r = self.run_args("--strict-brief", "--cwd", str(target), "--brief-file", str(brief))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("brief_warnings", json.loads(r.stdout))
