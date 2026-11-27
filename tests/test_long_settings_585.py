"""#585: on Windows a command line ends at 32767 characters. A unit with ~370 forbidden folders put its deny rules
into the claude `--settings` JSON on the command line and every sub-agent died with `[WinError 206]`. Fake CLIs only."""
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

import ccx.runners  # noqa: F401  (import order: runners loads the adapters)
from ccx.agents.claude import claude_invocation, SETTINGS_INLINE_MAX
from ccx.credential_guard import protect
from ccx.runners import Invocation, execute
from ccx.delegate import env_failure

FAKES = Path(__file__).parent / "fakes"
LIMIT = 30000        # a safe margin under Windows' 32767


def _deny(n=400):
    return [f"Read(//d/some/very/long/forbidden/folder/number-{i:04d}/{'x' * 40}/**)" for i in range(n)]


@pytest.fixture
def big(monkeypatch, tmp_path):
    monkeypatch.setenv("CCX_CLAUDE_BIN", str(FAKES / "fake_claude.py"))
    for k in ("CCX_CLAUDE_SETTING_SOURCES", "CCX_CLAUDE_NO_SKILLS"):
        monkeypatch.delenv(k, raising=False)
    f = tmp_path / "unit-settings-585.json"
    f.write_text(json.dumps({"permissions": {"deny": _deny()}, "disableAllHooks": True}), encoding="utf-8")
    monkeypatch.setenv("CCX_CLAUDE_SETTINGS", str(f))
    return dict(model="m", effort="low", perm=[], cwd=tmp_path, prompt="x", run_dir=tmp_path)


def _cmd_units(argv):
    return len(subprocess.list2cmdline(argv).encode("utf-16-le")) // 2


def test_many_forbidden_paths_stay_off_the_command_line(big, tmp_path):
    inv = claude_invocation(**big)
    assert _cmd_units(inv.argv) < LIMIT
    path = Path(inv.argv[inv.argv.index("--settings") + 1])
    s = json.loads(path.read_text(encoding="utf-8"))          # the rules are all there, in the file
    deny = s["permissions"]["deny"]
    assert deny[:len(_deny())] == _deny() and s["ultracode"] is False and s["disableAllHooks"] is True
    assert any(r.startswith("Edit(") and r.endswith("claude-settings.json)") for r in deny)   # it denies itself
    assert any(r.startswith("Read(") for r in deny[len(_deny()):]) and "Bash(*claude-settings.json*)" in deny


def test_a_relative_run_dir_gives_an_absolute_settings_path(big, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    inv = claude_invocation(**{**big, "run_dir": Path("runs") / "r"})
    assert Path(inv.argv[inv.argv.index("--settings") + 1]).is_absolute()


def test_a_stale_file_goes_when_the_settings_are_short_again(big, tmp_path, monkeypatch):
    claude_invocation(**big)
    assert (tmp_path / "claude-settings.json").exists()
    monkeypatch.delenv("CCX_CLAUDE_SETTINGS")
    claude_invocation(**big)
    assert not (tmp_path / "claude-settings.json").exists()


def test_small_settings_stay_inline(monkeypatch, tmp_path):
    monkeypatch.setenv("CCX_CLAUDE_BIN", str(FAKES / "fake_claude.py"))
    monkeypatch.delenv("CCX_CLAUDE_SETTINGS", raising=False)
    argv = claude_invocation(model="m", effort="low", perm=[], cwd=tmp_path, prompt="x", run_dir=tmp_path).argv
    assert json.loads(argv[argv.index("--settings") + 1])["ultracode"] is False
    assert SETTINGS_INLINE_MAX < LIMIT


def test_credential_guard_works_on_a_settings_file(big, tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    inv = claude_invocation(**big)
    got = protect("claude", inv, {"security": {"credential_guard": True}}, inv.cwd, dict(os.environ))
    assert got and got["mechanism"] == "claude-permissions-deny"
    assert _cmd_units(inv.argv) < LIMIT
    s = json.loads(Path(inv.argv[inv.argv.index("--settings") + 1]).read_text(encoding="utf-8"))
    assert set(_deny()) <= set(s["permissions"]["deny"])           # the caller's rules kept
    assert any(r.startswith("Bash(*") for r in s["permissions"]["deny"])   # the guard's rules added


def test_a_settings_file_that_is_not_ccxs_own_is_refused_by_the_guard(tmp_path):
    other = tmp_path / "other.json"
    other.write_text("{}", encoding="utf-8")
    inv = Invocation(["fake", "--settings", str(other)], "x", tmp_path)
    with pytest.raises(ValueError):
        protect("claude", inv, {"security": {"credential_guard": True}}, tmp_path, dict(os.environ))


@pytest.mark.skipif(sys.platform != "win32", reason="a text file as the binary: WinError 193 only on Windows")
def test_a_launch_error_ends_the_run_as_env_without_climbing(tmp_path):
    """End to end: ccx run with a binary Windows cannot start -> kind env, needs_lead, one attempt only."""
    root = Path(__file__).resolve().parent.parent
    (tmp_path / "bin.txt").write_text("not a program", encoding="utf-8")
    (tmp_path / "brief.md").write_text("say ok", encoding="utf-8")
    proj = tmp_path / "proj"
    proj.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=proj, check=True)
    env = {**os.environ, "CCX_HUB": str(tmp_path / "hub"), "CCX_CLAUDE_BIN": str(tmp_path / "bin.txt"),
           "CCX_NO_QUOTA_PROBE": "1", "CCX_NO_BENCH_REFRESH": "1"}
    r = subprocess.run([sys.executable, str(root / "ccx.py"), "run", "--to", "claude", "--brief-file",
                        str(tmp_path / "brief.md"), "--cwd", str(proj), "--mode", "read", "--model", "haiku",
                        "--effort", "low", "--review", "off"], cwd=tmp_path, env=env, capture_output=True,
                       text=True, encoding="utf-8", timeout=90)
    out = json.loads(r.stdout[r.stdout.index("{"):])
    assert out["kind"] == "env" and "ccx launch failed" in out["hint"] and "needs_lead" in out
    rec = json.loads(next((tmp_path / "hub").glob("ccx/runs/*/run.json")).read_text(encoding="utf-8"))
    assert len(rec["attempts"]) == 1 and rec["attempts"][0]["kind"] == "env"      # no climb, no retry


def test_the_guard_restores_argv_when_the_rules_do_not_fit(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setattr("ccx.credential_guard.MAX_COMMAND_CHARS", 50)
    inv = Invocation(["fake", "--settings", json.dumps({"permissions": {"deny": []}})], "x", tmp_path)
    before = list(inv.argv)
    with pytest.raises(ValueError):
        protect("claude", inv, {"security": {"credential_guard": True}}, tmp_path, dict(os.environ))
    assert inv.argv == before and inv.settings_file is None


def test_a_process_that_cannot_start_is_a_start_error_not_an_answer(tmp_path):
    inv = Invocation(["fake"], "x", tmp_path)
    with mock.patch("subprocess.Popen", side_effect=OSError(206, "The filename or extension is too long")):
        oc, out, err = execute("claude", inv, 30, dict(os.environ))
    assert not oc.ok and oc.kind == "error" and oc.result is None
    assert "could not start claude" in oc.error and "206" in oc.error
    why = env_failure(None, oc.ok, oc.kind, err, oc.error)         # delegate stops (kind env), no climb, no retry
    assert why and "could not start claude" in why
