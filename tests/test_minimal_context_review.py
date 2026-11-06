"""Review regressions for #287; conftest isolates all hubs and tool homes."""
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from ccx import ability, archive_worker, board, delegate, learn, memory, projects, sync, wake
from ccx.commands import board as board_commands
from ccx.commands.memory import cmd_mem
from ccx.config import Paths, set_setting

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def upkeep(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # never discover the shared main checkout's project state
    calls = []
    for module, name in ((delegate, "soft_verdicts"), (ability, "after_verdict"),
                         (archive_worker, "schedule"), (projects, "refresh_later"),
                         (learn, "refresh_benchmarks_later")):
        monkeypatch.setattr(module, name, lambda *args, name=name: calls.append(name))
    monkeypatch.delenv("CCX_NO_BENCH_REFRESH", raising=False)
    return calls


@pytest.mark.parametrize("minimal", [False, True])
def test_quiet_upkeep_runs_in_both_startup_modes(minimal, upkeep, capsys):
    p = Paths(Path(os.environ["CCX_HUB"]))
    set_setting(p, "lead.slim_context", str(minimal).lower())
    assert cmd_mem(SimpleNamespace(mem_cmd="delta", as_="claude", peek=False, full=False)) == 0
    assert upkeep == ["soft_verdicts", "after_verdict", "schedule", "refresh_later", "refresh_benchmarks_later"]
    if minimal:
        assert capsys.readouterr().out == ""


def test_minimal_peek_and_subagent_keep_maintenance_guards(upkeep, monkeypatch, capsys):
    p = Paths(Path(os.environ["CCX_HUB"]))
    set_setting(p, "lead.slim_context", "true")
    args = SimpleNamespace(mem_cmd="delta", as_="claude", peek=True, full=False)
    assert cmd_mem(args) == 0 and upkeep == []
    args.peek = False
    monkeypatch.setenv("CCX_ROLE", "subagent")
    assert cmd_mem(args) == 0 and upkeep == []
    assert capsys.readouterr().out == ""


def test_minimal_maintenance_keeps_failure_isolation_and_refresh_guard(upkeep, monkeypatch):
    p = Paths(Path(os.environ["CCX_HUB"]))
    set_setting(p, "lead.slim_context", "true")
    def broken(*args):
        upkeep.append("soft_failed")
        raise RuntimeError("fixture failure")
    monkeypatch.setattr(delegate, "soft_verdicts", broken)
    monkeypatch.setenv("CCX_NO_BENCH_REFRESH", "1")
    assert cmd_mem(SimpleNamespace(mem_cmd="delta", as_="claude", peek=False, full=False)) == 0
    assert upkeep == ["soft_failed", "schedule", "refresh_later"]


def test_minimal_turn_keeps_board_maintenance_and_completion_delivery(tmp_path, monkeypatch):
    monkeypatch.setattr(wake.time, "time", lambda: 1234567890.0)  # deterministic notice TTL
    p = Paths(Path(os.environ["CCX_HUB"]))
    set_setting(p, "lead.slim_context", "true")
    root = tmp_path / "project"
    (root / ".ccx").mkdir(parents=True)
    board.post(root, "codex", "claude", "unread board marker")
    calls = []
    monkeypatch.setattr(board_commands, "sync_in_background", lambda path: calls.append(path))
    # A human turn still reads the board to reset the conversation-loop guard.
    original_entries = board.entries
    def entries(path):
        calls.append("entries")
        return original_entries(path)
    monkeypatch.setattr(board, "entries", entries)
    monkeypatch.setattr(board, "turn_text", lambda *args: pytest.fail("must not consume hidden messages"))
    notice = wake.text("fixture-run", "finished successfully")
    wake._pending(p, "fixture-run", "claude", "fixture-session", str(root), notice)
    data = {"cwd": str(root), "session_id": "fixture-session", "prompt": "continue"}
    assert board_commands.turn_output("claude", data, 1) == notice
    assert calls == ["entries", root]
    assert board.read(root, "claude:fixture-session", advance=False)[0]["text"] == "unread board marker"
    assert json.loads((root / ".ccx" / "board.humans.json").read_text(encoding="utf-8"))["claude"] == 1
    assert board_commands.turn_output("claude", data, 1) == ""  # notice delivered once


@pytest.mark.parametrize("agent", ["claude", "codex"])
def test_startup_sync_and_external_hook_as_processes(tmp_path, monkeypatch, agent):
    p = Paths(Path(os.environ["CCX_HUB"]))
    monkeypatch.setenv("CCX_NO_BENCH_REFRESH", "1")
    def cli(*args):
        r = subprocess.run([sys.executable, str(ROOT / "ccx.py"), *args], cwd=tmp_path,
                           capture_output=True, text=True, encoding="utf-8", timeout=30, input="")
        assert r.returncode == 0, r.stdout + r.stderr
        return r.stdout
    memory.add(p, "unread-startup-marker", by="user")
    cli("sync", "--only", "memory", "--apply")
    homes = [("CLAUDE_CONFIG_DIR", "CLAUDE.md"), ("CODEX_HOME", "AGENTS.md")]
    original = {var: (Path(os.environ[var]) / name).read_bytes() for var, name in homes}
    baseline = cli("mem", "delta", "--as", agent, "--peek")
    cli("config", "set", "lead.slim_context", "true")
    cli("sync", "--only", "memory", "--apply")
    assert cli("mem", "delta", "--as", agent) == ""
    assert cli("mem", "delta", "--as", agent, "--full", "--peek") == baseline
    with open(p.state / "layout.toml", "w", encoding="utf-8", newline="") as fh:
        fh.write('[layout]\nsnapshot_mode = "external"\n')
    expected = sync.minimal_memory_block() + "\n"
    assert cli("mem", "delta", "--as", agent) == expected
    assert len(expected.splitlines()) == 2
    assert sync.ccx_command().rstrip() in expected and "--full" in expected
    assert cli("mem", "delta", "--as", agent, "--full", "--peek") == baseline
    cli("config", "set", "lead.slim_context", "false")
    with open(p.state / "layout.toml", "w", encoding="utf-8", newline="") as fh:
        fh.write('[layout]\nsnapshot_mode = "managed"\n')
    cli("sync", "--only", "memory", "--apply")
    for var, name in homes:
        assert (Path(os.environ[var]) / name).read_bytes() == original[var]
