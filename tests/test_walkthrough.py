"""Credential-free walkthrough isolation and newcomer instructions."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

from test_ccx import Env

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/walkthrough.py"
spec = importlib.util.spec_from_file_location("walkthrough", SCRIPT)
walk = importlib.util.module_from_spec(spec)
spec.loader.exec_module(walk)


def test_environment_drops_credentials_and_real_tools(tmp_path, monkeypatch):
    for key in ("OPENAI_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN", "CCX_CODEX_BIN", "PYTHONPATH",
                "PIP_INDEX_URL", "CCX_LEAD", "GIT_CONFIG_COUNT"):
        monkeypatch.setenv(key, "must-not-forward")
    env = walk.environment(tmp_path)
    assert "must-not-forward" not in env.values()
    for key in ("HOME", "USERPROFILE", "CCX_HUB", "CCX_CONFIG", "CODEX_HOME", "CLAUDE_CONFIG_DIR", "DSH_HOME"):
        assert Path(env[key]).is_relative_to(tmp_path)
    assert all(Path(item).is_relative_to(tmp_path) for item in env["PATH"].split(os.pathsep))
    assert env["PIP_CONFIG_FILE"] == os.devnull


def test_script_from_outside_checkout(tmp_path):
    # No network, cached dependencies or real CLIs. Installation may fail; it must
    # remain a failure while subsequent source checks still exercise the workflow.
    proc = subprocess.run([sys.executable, str(SCRIPT)], cwd=tmp_path, capture_output=True,
                          text=True, encoding="utf-8", timeout=180)
    first = proc.stdout.splitlines()[0]
    base = Path(first.removeprefix("Artifacts (retained): "))
    result = json.loads((base / "result.json").read_text(encoding="utf-8"))
    steps = {step["step"]: step for step in result["steps"]}
    assert proc.returncode in (0, 1), proc.stdout + proc.stderr
    for name in ("setup-preview", "setup-apply", "doctor", "demo", "ui", "readme-first-run", "show", "fake-only"):
        assert steps[name]["verdict"] == "Pass", (name, proc.stdout, base)
    installed = steps["install-editable"]["verdict"] == "Pass"
    assert steps["execution-mode"]["mode"] == ("installed" if installed else "source-fallback")
    assert result["verdict"] == ("Pass" if installed else "Fail")
    assert proc.returncode == (0 if installed else 1)
    assert result["real_models"] == "not run"
    setup = (base / "logs/setup-apply.stdout.txt").read_text(encoding="utf-8")
    assert "FAILED" not in setup


class TestSetupInstructions(Env):
    def test_first_try_names_its_input_and_both_verdicts(self):
        # This CLI runs from Env.work, outside the repository, with fake CLIs.
        proc = self.ccx("setup", "--yes", env={"FAKE_CODEX_LOGIN": "Not logged in"})
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "project folder containing README.md" in proc.stdout
        assert "ccx show <run_id>" in proc.stdout
        assert "--ok 1 (correct) or --ok 0 (wrong)" in proc.stdout
