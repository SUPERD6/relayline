"""Credential guard warnings must survive the lead's line-output preference."""
import json

import pytest

from ccx import leadview
from test_adapters import AdapterEnv
from test_ccx import FAKES
from test_leadview import PASSED


@pytest.mark.parametrize("guard_fields", [
    {"credential_guard": {"status": "Unknown", "mechanism": "unverified"}},
    {"credential_guard": {"status": "Fail"}},
    {"credential_guard_warnings": [{"attempt": 1, "agent": "codex", "message": "Unknown"}]},
])
def test_guard_attention_keeps_full_receipt(monkeypatch, guard_fields):
    monkeypatch.setenv("CCX_LEAD_VIEW", "line")
    receipt = {**PASSED, **guard_fields}
    rendered, one_line = leadview.render(receipt, {})
    assert one_line is False
    assert rendered == receipt
    # Direct line consumers also retain all guard evidence and warnings.
    for key, value in guard_fields.items():
        assert leadview.line(receipt)[key] == value


def test_disabled_line_receipt_bytes_match_legacy(monkeypatch):
    monkeypatch.setenv("CCX_LEAD_VIEW", "line")
    expected = {key: PASSED[key] for key in (
        "run_id", "agent", "model", "ok", "status", "summary", "files_changed", "diffstat")}
    expected.update(check=PASSED["check"], review={"verdict": "pass", "by": "claude:sonnet"},
                    view="line", recap=PASSED["recap"])
    rendered, one_line = leadview.render(PASSED, {})
    assert one_line is True
    assert leadview.dumps(rendered, one_line) == leadview.dumps(expected, True)


class TestGuardLeadOutput(AdapterEnv):
    def test_capacity_fallback_warning_reaches_lead_with_line_preference(self):
        self.env.update(CCX_LEAD_VIEW="line", HOME=str(self.work / "home"), USERPROFILE=str(self.work / "home"))
        self.env["CCX_CLAUDE_BIN"] = str(FAKES / "fake_claude_capacity.py")
        self.j("config", "set", "security.credential_guard", "true")
        result = self.ccx("run", "--from", "user", "--to", "claude", "--tier", "T1", "--new",
                          "--context", "off", "--no-ab", "--review", "off", "--no-escalate",
                          "--check", "python -c pass", "Read the parser")
        assert result.returncode == 0, result.stdout + result.stderr
        receipt = json.loads(result.stdout)
        assert receipt["credential_guard"]["status"] == "Unknown"
        warning = receipt["credential_guard_warnings"][1]
        assert warning["agent"] == "codex" and "Unknown" in warning["message"]
        assert "warnings" not in receipt
