"""Codex credential guard (#289): a permission profile with filesystem deny entries. Temporary homes and fakes only."""
import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

import ccx.delegate  # noqa: F401  (loads ccx.agents first; a bare ccx.agents.codex import is circular)
from ccx import credential_guard
from ccx.agents.codex import codex_invocation
from ccx.credential_guard import note_denials, observed_denials, protect, record_guard

ROOT = Path(__file__).resolve().parents[1]
PROFILE = "permissions.ccx-credential-guard="


@pytest.fixture
def codex(tmp_path, monkeypatch):
    home = tmp_path / "home"
    chome = tmp_path / "guard-codex-home"
    chome.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    for key in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(key, str(home))
    monkeypatch.setenv("CODEX_HOME", str(chome))
    monkeypatch.setenv("CCX_CODEX_BIN", str(ROOT / "tests/fakes/fake_codex.py"))   # never the real CLI (CI has none)
    monkeypatch.setattr(credential_guard, "IS_WINDOWS", False)   # Windows-only checks opt in per test
    work = tmp_path / "work"
    work.mkdir()
    (work / ".git").mkdir()                       # project config lookup stops at the repository root

    def build(mode="read", resume=None, cfg_extra=None):
        perm = ["-c", f'sandbox_mode="{"read-only" if mode == "read" else "workspace-write"}"']
        inv = codex_invocation(model="m", effort="low", perm=perm, cwd=work, prompt="p", run_dir=tmp_path,
                               resume_id=resume)
        cfg = {"security": {"credential_guard": True, **(cfg_extra or {})}}
        return inv, cfg, {**os.environ, "CODEX_HOME": str(chome)}
    return build, chome, work


def profile_of(argv):
    raw = next(x for x in argv if x.startswith(PROFILE))[len(PROFILE):]
    return tomllib.loads(f"v = {raw}")["v"]


@pytest.mark.parametrize("mode, base", [("read", ":read-only"), ("write", ":workspace")])
def test_profile_replaces_sandbox_mode_with_deny_entries(codex, mode, base, monkeypatch):
    monkeypatch.setattr(credential_guard, "IS_WINDOWS", True)
    build, chome, work = codex
    (chome / "config.toml").write_text('[windows]\nsandbox = "elevated"\n', encoding="utf-8")
    inv, cfg, env = build(mode, cfg_extra={"credential_dirs": ["secrets"]})
    guard = protect("codex", inv, cfg, work, env)
    assert guard == {"status": "Unknown", "mechanism": "codex-permission-profile", "rules_added": True,
                     "execpolicy_rules": "ignored", "windows_sandbox": "elevated"}
    assert inv.argv.count("--ignore-rules") == 1          # allow rules would run commands outside the sandbox
    assert not any(x.startswith("sandbox_mode=") for x in inv.argv)
    assert 'default_permissions="ccx-credential-guard"' in inv.argv
    prof = profile_of(inv.argv)                      # the value Codex parses is valid TOML
    assert prof["extends"] == base
    fs = prof["filesystem"]
    assert set(fs.values()) == {"deny"}
    c = str(chome).replace("\\", "/")
    assert f"{c}/auth*" in fs and f"{c}/*.sqlite*" in fs
    assert str(work / "secrets").replace("\\", "/") in fs
    assert any(p.endswith("/.ccx/eval-codex-home") for p in fs)
    assert not any(p.endswith(("/.codex", "/guard-codex-home")) for p in fs)   # whole homes stay readable
    assert inv.argv[-3:-1] == ["-C", str(work)] and inv.argv[-1] == "-"


def test_resume_gets_the_profile_too(codex):
    build, _, work = codex
    inv, cfg, env = build(resume="thread-1")
    protect("codex", inv, cfg, work, env)
    assert inv.argv[inv.argv.index("exec"):inv.argv.index("exec") + 3] == ["exec", "resume", "thread-1"]
    assert profile_of(inv.argv)["extends"] == ":read-only"


