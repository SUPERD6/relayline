"""Review regressions: temporary credential stand-ins only, never real CLI homes."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from ccx.credential_guard import MAX_COMMAND_CHARS, MAX_SETTINGS_CHARS, _rules, protect, protected_dirs
from ccx.runners import Invocation


@pytest.fixture
def guarded(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    for key, path in (("HOME", home), ("USERPROFILE", home),
                      ("CODEX_HOME", tmp_path / "codex"), ("CLAUDE_CONFIG_DIR", tmp_path / "claude")):
        monkeypatch.setenv(key, str(path))
    inv = Invocation(["fake", "--settings", '{"permissions":{"deny":["Bash(rm *)"]}}'], "task", tmp_path)
    return inv, {"security": {"credential_guard": True}}, dict(os.environ)


def test_only_credential_targets_are_denied_and_normal_context_stays_readable(guarded):
    inv, cfg, env = guarded
    result = protect("claude", inv, cfg, inv.cwd, env)
    rules = json.loads(inv.argv[-1])["permissions"]["deny"]
    assert rules[0] == "Bash(rm *)"
    assert any("/.claude/.credentials.json)" in r for r in rules)
    assert any("/.claude/auth*)" in r for r in rules)
    assert any("/.codex/auth*)" in r for r in rules)
    assert any("/*.sqlite*)" in r for r in rules)
    assert any("eval-codex-home/**)" in r for r in rules)
    assert not any(r.endswith(("/.claude)", "/.claude/**)", "/.codex)", "/.codex/**)")) for r in rules)
    # No blanket shell home or variable rule may block skills/memory/tool results.
    assert "Bash(*$CODEX_HOME*)" not in rules
    assert "Bash(*$CLAUDE_CONFIG_DIR*)" not in rules
    assert "Bash(*~/.claude*)" not in rules
    assert not any("/skills" in r or "/projects" in r or "/tool-results" in r for r in rules)
    assert result["rules_added"] is True and result["status"] == "Unknown"


def test_windows_literals_cover_git_bash_and_common_case_spellings():
    # Literal expectations from Claude's official permissions docs, not a
    # reimplementation of the producer's Windows normalization formula.
    rules = _rules("C:/Users/Example/.claude/.credentials.json")
    assert "Read(//c/Users/Example/.claude/.credentials.json)" in rules
    assert "Bash(*C:/Users/Example/.claude/.credentials.json*)" in rules
    assert "Bash(*C:\\Users\\Example\\.claude\\.credentials.json*)" in rules
    assert "Bash(*/c/Users/Example/.claude/.credentials.json*)" in rules
    assert "Bash(*//c/Users/Example/.claude/.credentials.json*)" in rules
    assert "Bash(*/c/users/example/.claude/.credentials.json*)" in rules
    assert "Bash(*//C/USERS/EXAMPLE/.CLAUDE/.CREDENTIALS.JSON*)" in rules


def test_relative_homes_use_task_cwd_instead_of_parent_process_cwd(guarded, monkeypatch, tmp_path):
    inv, _, env = guarded
    task = tmp_path / "task"
    task.mkdir()
    child = task / "worker"
    child.mkdir()
    monkeypatch.setenv("CODEX_HOME", "original-codex")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", "original-claude")
    env.update(CODEX_HOME="worker-codex", CLAUDE_CONFIG_DIR="worker-claude")
    paths = protected_dirs(task, child, env, [])
    assert str(task / "original-codex" / "auth*").replace("\\", "/") in paths
    assert str(child / "worker-codex" / "*.sqlite*").replace("\\", "/") in paths
    assert str(task / "original-claude" / ".credentials.json").replace("\\", "/") in paths
    assert str(child / "worker-claude" / ".credentials.json").replace("\\", "/") in paths


def test_resolved_alias_added_without_opening_or_listing(guarded, monkeypatch):
    inv, _, env = guarded
    alias = inv.cwd / "temporary-alias"
    target = inv.cwd / "temporary-real"
    env["CODEX_HOME"] = str(alias)
    original = Path.resolve
    # Deterministic stand-in for a Windows junction / 8.3 alias. No privileges or
    # real home inspection required, and real filesystem resolution is not claimed.
    def resolve(path, strict=False):
        return target if path == alias else original(path, strict=strict)
    monkeypatch.setattr(Path, "resolve", resolve)
    def forbidden(*a, **kw):
        raise AssertionError("credential contents and listings must never be read")
    for name in ("open", "read_text", "read_bytes", "iterdir", "glob"):
        monkeypatch.setattr(Path, name, forbidden)
    paths = protected_dirs(inv.cwd, inv.cwd, env, [])
    assert str(alias / "auth*").replace("\\", "/") in paths
    assert str(target / "auth*").replace("\\", "/") in paths


def test_large_rule_list_is_rejected_before_mutating_launch(guarded):
    inv, cfg, env = guarded
    cfg["security"]["credential_dirs"] = ["extra/" + "x" * 160 + str(i) for i in range(200)]
    before = list(inv.argv)
    with pytest.raises(ValueError, match="rule length"):
        protect("claude", inv, cfg, inv.cwd, env)
    assert inv.argv == before


def test_regular_guard_fits_launch_length_limit(guarded):
    inv, cfg, env = guarded
    protect("claude", inv, cfg, inv.cwd, env)
    assert len(inv.argv[-1]) <= MAX_SETTINGS_CHARS
    assert len(subprocess.list2cmdline(inv.argv).encode("utf-16-le")) // 2 <= MAX_COMMAND_CHARS


def test_invalid_guard_config_has_clear_error_and_never_starts_cli(tmp_path):
    from ccx.config import Paths
    root = Path(__file__).resolve().parents[1]
    hub = Paths(Path(os.environ["CCX_HUB"]))
    hub.state.mkdir(parents=True, exist_ok=True)
    hub.user_tiers.write_text('[security]\ncredential_guard = "invalid"\n', encoding="utf-8")
    log = tmp_path / "fake.jsonl"
    env = {k: v for k, v in os.environ.items() if not k.startswith("FAKE_") and
           k not in ("CCX_CLAUDE_SETTINGS", "CCX_CLAUDE_SETTING_SOURCES", "CCX_CODEX_ISOLATE")}
    env.update(HOME=str(tmp_path), USERPROFILE=str(tmp_path), FAKE_LOG=str(log), CCX_NO_QUOTA_PROBE="1",
               CCX_NO_BENCH_REFRESH="1", CCX_CLAUDE_BIN=str(root / "tests/fakes/fake_claude.py"),
               CCX_CODEX_BIN=str(root / "tests/fakes/fake_codex.py"))
    result = subprocess.run([sys.executable, str(root / "ccx.py"), "run", "Return done", "--to", "claude",
                             "--mode", "read", "--model", "haiku", "--effort", "low", "--review", "off",
                             "--no-escalate", "--no-fallback"], cwd=tmp_path, env=env, capture_output=True,
                            text=True, encoding="utf-8", timeout=60)
    assert result.returncode == 3
    assert "credential guard configuration" in result.stdout
    records = list(hub.runs.glob("*/run.json"))
    assert len(records) == 1
    record = json.loads(records[0].read_text(encoding="utf-8"))
    assert record["kind"] == "error" and record["state"] == "finished"
    assert "must be true or false" in record["error"]
    assert record["attempts"] == [] and "current" not in record
    calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []
    assert not any("-p" in c["argv"] or "exec" in c["argv"] for c in calls)
