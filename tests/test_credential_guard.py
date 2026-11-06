"""Credential guard regression checks use only temporary homes and fake CLIs."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from ccx.credential_guard import protect, protected_dirs
from ccx.runners import Invocation


@pytest.fixture
def launch(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    inv = Invocation(["fake", "--settings", json.dumps({"permissions": {"deny": ["Bash(rm *)"]},
                                                       "ultracode": False})], "task", tmp_path)
    return inv, {"security": {"credential_guard": True}}, dict(os.environ)


def test_disabled_preserves_everything(launch, capsys):
    inv, _, env = launch
    before = list(inv.argv)
    assert protect("claude", inv, {}, inv.cwd, env) is None
    assert inv.argv == before and not capsys.readouterr().err


def test_claude_denies_credentials_without_reading_contents_or_listing(launch, monkeypatch):
    inv, cfg, env = launch
    cfg["security"]["credential_dirs"] = ["private tokens"]
    # Content reads/listings are forbidden; metadata-only resolve is permitted.
    def forbidden(*args, **kw):
        raise AssertionError("must not inspect credential directories")
    for method in ("iterdir", "glob", "read_text", "read_bytes", "open"):
        monkeypatch.setattr(Path, method, forbidden)
    result = protect("claude", inv, cfg, inv.cwd, env)
    data = json.loads(inv.argv[-1])
    rules = data["permissions"]["deny"]
    assert rules[0] == "Bash(rm *)" and data["ultracode"] is False
    assert any("/.codex/auth*)" in r for r in rules)
    assert any("/.codex/*.sqlite*)" in r for r in rules)
    assert any("/.claude/.credentials.json)" in r for r in rules)
    assert any("/.claude/auth*)" in r for r in rules)
    assert not any(r.endswith(("/.claude/**)", "/.codex/**)", "/.claude)", "/.codex)")) for r in rules)
    assert any("eval-codex-home/**)" in r for r in rules)
    assert any("/private tokens/**)" in r for r in rules)
    assert any(r.startswith("Bash(*") and ".credentials.json" in r for r in rules)
    assert result == {"status": "Unknown", "mechanism": "claude-permissions-deny", "rules_added": True}


def test_effective_child_and_original_home_credentials_and_worktree_are_protected(launch):
    inv, cfg, env = launch
    env["CODEX_HOME"] = str(inv.cwd / "child-codex")
    project = inv.cwd / "project"
    paths = protected_dirs(project, inv.cwd, env, [])
    expected = [str(Path(os.environ["CODEX_HOME"]) / "auth*"),
                str(Path(os.environ["CODEX_HOME"]) / "*.sqlite*"),
                str(Path(env["CODEX_HOME"]) / "auth*"), str(Path(env["CODEX_HOME"]) / "*.sqlite*"),
                str(Path(os.environ["CLAUDE_CONFIG_DIR"]) / ".credentials.json"),
                str(Path(os.environ["CLAUDE_CONFIG_DIR"]) / "auth*"),
                str(project / ".ccx" / "eval-codex-home"), str(inv.cwd / ".ccx" / "eval-codex-home")]
    assert all(p.replace("\\", "/") in paths for p in expected)
    assert all(p.replace("\\", "/") not in paths for p in
               (os.environ["CODEX_HOME"], env["CODEX_HOME"], os.environ["CLAUDE_CONFIG_DIR"]))
    assert str(project.parent / ".ccx" / "eval-codex-home").replace("\\", "/") in paths


@pytest.mark.parametrize("cli", ["codex", "dsh", "gemini"])
def test_unsupported_warns_before_launch_without_claiming_isolation(launch, capsys, cli):
    inv, cfg, env = launch
    before = list(inv.argv)
    assert protect(cli, inv, cfg, inv.cwd, env)["status"] == "Unknown"
    assert inv.argv == before
    assert "Unknown" in capsys.readouterr().err


@pytest.mark.parametrize("value", ["yes", 1, None])
def test_invalid_switch_is_not_silently_disabled(launch, value):
    inv, cfg, env = launch
    cfg["security"]["credential_guard"] = value
    with pytest.raises(ValueError, match="must be true or false"):
        protect("claude", inv, cfg, inv.cwd, env)


def test_settings_file_and_bypass_fail_closed(launch):
    inv, cfg, env = launch
    inv.argv[-1] = "unreadable-settings.json"
    with pytest.raises(ValueError, match="inline"):
        protect("claude", inv, cfg, inv.cwd, env)
    inv.argv += ["--permission-mode", "bypassPermissions"]
    with pytest.raises(ValueError, match="bypass"):
        protect("claude", inv, cfg, inv.cwd, env)


@pytest.mark.parametrize("via", ["equals", "settings"])
def test_other_permission_bypass_spellings_fail_closed(launch, via):
    inv, cfg, env = launch
    if via == "equals":
        inv.argv += ["--permission-mode=bypassPermissions"]
    else:
        data = json.loads(inv.argv[-1])
        data["permissions"]["defaultMode"] = "bypassPermissions"
        inv.argv[-1] = json.dumps(data)
    with pytest.raises(ValueError, match="bypass"):
        protect("claude", inv, cfg, inv.cwd, env)


@pytest.mark.parametrize("cli", ["claude", "codex"])
def test_run_command_from_outside_repo_applies_guard(tmp_path, monkeypatch, cli):
    root = Path(__file__).resolve().parents[1]
    home = tmp_path / "home"
    home.mkdir()
    project = tmp_path / "project"
    project.mkdir()
    hub = Path(os.environ["CCX_HUB"])
    from ccx.config import Paths
    Paths(hub).state.mkdir(parents=True, exist_ok=True)
    Paths(hub).user_tiers.write_text('[security]\ncredential_guard = true\n', encoding="utf-8")
    brief = tmp_path / "brief.md"
    brief.write_text("Return done", encoding="utf-8")
    log = tmp_path / "fake.jsonl"
    inherited = {k: v for k, v in os.environ.items() if not k.startswith("FAKE_") and
                 k not in ("CCX_CLAUDE_SETTINGS", "CCX_CLAUDE_SETTING_SOURCES", "CCX_CODEX_ISOLATE")}
    env = {**inherited, "HOME": str(home), "USERPROFILE": str(home), "FAKE_LOG": str(log),
           "CCX_NO_QUOTA_PROBE": "1", "CCX_NO_BENCH_REFRESH": "1",
           "CCX_CLAUDE_BIN": str(root / "tests/fakes/fake_claude.py"),
           "CCX_CODEX_BIN": str(root / "tests/fakes/fake_codex.py")}
    result = subprocess.run([sys.executable, str(root / "ccx.py"), "run", "--to", cli,
                             "--brief-file", str(brief), "--cwd", str(project), "--mode", "read",
                             "--model", "haiku" if cli == "claude" else "gpt-6-luna", "--effort", "low",
                             "--review", "off", "--no-escalate", "--no-fallback"], cwd=tmp_path, env=env,
                            capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "credential guard" in result.stderr
    records = list((hub / "ccx/runs").glob("*/run.json"))
    assert len(records) == 1
    record = json.loads(records[0].read_text(encoding="utf-8"))
    assert record["credential_guard"]["mechanism"] == ("claude-permissions-deny" if cli == "claude" else "unverified")
    calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    argv = next(call["argv"] for call in calls if call["agent"] == cli and
                ("-p" in call["argv"] if cli == "claude" else "exec" in call["argv"]))
    if cli == "claude":
        rules = json.loads(argv[argv.index("--settings") + 1])["permissions"]["deny"]
        assert any("eval-codex-home/**)" in rule for rule in rules)
        assert any(rule.startswith("Bash(*") for rule in rules)
    else:
        assert 'sandbox_mode="read-only"' in argv
