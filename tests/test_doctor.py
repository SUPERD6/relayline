"""Readiness reuses local signals and cached doctor results without reading credentials."""
import json
import time
from pathlib import Path
from unittest import mock

import pytest

from ccx.agents import cache_login, others, readiness
from ccx.config import Paths, load_config
from ccx.workspace import canonical
from test_ccx import Env


@pytest.mark.parametrize("agent,filename", [("codex", "auth.json"), ("claude", ".credentials.json"),
                                           ("gemini", "oauth_creds.json")])
def test_readiness_checks_only_file_existence(tmp_path, monkeypatch, agent, filename):
    home = tmp_path / "tool-home"
    home.mkdir()
    monkeypatch.setattr("ccx.agents.get", lambda name: mock.Mock(home=lambda: home))
    monkeypatch.setattr("ccx.runners.find_bin", lambda name: "fake")
    credential = home / filename
    credential.write_text("must never read this", encoding="utf-8")
    original = Path.read_text
    def read(path, *args, **kwargs):
        assert canonical(path) != canonical(credential)
        return original(path, *args, **kwargs)
    p = Paths(tmp_path / "hub")
    with mock.patch.object(Path, "read_text", read), mock.patch("subprocess.run", side_effect=AssertionError):
        row = readiness(p, {}, [agent])[agent]
    assert row["ready"] and row["installed"] and row["logged_in"]
    assert json.loads((p.state / "agent-readiness.json").read_text(encoding="utf-8"))[agent]["ts"] > 0
    assert "must never read this" not in (p.state / "agent-readiness.json").read_text(encoding="utf-8")


def test_dsh_uses_existing_adapter_key_signal(tmp_path, monkeypatch):
    monkeypatch.setattr("ccx.runners.find_bin", lambda name: "fake")
    p = Paths(tmp_path / "hub")
    assert not readiness(p, {}, ["dsh"])["dsh"]["ready"]
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key-never-save")
    assert readiness(p, {}, ["dsh"])["dsh"]["ready"]
    assert "fake-key-never-save" not in (p.state / "agent-readiness.json").read_text(encoding="utf-8")


def test_readiness_cache_expires_at_quota_interval_and_tracks_home(tmp_path, monkeypatch):
    from ccx.config import codex_home
    monkeypatch.setattr("ccx.runners.find_bin", lambda name: "fake")
    p, cfg = Paths(tmp_path / "hub"), {"quota": {"auto_refresh_min": 1}}
    auth = codex_home() / "auth.json"
    auth.touch()
    assert readiness(p, cfg, ["codex"])["codex"]["ready"]
    auth.unlink()
    assert not readiness(p, cfg, ["codex"])["codex"]["ready"]
    with mock.patch("ccx.agents.time.time", return_value=time.time() + 61):
        assert not readiness(p, cfg, ["codex"])["codex"]["ready"]
    cache_login(p, "codex", True)
    assert readiness(p, cfg, ["codex"])["codex"]["ready"]
    home = tmp_path / "different-home"
    home.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(home))
    assert not readiness(p, cfg, ["codex"])["codex"]["ready"]


def test_cached_negative_login_and_missing_installation_override_files(tmp_path, monkeypatch):
    from ccx.config import codex_home
    monkeypatch.setattr("ccx.runners.find_bin", lambda name: "fake")
    p = Paths(tmp_path / "hub")
    (codex_home() / "auth.json").touch()
    cache_login(p, "codex", False)
    assert not readiness(p, {}, ["codex"])["codex"]["ready"]
    cache_login(p, "codex", True)
    monkeypatch.setattr("ccx.runners.find_bin", lambda name: None)
    assert readiness(p, {}, ["codex"])["codex"]["why"] == "codex: not installed"


def test_other_orders_ready_before_official_support_order(tmp_path, monkeypatch):
    from ccx.config import claude_home
    monkeypatch.setattr("ccx.runners.find_bin", lambda name: "fake")
    (claude_home() / ".credentials.json").touch()
    assert others("dsh", {})[:2] == ["claude", "codex"]
    assert others("dsh", {"routing": {"require_ready": False}})[:2] == ["codex", "claude"]


class TestDoctorLoginCache(Env):
    def test_doctor_caches_status_without_output_or_credentials(self):
        result = self.ccx("doctor", env={"FAKE_CLAUDE_AUTH": '{"loggedIn":false}',
                                        "FAKE_CODEX_LOGIN": "Logged in using ChatGPT"})
        self.assertIn("claude login", result.stdout)
        states = readiness(Paths(self.hub), load_config(Paths(self.hub)), ["claude", "codex"])
        self.assertFalse(states["claude"]["ready"])
        self.assertTrue(states["codex"]["ready"])
        self.assertEqual(states["codex"]["source"], "doctor")
        self.assertNotIn("ChatGPT", (Paths(self.hub).state / "agent-readiness.json").read_text(encoding="utf-8"))
