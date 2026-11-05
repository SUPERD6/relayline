"""Opt-in lead guidance, real sync/hook subprocess wiring and unchanged defaults."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from ccx.config import Paths, load_config, set_setting
from ccx.lead_slim import guidance_for, small_guidance
from ccx.sync import claude_memory_block, lead_memory_block

ROOT = Path(__file__).resolve().parents[1]


def test_default_off_and_shared_source(tmp_path):
    p = Paths(tmp_path / "hub")
    assert load_config(p)["lead"]["slim_small"] is False
    before = claude_memory_block(p)
    assert small_guidance(load_config(p)) == ""
    set_setting(p, "lead.slim_small", "on")
    text = small_guidance(load_config(p))
    assert "at most 1" in text and "no ccx command, brief file" in text
    assert "150000" in text and "90%" in text
    assert claude_memory_block(p) == before + "\n" + text
    assert text in lead_memory_block(p, "codex")
    set_setting(p, "lead.slim_small", "off")
    assert claude_memory_block(p) == before


@pytest.mark.parametrize("cfg", [{}, {"lead": {"slim_small": False}}, {"lead": {"slim_small": "true"}},
                                  {"policy": {"picked": "save"}}, {"routing": {"small_self_by": "cost"}},
                                  {"routing": {"small_self_files": "bad"}}])
def test_conservative_defaults_and_other_policies(cfg):
    if "lead" not in cfg and cfg:
        cfg = {**cfg, "lead": {"slim_small": True}}
    assert small_guidance(cfg) == ""


def test_existing_thresholds_are_used():
    text = small_guidance({"lead": {"slim_small": True}, "routing": {"small_self_files": 2,
                         "small_self_quota": 75}, "policy": {"bands": {"lead_ctx_large": 12345}}})
    assert "at most 2" in text and "75%" in text and "12345" in text
    for name in ("worktree", "undo", "resume", "another vendor", "uncertain"):
        assert name in text


def test_bad_optional_config_does_not_break_managed_context(tmp_path):
    p = Paths(tmp_path / "hub")
    before = claude_memory_block(p)
    p.user_tiers.parent.mkdir(parents=True)
    p.user_tiers.write_text("not valid = [", encoding="utf-8")
    assert guidance_for(p) == ""
    assert claude_memory_block(p) == before


def cli(args, cwd, env, data=None):
    return subprocess.run([sys.executable, str(ROOT / "ccx.py"), *args], cwd=cwd, env=env,
                          input=json.dumps(data) if data is not None else None,
                          capture_output=True, text=True, encoding="utf-8", timeout=30)


def test_config_sync_and_turn_from_outside_repo(tmp_path):
    env = {**os.environ, "CCX_NO_LOCATE": "1", "CCX_NO_QUOTA_PROBE": "1"}
    r = cli(["config", "set", "lead.slim_small", "true"], tmp_path, env)
    assert r.returncode == 0, r.stdout + r.stderr
    p = Paths(Path(env["CCX_HUB"]))
    expected = small_guidance(load_config(p))
    # Sync touches only fixture tool homes. No real CLI or credentials are used.
    r = cli(["sync", "--only", "memory", "--apply"], tmp_path, env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert expected in (Path(env["CLAUDE_CONFIG_DIR"]) / "CLAUDE.md").read_text(encoding="utf-8")
    assert expected in (Path(env["CODEX_HOME"]) / "AGENTS.md").read_text(encoding="utf-8")
    for agent in ("claude", "codex"):
        r = cli(["turn", "--as", agent], tmp_path, env, {"cwd": str(tmp_path)})
        assert r.returncode == 0, r.stdout + r.stderr
        assert expected in r.stdout
    for key, value in (("CCX_ROLE", "subagent"), ("CCX_DEPTH", "1")):
        r = cli(["turn", "--as", "claude"], tmp_path, {**env, key: value}, {"cwd": str(tmp_path)})
        assert r.returncode == 0 and expected not in r.stdout
    assert cli(["config", "set", "lead.slim_small", "false"], tmp_path, env).returncode == 0
    r = cli(["turn", "--as", "claude"], tmp_path, env, {"cwd": str(tmp_path)})
    assert r.returncode == 0 and expected not in r.stdout