@pytest.mark.parametrize("extra, match", [
    (["--sandbox", "read-only"], "--sandbox"),
    (["--sandbox=danger-full-access"], "--sandbox"),
    (["-sdanger-full-access"], "-s"),
    (["--profile=x"], "--profile"),
    (["-pwork"], "-p"),
    (["--full-auto"], "--full-auto"),
    (["-c", 'profile="lead"'], "existing Codex permission"),
    (["-c", "profiles.lead.sandbox_mode=\"danger-full-access\""], "existing Codex permission"),
    (["-c", "windows={sandbox=\"unelevated\"}"], "whole"),
    (["-c", "sandbox_mode=[1]"], "sandbox_mode"),
    (["--dangerously-bypass-approvals-and-sandbox"], "bypass"),
    (["-p", "work"], "-p"),
    (["-c", 'default_permissions="mine"'], "existing Codex permission"),
    (["-c", "sandbox_workspace_write.network_access=true"], "existing Codex permission"),
    (["--config=sandbox_mode=read-only"], "separate"),
])
def test_uninspectable_or_bypassing_argv_fails_closed(codex, extra, match):
    build, _, work = codex
    inv, cfg, env = build()
    inv.argv[-1:-1] = extra                     # after ccx's own -c sandbox_mode: the last one wins
    before = list(inv.argv)
    with pytest.raises(ValueError, match=match):
        protect("codex", inv, cfg, work, env)
    assert inv.argv == before


def test_full_access_and_missing_sandbox_mode_fail_closed(codex):
    build, _, work = codex
    inv, cfg, env = build()
    i = inv.argv.index('sandbox_mode="read-only"')
    inv.argv[i] = 'sandbox_mode="danger-full-access"'
    with pytest.raises(ValueError, match="danger-full-access"):
        protect("codex", inv, cfg, work, env)
    del inv.argv[i - 1:i + 1]
    with pytest.raises(ValueError, match="sandbox_mode"):
        protect("codex", inv, cfg, work, env)


@pytest.mark.parametrize("where", ["home", "argv", "unset", "project"])
def test_unelevated_windows_sandbox_is_refused_before_launch(codex, monkeypatch, where):
    monkeypatch.setattr(credential_guard, "IS_WINDOWS", True)
    build, chome, work = codex
    inv, cfg, env = build()
    if where == "home":
        (chome / "config.toml").write_text('[windows]\nsandbox = "unelevated"\n', encoding="utf-8")
    elif where == "unset":
        pass                                                   # not measured: fails closed too
    elif where == "project":                                   # project config is layered over the user's
        (chome / "config.toml").write_text('[windows]\nsandbox = "elevated"\n', encoding="utf-8")
        (work / ".codex").mkdir()
        (work / ".codex" / "config.toml").write_text('[windows]\nsandbox = "unelevated"\n', encoding="utf-8")
    else:
        (chome / "config.toml").write_text('[windows]\nsandbox = "elevated"\n', encoding="utf-8")
        inv.argv[1:1] = ["-c", 'windows.sandbox="unelevated"']       # a later -c wins, as in Codex
    with pytest.raises(ValueError, match="elevated"):
        protect("codex", inv, cfg, work, env)


def test_unelevated_is_not_refused_off_windows(codex, monkeypatch):
    monkeypatch.setattr(credential_guard, "IS_WINDOWS", False)
    build, chome, work = codex
    (chome / "config.toml").write_text('[windows]\nsandbox = "unelevated"\n', encoding="utf-8")
    inv, cfg, env = build()
    assert "windows_sandbox" not in protect("codex", inv, cfg, work, env)


def test_elevated_backend_is_recorded(codex, monkeypatch):
    monkeypatch.setattr(credential_guard, "IS_WINDOWS", True)
    build, chome, work = codex
    (chome / "config.toml").write_text('[windows]\nsandbox = "elevated"\n', encoding="utf-8")
    inv, cfg, env = build()
    assert protect("codex", inv, cfg, work, env)["windows_sandbox"] == "elevated"


@pytest.mark.parametrize("where", ["home", "project", "profile"])
def test_config_sandbox_mode_is_kept_visible(codex, capsys, where):
    build, chome, work = codex
    text = 'sandbox_mode = "danger-full-access"\n'
    if where == "profile":
        text = 'profile = "x"\n[profiles.x]\nsandbox_mode = "read-only"\n'
    target = chome if where != "project" else work / ".codex"
    target.mkdir(exist_ok=True)
    (target / "config.toml").write_text(text, encoding="utf-8")
    inv, cfg, env = build()
    assert protect("codex", inv, cfg, work, env)["config_sets_sandbox_mode"] is True
    assert "sandbox_mode" in capsys.readouterr().err


