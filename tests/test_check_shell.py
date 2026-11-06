"""Issue #278: shell mismatch is broken acceptance, not failed work."""
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ccx import check_shell, workspace
from test_ccx import Env


@pytest.mark.parametrize("cmd", [
    "export PYTHONPATH=.; python -m pytest",
    "export X=1 && python -m pytest",
    "python -m pytest && export X=1",
    "PYTHONPATH=. python -m pytest",
    'echo "$PYTHONPATH"', "echo ${VALUE}", "echo $VALUE", "echo $(pwd)",
])
def test_bash_syntax(cmd):
    assert check_shell.needs_bash(cmd)


@pytest.mark.parametrize("cmd", [
    "python -m pytest", "python -m pytest && echo ok", "set X=1 && echo %X%",
    'python -c "print(\'export X=1 && foo\')"', "echo 'export X=1; $VALUE'",
    'python -c "print(\'$VALUE\')"', 'pwsh -Command "Write-Output $env:PATH"',
    'python -m pytest -k "a or b"', 'echo export', r'echo C:\work\tests',
])
def test_native_commands_keep_existing_shell(cmd):
    assert not check_shell.needs_bash(cmd)


def windows(monkeypatch):
    # Do not mutate global os.name: pathlib and pytest must keep the host platform.
    monkeypatch.setattr(workspace, "os", SimpleNamespace(name="nt", environ=dict(os.environ)))
    monkeypatch.setattr(workspace, "_check_doubt", lambda *a: {})


def test_windows_export_uses_bash_without_cmd_quote_rewrite(tmp_path, monkeypatch):
    windows(monkeypatch)
    resolver = Mock(return_value="git-bash.exe")
    monkeypatch.setattr(check_shell, "find_bash", resolver)
    run = Mock(return_value=subprocess.CompletedProcess([], 0, "checked", ""))
    monkeypatch.setattr(workspace.subprocess, "run", run)
    cmd = "export X=1 && python -m pytest tests/test_*.py -k 'a or b'"
    out = workspace.run_check(cmd, tmp_path, env={"PATH": "fixture", "CCX_RUN_ID": "outer"})
    assert out["passed"] and out["cmd"] == cmd and "ran" not in out
    assert run.call_args.args[0] == ["git-bash.exe", "--noprofile", "--norc", "-c", cmd]
    assert run.call_args.kwargs["shell"] is False
    assert resolver.call_args.args[0] == {"PATH": "fixture"}
    assert run.call_args.kwargs["env"] == {"PATH": "fixture"}


def test_missing_bash_is_broken_and_preserves_logs(tmp_path, monkeypatch):
    windows(monkeypatch)
    monkeypatch.setattr(check_shell, "find_bash", lambda env: None)
    run = Mock(return_value=subprocess.CompletedProcess([], 1, "", "export is not recognized"))
    monkeypatch.setattr(workspace.subprocess, "run", run)
    cmd = "export X=1 && python -m pytest"
    out = workspace.run_check(cmd, tmp_path, log_dir=tmp_path)
    assert out["status"] == "check_broken" and not out["passed"]
    assert out["exit"] == -1 and out["cmd"] == cmd
    assert "Bash" in out["broken"] and "--check" in out["broken"]
    assert "Bash" in Path(out["stderr_path"]).read_text(encoding="utf-8")
    run.assert_not_called()


def test_bash_launch_error_is_broken(tmp_path, monkeypatch):
    windows(monkeypatch)
    monkeypatch.setattr(check_shell, "find_bash", lambda env: "gone-bash.exe")
    monkeypatch.setattr(workspace.subprocess, "run", Mock(side_effect=OSError("cannot execute")))
    out = workspace.run_check("export X=1", tmp_path)
    assert out["status"] == "check_broken" and "cannot execute" in out["broken"]


@pytest.mark.parametrize("code,broken", [(0, False), (1, False), (4, True), (5, True)])
def test_bash_exit_keeps_existing_verdicts(tmp_path, monkeypatch, code, broken):
    windows(monkeypatch)
    monkeypatch.setattr(check_shell, "find_bash", lambda env: "git-bash.exe")
    monkeypatch.setattr(workspace.subprocess, "run",
                        Mock(return_value=subprocess.CompletedProcess([], code, "", "")))
    out = workspace.run_check("export X=1 && python -m pytest", tmp_path)
    assert out["exit"] == code and out["passed"] == (code == 0)
    assert (out.get("status") == "check_broken") == broken


