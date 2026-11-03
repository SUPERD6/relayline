"""Launcher controls stay in ccx, not in acceptance commands or agent CLIs. Fake CLIs only."""
import json
import os
import sys
from unittest import mock

import pytest

from test_ccx import Env

from ccx import review
from ccx.delegate import _child_env
from ccx.runners import without_launcher_vars
from ccx.workspace import canonical, run_check


LAUNCHER_ENV = {"CCX_RUN_ID": "launcher-run", "CCX_LEAD_VIEW": "full", "CCX_DISCUSS_ID": "launcher-discuss"}


def test_without_launcher_vars_strips_lowercase_controls():
    # A plain dict keeps the casing supplied by provider configuration, including on Windows.
    env = {"ccx_run_id": "launcher-run", "ccx_lead_view": "full", "ccx_discuss_id": "launcher-discuss",
           "CcX_LeAd_ViEw": "full", "Path": "keep", "CCX_PARENT_RUN": "parent"}
    before = dict(env)
    assert without_launcher_vars(env) == {"Path": "keep", "CCX_PARENT_RUN": "parent"}
    assert env == before


def test_run_check_does_not_inherit_launcher_controls(tmp_path, monkeypatch):
    for key, value in LAUNCHER_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("HOME", str(canonical(tmp_path / "home")))
    monkeypatch.setenv("PYTHONPATH", str(canonical(tmp_path / "python")))
    monkeypatch.setenv("CCX_CHECK_SENTINEL", "keep")
    keys = (*LAUNCHER_ENV, "HOME", "PATH", "PYTHONPATH", "CCX_CHECK_SENTINEL")
    cmd = (f'"{sys.executable}" -c "import json,os; '
           f'print(json.dumps({{k: os.environ.get(k) for k in {keys!r}}}))"')
    checked = run_check(cmd, canonical(tmp_path), tail_chars=20000)
    assert checked["passed"], checked
    child = json.loads(checked["tail"])
    for key, value in LAUNCHER_ENV.items():
        assert child[key] is None
        assert os.environ[key] == value
    for key in ("HOME", "PATH", "PYTHONPATH", "CCX_CHECK_SENTINEL"):
        assert child[key] == os.environ[key]


@pytest.mark.parametrize("agent", ["codex", "claude", "dsh", "gemini"])
@pytest.mark.parametrize("extra", [{}, LAUNCHER_ENV])
def test_child_env_strips_launcher_controls_and_keeps_subagent_identity(monkeypatch, agent, extra):
    for key, value in LAUNCHER_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("CCX_DEPTH", "2")
    monkeypatch.setenv("CCX_ROLE", "lead")
    monkeypatch.setenv("CCX_PARENT_RUN", "old-parent")
    monkeypatch.setenv("CCX_CHECK_SENTINEL", "keep")
    child = _child_env(agent, "child-run", extra)
    assert all(key not in child for key in LAUNCHER_ENV)
    assert child["CCX_DEPTH"] == "3"
    assert child["CCX_ROLE"] == "subagent"
    assert child["CCX_PARENT_RUN"] == "child-run"
    assert child["CCX_CHECK_SENTINEL"] == "keep"
    for key, value in LAUNCHER_ENV.items():
        assert os.environ[key] == value
    assert os.environ["CCX_DEPTH"] == "2"


def test_review_git_does_not_inherit_launcher_controls(tmp_path, monkeypatch):
    for key, value in LAUNCHER_ENV.items():
        monkeypatch.setenv(key, value)
    with mock.patch("ccx.review.subprocess.run") as run:
        run.return_value.returncode = 0
        run.return_value.stdout = "diff text"
        assert review._git(canonical(tmp_path), "diff") == "diff text"
    child = run.call_args.kwargs["env"]
    assert all(key not in child for key in LAUNCHER_ENV)
    assert child["PATH"] == os.environ["PATH"]


class TestBackgroundCheckEnv(Env):
    def test_bg_check_is_isolated_and_log_keeps_full_result(self):
        # Env.ccx runs a separate ccx process from a temp work folder outside the repository.
        (self.work / "check_env.py").write_text(
            "import json, os, sys\n"
            "from pathlib import Path\n"
            "keys = ('CCX_RUN_ID', 'CCX_LEAD_VIEW', 'CCX_DISCUSS_ID')\n"
            "seen = {k: os.environ.get(k) for k in keys}\n"
            "seen['CCX_CHECK_SENTINEL'] = os.environ.get('CCX_CHECK_SENTINEL')\n"
            "Path('check-env.json').write_text(json.dumps(seen), encoding='utf-8')\n"
            "sys.exit(1 if any(k in os.environ for k in keys) else 0)\n",
            encoding="utf-8")
        r = self.ccx("run", "--from", "claude", "--to", "codex", "--model", "gpt-6-luna", "--effort", "low",
                     "--no-ab", "--review", "off", "--check", f'"{sys.executable}" check_env.py',
                     "--bg", "--wait", "90", "implement thing",
                     env={"CCX_LEAD_VIEW": "line", "CCX_DISCUSS_ID": "outer-discuss", "CCX_CHECK_SENTINEL": "keep"})
        assert r.returncode == 0, r.stdout + r.stderr
        assert len(r.stdout.strip().splitlines()) == 1, r.stdout
        out = json.loads(r.stdout)
        assert (out["view"], out["ok"], out["status"]) == ("line", True, "done"), out
        assert out["check"]["passed"] is True
        seen = json.loads((self.work / "check-env.json").read_text(encoding="utf-8"))
        assert seen == {**dict.fromkeys(LAUNCHER_ENV), "CCX_CHECK_SENTINEL": "keep"}
        log = (self.hub / "ccx" / "runs" / out["run_id"] / "bg.log").read_text(encoding="utf-8")
        assert '  "tokens"' in log
        assert json.loads(log)["check"]["passed"] is True