def test_ignore_user_config_skips_the_home_file(codex):
    build, chome, work = codex
    (chome / "config.toml").write_text('sandbox_mode = "danger-full-access"\n', encoding="utf-8")
    inv, cfg, env = build()
    inv.argv[1:1] = ["--ignore-user-config"]
    assert "config_sets_sandbox_mode" not in protect("codex", inv, cfg, work, env)


def test_project_config_above_the_repository_is_not_read(codex, tmp_path):
    build, _, work = codex
    (tmp_path / ".codex").mkdir()
    (tmp_path / ".codex" / "config.toml").write_text("not = [valid toml", encoding="utf-8")
    inv, cfg, env = build()
    protect("codex", inv, cfg, work, env)                       # the unparseable file above .git is ignored
    (work / ".codex").mkdir()
    (work / ".codex" / "config.toml").write_text("not = [valid toml", encoding="utf-8")
    inv, cfg, env = build()
    with pytest.raises(ValueError, match="parse"):
        protect("codex", inv, cfg, work, env)


def test_overlong_profile_fails_before_launch(codex):
    build, _, work = codex
    inv, cfg, env = build(cfg_extra={"credential_dirs": [f"d{i}/" + "x" * 200 for i in range(200)]})
    before = list(inv.argv)
    with pytest.raises(ValueError, match="length"):
        protect("codex", inv, cfg, work, env)
    assert inv.argv == before


def _event(output, code):
    return json.dumps({"type": "item.completed", "item": {"type": "command_execution", "command": "x",
                                                          "aggregated_output": output, "exit_code": code}})


def test_observed_denials_count_refused_commands_only():
    stdout = "\n".join([_event("Get-Content : Access is denied.", 1), _event("cat: x: Permission denied", 1),
                        _event("Access is denied", 0), _event("not found", 1), "not json",
                        json.dumps({"type": "item.completed", "item": {"type": "agent_message",
                                                                       "text": "Access is denied"}})])
    assert observed_denials("codex", stdout, None) == {"access_denied_commands": 2}
    assert observed_denials("claude", "", 3) == {"refused_tool_calls": 3}
    assert observed_denials("claude", "", None) == {}
    assert observed_denials("gemini", stdout, None) == {}


def test_counts_are_run_totals_across_attempts():
    rec = {"attempts": []}
    for n, found in enumerate([{"access_denied_commands": 2}, {"access_denied_commands": 1}]):
        current = {"n": n, "agent": "codex", "cli": "codex", "model": "m"}
        guard = {"status": "Unknown", "mechanism": "codex-permission-profile", "rules_added": True}
        record_guard(rec, current, guard)
        note_denials(rec, guard, found)
        rec["attempts"].append({"agent": "codex", "model": "m", "credential_guard": guard})
    assert rec["credential_guard"]["access_denied_commands"] == 3
    assert [a["access_denied_commands"] for a in rec["credential_guard"]["attempts"]] == [2, 1]
    note_denials(rec, None, {"access_denied_commands": 9})          # guard off: nothing changes
    assert rec["credential_guard"]["access_denied_commands"] == 3