def test_cmd_path_still_expands_single_quotes(tmp_path, monkeypatch):
    windows(monkeypatch)
    resolver = Mock(side_effect=AssertionError("ordinary command must not discover Bash"))
    monkeypatch.setattr(check_shell, "find_bash", resolver)
    run = Mock(return_value=subprocess.CompletedProcess([], 1, "", ""))
    monkeypatch.setattr(workspace.subprocess, "run", run)
    out = workspace.run_check("python -m pytest -k 'a or b' && echo done", tmp_path)
    assert out["ran"] == 'python -m pytest -k "a or b" && echo done'
    assert run.call_args.kwargs["shell"] is True
    assert "status" not in out and out["exit"] == 1


def test_posix_keeps_native_shell(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "os", SimpleNamespace(name="posix", environ={}))
    monkeypatch.setattr(workspace, "_check_doubt", lambda *a: {})
    monkeypatch.setattr(check_shell, "find_bash", Mock(side_effect=AssertionError("not Windows")))
    run = Mock(return_value=subprocess.CompletedProcess([], 0, "", ""))
    monkeypatch.setattr(workspace.subprocess, "run", run)
    cmd = "export X=1 && echo $X"
    assert workspace.run_check(cmd, tmp_path)["passed"]
    assert run.call_args.args == (cmd,) and run.call_args.kwargs["shell"] is True


def test_find_bash_on_path(monkeypatch):
    which = Mock(return_value="fixture/bash.exe")
    monkeypatch.setattr(check_shell.shutil, "which", which)
    assert check_shell.find_bash({"Path": "fixture"}) == "fixture/bash.exe"
    which.assert_called_once_with("bash", path="fixture")


def test_find_git_bash_in_standard_layout(tmp_path, monkeypatch):
    root = tmp_path / "Git"
    bash = root / "bin" / "bash.exe"
    bash.parent.mkdir(parents=True)
    bash.write_bytes(b"fake")
    monkeypatch.setattr(check_shell.shutil, "which", lambda name, **kw:
                        str(root / "cmd" / "git.exe") if name == "git" else None)
    assert check_shell.find_bash({"PATH": "fixture"}) == str(bash)


def test_wsl_launcher_is_not_git_bash(monkeypatch):
    monkeypatch.setattr(check_shell.shutil, "which", lambda name, **kw:
                        r"C:\Windows\System32\bash.exe" if name == "bash" else None)
    assert check_shell.find_bash({"PATH": "fixture"}) is None


@pytest.mark.skipif(sys.platform != "win32", reason="Windows shell selection")
class TestShellReceipt(Env):
    def test_real_git_bash_with_space_and_non_ascii_cwd(self):
        if not check_shell.find_bash(self.env):
            pytest.skip("Git Bash is not installed on this Windows host")
        self.work = self.work / "验收 空格"
        self.work.mkdir()
        (self.work / "check.py").write_text(
            "import os\nfrom pathlib import Path\n"
            "assert Path.cwd().name == '验收 空格'\n"
            "assert os.environ['CHECK_SENTINEL'] == 'present'\n"
            "print('CHECK_OK')\n", encoding="utf-8", newline="")
        cmd = f'export CHECK_SENTINEL=present && "{Path(sys.executable).as_posix()}" check.py'
        result = self.ccx("run", "--from", "claude", "--tier", "T1", "--mode", "write",
                          "--review", "off", "--check", cmd, "do it")
        out = json.loads(result.stdout)
        assert out["ok"] and out["check"]["passed"], (result.returncode, out, result.stderr)
        record = json.loads((self.hub / "ccx" / "runs" / out["run_id"] / "run.json").read_text(encoding="utf-8"))
        assert "CHECK_OK" in record["check"]["tail"]
        assert len(self.calls()) == 1

    def test_missing_bash_remedy_reaches_lead(self):
        result = self.ccx("run", "--from", "claude", "--tier", "T1", "--mode", "write",
                          "--review", "off", "--check", "export X=1 && echo $X", "do it", env={"PATH": ""})
        out = json.loads(result.stdout)
        assert out["kind"] == "check_broken", (result.returncode, out, result.stderr)
        assert "Install Git Bash or rewrite --check for cmd.exe" in out["needs_lead"]
        assert "check shell could not start" not in out["needs_lead"]

    def test_missing_bash_stops_without_escalation(self):
        # Env.ccx launches the actual CLI from a temporary folder outside the repo;
        # agent invocations use tests/fakes, and an empty PATH makes Bash unavailable.
        result = self.ccx("run", "--from", "claude", "--tier", "T1", "--mode", "write",
                          "--review", "off", "--check", "export X=1 && echo $X", "do it", env={"PATH": ""})
        out = json.loads(result.stdout)
        assert out["kind"] == "check_broken", (result.returncode, out, result.stderr)
        assert not out["ok"] and "Bash" in out["needs_lead"]
        record = json.loads((self.hub / "ccx" / "runs" / out["run_id"] / "run.json").read_text(encoding="utf-8"))
        assert "Bash" in record["check"]["broken"]
        assert len(self.calls()) == 1


