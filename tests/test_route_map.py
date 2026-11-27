"""Split rule v0 (#545): off = unchanged output; on = the text once; self-work costs nothing."""
import json
import os
from pathlib import Path
import subprocess
import sys

from ccx import lead_slim
from ccx.config import Paths, load_config, set_setting
from ccx.lead_slim import guidance_for, route_map_guidance, small_guidance
from ccx.sync import claude_memory_block, lead_memory_block

ROOT = Path(__file__).resolve().parents[1]


def test_default_off_and_output_unchanged(tmp_path):
    p = Paths(tmp_path / "hub")
    assert load_config(p)["lead"]["route_map"] is False
    before = (claude_memory_block(p), lead_memory_block(p, "codex"), guidance_for(p))
    set_setting(p, "lead.route_map", "false")
    assert (claude_memory_block(p), lead_memory_block(p, "codex"), guidance_for(p)) == before
    assert route_map_guidance(load_config(p)) == ""
    set_setting(p, "lead.route_map", "on")
    assert claude_memory_block(p) != before[0]
    set_setting(p, "lead.route_map", "off")
    assert (claude_memory_block(p), lead_memory_block(p, "codex"), guidance_for(p)) == before


def test_on_text_appears_exactly_once(tmp_path):
    p = Paths(tmp_path / "hub")
    set_setting(p, "lead.route_map", "true")
    text = route_map_guidance(load_config(p))
    assert "Do it yourself unless" in text and "none yet" in text and "If unsure" in text
    assert "call no ccx command" in text and "start no process" in text   # self-work: no ccx call, no process
    for block in (claude_memory_block(p), lead_memory_block(p, "codex"), guidance_for(p)):
        assert block.count(text) == 1
    set_setting(p, "lead.slim_small", "true")                  # next to the other guidance: still once each
    both = guidance_for(p)
    assert both.count(text) == 1 and both.count(small_guidance(load_config(p))) == 1


def test_only_true_switches_it_on_and_v0_has_no_cells():
    assert lead_slim.PROVEN_CELLS == ()
    for cfg in ({}, {"lead": {}}, {"lead": {"route_map": "true"}}, {"lead": {"route_map": 1}}):
        assert route_map_guidance(cfg) == ""


def test_proven_cells_slot(monkeypatch):
    monkeypatch.setattr(lead_slim, "PROVEN_CELLS", (("read-only audit", "codex"),))
    text = route_map_guidance({"lead": {"route_map": True}})
    assert "read-only audit -> codex" in text and "none yet" not in text


def cli(args, cwd, env, data=None):
    return subprocess.run([sys.executable, str(ROOT / "ccx.py"), *args], cwd=cwd, env=env,
                          input=json.dumps(data) if data is not None else None,
                          capture_output=True, text=True, encoding="utf-8", timeout=30)


def test_turn_hook_once_when_on_and_identical_when_off(tmp_path):
    env = {**os.environ, "CCX_NO_LOCATE": "1", "CCX_NO_QUOTA_PROBE": "1"}
    off = cli(["turn", "--as", "claude"], tmp_path, env, {"cwd": str(tmp_path)})
    assert off.returncode == 0, off.stdout + off.stderr
    assert cli(["config", "set", "lead.route_map", "true"], tmp_path, env).returncode == 0
    text = route_map_guidance(load_config(Paths(Path(env["CCX_HUB"]))))
    on = cli(["turn", "--as", "claude"], tmp_path, env, {"cwd": str(tmp_path)})
    assert on.returncode == 0 and on.stdout.count(text) == 1
    sub = cli(["turn", "--as", "claude"], tmp_path, {**env, "CCX_ROLE": "subagent"}, {"cwd": str(tmp_path)})
    assert sub.returncode == 0 and text not in sub.stdout
    dep = cli(["turn", "--as", "claude"], tmp_path, {**env, "CCX_DEPTH": "1"}, {"cwd": str(tmp_path)})
    assert dep.returncode == 0 and text not in dep.stdout
    assert cli(["config", "set", "lead.slim_context", "true"], tmp_path, env).returncode == 0
    mini = cli(["turn", "--as", "claude"], tmp_path, env, {"cwd": str(tmp_path)})
    assert mini.returncode == 0 and text not in mini.stdout
    assert cli(["config", "set", "lead.slim_context", "false"], tmp_path, env).returncode == 0
    assert cli(["config", "set", "lead.route_map", "false"], tmp_path, env).returncode == 0
    again = cli(["turn", "--as", "claude"], tmp_path, env, {"cwd": str(tmp_path)})
    assert again.returncode == 0 and again.stdout == off.stdout