def test_run_records_the_profile_and_the_denied_read(tmp_path):
    """End to end through `ccx run` and the fake Codex: the profile reaches the CLI, the refusal reaches the receipt."""
    home = tmp_path / "home"
    home.mkdir()
    project = tmp_path / "project"
    project.mkdir()
    hub = Path(os.environ["CCX_HUB"])
    from ccx.config import Paths
    Paths(hub).state.mkdir(parents=True, exist_ok=True)
    Paths(hub).user_tiers.write_text('[security]\ncredential_guard = true\n', encoding="utf-8")
    brief = tmp_path / "brief.md"
    brief.write_text("Print .env", encoding="utf-8")
    (Path(os.environ["CODEX_HOME"]) / "config.toml").write_text('[windows]\nsandbox = "elevated"\n', encoding="utf-8")
    log = tmp_path / "fake.jsonl"
    inherited = {k: v for k, v in os.environ.items() if not k.startswith("FAKE_") and
                 k not in ("CCX_CLAUDE_SETTINGS", "CCX_CLAUDE_SETTING_SOURCES", "CCX_CODEX_ISOLATE")}
    env = {**inherited, "HOME": str(home), "USERPROFILE": str(home), "FAKE_LOG": str(log),
           "FAKE_DENIED_READ": "1", "CCX_NO_QUOTA_PROBE": "1", "CCX_NO_BENCH_REFRESH": "1",
           "CCX_CODEX_BIN": str(ROOT / "tests/fakes/fake_codex.py")}
    result = subprocess.run([sys.executable, str(ROOT / "ccx.py"), "run", "--to", "codex", "--brief-file", str(brief),
                             "--cwd", str(project), "--mode", "read", "--model", "gpt-6-luna", "--effort", "low",
                             "--review", "off", "--no-escalate", "--no-fallback"], cwd=tmp_path, env=env,
                            capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    record = json.loads(next((hub / "ccx/runs").glob("*/run.json")).read_text(encoding="utf-8"))
    assert record["credential_guard"]["mechanism"] == "codex-permission-profile"
    assert record["credential_guard"]["access_denied_commands"] == 1
    assert record["attempts"][0]["credential_guard"]["access_denied_commands"] == 1
    argv = next(c["argv"] for c in map(json.loads, log.read_text(encoding="utf-8").splitlines())
                if c.get("agent") == "codex" and "exec" in c.get("argv", []))
    assert profile_of(argv)["extends"] == ":read-only"
    assert not any(x.startswith("sandbox_mode=") for x in argv)


def test_project_elevated_over_user_unelevated_is_accepted(codex, monkeypatch):
    monkeypatch.setattr(credential_guard, "IS_WINDOWS", True)
    build, chome, work = codex
    (chome / "config.toml").write_text('[windows]\nsandbox = "unelevated"\n', encoding="utf-8")
    (work / ".codex").mkdir()
    (work / ".codex" / "config.toml").write_text('[windows]\nsandbox = "elevated"\n', encoding="utf-8")
    inv, cfg, env = build()
    assert protect("codex", inv, cfg, work, env)["windows_sandbox"] == "elevated"


@pytest.mark.parametrize("text", ['profile = ["x"]\n', 'windows = "x"\n', 'profiles = "x"\nprofile = "x"\n'])
def test_odd_config_types_are_configuration_errors(codex, text):
    build, chome, work = codex
    (chome / "config.toml").write_text(text, encoding="utf-8")
    inv, cfg, env = build()
    with pytest.raises(ValueError, match="unexpected"):
        protect("codex", inv, cfg, work, env)


def test_relative_codex_home_resolves_against_the_task_directory(codex):
    build, _, work = codex
    (work / "rel-home").mkdir()
    (work / "rel-home" / "config.toml").write_text('sandbox_mode = "read-only"\n', encoding="utf-8")
    inv, cfg, env = build()
    env["CODEX_HOME"] = "rel-home"
    assert protect("codex", inv, cfg, work, env)["config_sets_sandbox_mode"] is True


@pytest.mark.parametrize("bad", ["sec[1]", "a?b", "x{y}"])
def test_glob_characters_in_a_protected_path_fail_closed(codex, bad):
    build, _, work = codex
    inv, cfg, env = build(cfg_extra={"credential_dirs": [bad]})
    with pytest.raises(ValueError, match="glob"):
        protect("codex", inv, cfg, work, env)


def test_unusual_path_characters_still_give_valid_toml(codex):
    build, _, work = codex
    inv, cfg, env = build(cfg_extra={"credential_dirs": ['we"ird\\x 中文\x7fdel', "tab\there"]})
    protect("codex", inv, cfg, work, env)
    fs = profile_of(inv.argv)["filesystem"]
    assert any(p.endswith("中文\x7fdel") for p in fs) and any("tab\there" in p for p in fs)


def test_existing_ignore_rules_is_not_repeated(codex):
    build, _, work = codex
    inv, cfg, env = build()
    inv.argv[1:1] = ["--ignore-rules"]
    protect("codex", inv, cfg, work, env)
    assert inv.argv.count("--ignore-rules") == 1


def test_observed_denials_skip_items_that_are_not_objects():
    line = json.dumps({"type": "item.completed", "item": "command_execution"})
    assert observed_denials("codex", line, None) == {"access_denied_commands": 0}
