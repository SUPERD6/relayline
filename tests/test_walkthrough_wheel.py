"""Installed-wheel mode never masks a broken package with a source fallback."""
import json
from pathlib import Path
import subprocess

import pytest

from test_ccx import Env
from test_walkthrough import walk


@pytest.mark.parametrize("failure", [None, "wheel", "install"])
def test_wheel_install_and_installed_entry_point(tmp_path, monkeypatch, failure):
    calls = []

    def run(argv, *, cwd, env, **kwargs):
        calls.append(argv)
        assert cwd == tmp_path / "work"
        assert "PYTHONPATH" not in env
        stdout, rc = "", 0
        if "wheel" in argv:
            if failure == "wheel":
                rc = 1
            else:
                walk.write(tmp_path / "wheels/relayline-0.0.0-py3-none-any.whl", "stand-in wheel")
        elif "install" in argv:
            assert "--no-index" in argv
            assert "-e" not in argv
            assert argv[-1].endswith(".whl")
            rc = 1 if failure == "install" else 0
        elif "setup" in argv:
            stdout = "Nothing was changed."
        elif "--export" in argv:
            walk.write(Path(argv[-1]), "<html>fake export</html>")
        elif "run" in argv:
            stdout = json.dumps({"status": "done", "run_id": "fake-run"})
            walk.write(Path(env["FAKE_LOG"]), json.dumps({"agent": "codex"}) + "\n")
        return subprocess.CompletedProcess(argv, rc, stdout, "")

    monkeypatch.setattr(walk.subprocess, "run", run)
    result = walk.walkthrough(tmp_path, wheelhouse=tmp_path / "dependencies", installed_wheel=True)
    assert result["verdict"] == ("Fail" if failure else "Pass")
    assert result["real_models"] == "not run"
    steps = {row["step"]: row for row in result["steps"]}
    assert "install-editable" not in steps
    build = steps["build-wheel"]["argv"]
    assert "wheel" in build and "--no-index" in build
    assert "--find-links" in build
    if failure:
        assert "setup-preview" not in steps
        assert steps["build-wheel" if failure == "wheel" else "install-wheel"]["verdict"] == "Fail"
    else:
        entry = tmp_path / "venv" / ("Scripts/ccx.exe" if walk.os.name == "nt" else "bin/ccx")
        assert steps["execution-mode"]["mode"] == "installed"
        for name in ("setup-preview", "setup-apply", "doctor", "demo", "ui", "readme-first-run", "show"):
            assert steps[name]["argv"][0] == str(entry)
            assert steps[name]["verdict"] == "Pass"
    assert all(not any(str(arg).endswith("source/ccx.py") for arg in argv) for argv in calls)


class TestSetupIntroduction(Env):
    def test_three_messages_before_the_tool_checks(self):
        proc = self.ccx("setup", stdin="")
        assert proc.returncode == 0, proc.stderr
        intro = proc.stdout.split("Check the tools", 1)[0]
        assert "quota runs out (experimental" in intro
        assert "Share memory and context" in intro
        assert "one ledger across tools" in intro
        assert "API-equivalent" in intro
