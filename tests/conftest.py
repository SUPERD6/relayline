"""Every test gets its own hub, tool homes and user config under its own temp folder, whether or not it sets them
itself (tests built on test_ccx.Env set their own on top). A test that forgot to would otherwise read or write the
real ~/.ccx hub, ~/.codex, ~/.claude or ~/.dsh of the machine it runs on, and tests would share state with each
other. No test finds a real agent CLI on its own either (e.g. a desktop app's bundled dsh from the registry):
CCX_NO_LOCATE is set before any test, so the ccx processes the tests start inherit it."""
import os

import pytest

os.environ["CCX_NO_LOCATE"] = "1"


@pytest.fixture(autouse=True)
def _own_hub(tmp_path, monkeypatch):
    for var, sub in (("CCX_HUB", "hub"), ("CODEX_HOME", "codex-home"), ("CLAUDE_CONFIG_DIR", "claude-home"),
                     ("DSH_HOME", "dsh-home")):
        d = tmp_path / sub
        d.mkdir()
        monkeypatch.setenv(var, str(d))
    monkeypatch.setenv("CCX_CONFIG", str(tmp_path / "user-config.toml"))
    # sessions.archive = after_run would end most runs with a `codex archive` call; the tests that are about it
    # switch it back on (tests/test_archive_after_run.py)
    monkeypatch.setenv("CCX_NO_AUTO_ARCHIVE", "1")
    monkeypatch.setenv("CCX_DSH_DESKTOP", "closed")     # whether this machine's dsh desktop app is open is no input
    # a slow CI machine must not turn a hook test's output into nothing (L4); tests/test_hooks_skills.py sets its own
    monkeypatch.setenv("CCX_HOOK_TIMEOUT_S", "0")
    for var in ("CCX_DEPTH", "CCX_ROLE", "CCX_RUN_ID", "CCX_PARENT_RUN"):     # never inherit a live ccx run
        monkeypatch.delenv(var, raising=False)
    for var in ("CCX_LEAD", "DSH_SESSION_ID", "ANTHROPIC_BASE_URL", "CLAUDE_CODE_SIMPLE",   # nor a lead's identity
                "CLAUDE_CODE_MESSAGING_SOCKET", "CLAUDE_CODE_MESSAGING_TOKEN"):   # nor its inbox (ccx/wake.py)
        monkeypatch.delenv(var, raising=False)
    for var in [k for k in os.environ if k.endswith(("_API_KEY", "_AUTH_TOKEN"))]:
        # the machine's own provider keys (DEEPSEEK_API_KEY ...): a test sets the fake one it needs, and a key
        # that happens to be set must not change what a test sees ("missing key" passed only where none was set)
        monkeypatch.delenv(var, raising=False)
    yield