@pytest.mark.parametrize("cmd", [
    "echo $env:FOO", 'echo "$env:FOO"', "echo $environment:FOO",
    r'echo C:\work\$x\file', 'echo "C:/work/$x/file"', "echo ./work/$x/file", "echo C:$x",
])
def test_powershell_variables_and_literal_paths_do_not_select_bash(cmd):
    assert not check_shell.needs_bash(cmd)


@pytest.mark.parametrize("cmd", ["echo $NAME", "echo ${NAME}", "echo $(pwd)", "echo $ROOT/tests"])
def test_supported_bash_expansions_still_select_bash(cmd):
    assert check_shell.needs_bash(cmd)


def test_backslash_paths_have_a_check_warning(tmp_path, monkeypatch):
    windows(monkeypatch)
    monkeypatch.setattr(check_shell, "find_bash", lambda env: "git-bash.exe")
    monkeypatch.setattr(workspace.subprocess, "run",
                        Mock(return_value=subprocess.CompletedProcess([], 0, "", "")))
    out = workspace.run_check(r'export X=1 && python C:\work\check.py', tmp_path)
    assert out["passed"] and "backslashes" in out["shell_warning"]
    assert "forward slashes" in out["shell_warning"]


@pytest.mark.parametrize("platform,cmd,existing_bash,missing_cwd", [
    ("posix", "echo ok", False, True),
    ("posix", "export X=1", False, False),
    ("nt", "echo ok", False, True),
    ("nt", "export X=1", True, True),
    ("nt", "export X=1", True, False),
])
def test_preexisting_os_errors_propagate(tmp_path, monkeypatch, platform, cmd, existing_bash, missing_cwd):
    monkeypatch.setattr(workspace, "os", SimpleNamespace(name=platform, environ={}))
    bash = tmp_path / "bash.exe"
    if existing_bash:
        bash.write_bytes(b"fake")
    monkeypatch.setattr(check_shell, "find_bash", lambda env: str(bash))
    monkeypatch.setattr(workspace.subprocess, "run", Mock(side_effect=OSError("original failure")))
    cwd = tmp_path / "missing" if missing_cwd else tmp_path
    with pytest.raises(OSError, match="original failure"):
        workspace.run_check(cmd, cwd)


@pytest.mark.parametrize("launcher", [
    r"C:\Windows\SysWOW64\bash.exe", r"C:\Windows\Sysnative\bash.exe",
    r"C:\Users\example\AppData\Local\Microsoft\WindowsApps\bash.exe",
    r"C:\Program Files\WindowsApps\Package\bash.exe",
])
def test_other_wsl_launchers_are_excluded(monkeypatch, launcher):
    monkeypatch.setattr(check_shell.shutil, "which", lambda name, **kw: launcher if name == "bash" else None)
    assert check_shell.find_bash({"PATH": "fixture"}) is None


@pytest.mark.parametrize("layout", ["mingw64/bin/git.exe", "scoop/shims/git.exe"])
def test_git_bash_discovery_from_nested_git_and_scoop(tmp_path, monkeypatch, layout):
    git = tmp_path / layout
    root = tmp_path / "scoop/apps/git/current" if layout.startswith("scoop/") else tmp_path
    bash = root / "usr/bin/bash.exe"
    bash.parent.mkdir(parents=True)
    bash.write_bytes(b"fake")
    monkeypatch.setattr(check_shell.shutil, "which", lambda name, **kw: str(git) if name == "git" else None)
    assert check_shell.find_bash({"PATH": "fixture"}) == str(bash)
