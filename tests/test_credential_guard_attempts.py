"""Per-attempt credential guard receipts, using fake CLI subprocesses only."""
import json

import pytest

from ccx import credential_guard
from ccx.delegate import compact
from test_adapters import AdapterEnv
from test_ccx import FAKES


class TestGuardAttempts(AdapterEnv):
    def run_switch(self, enabled):
        self.env.update(HOME=str(self.work / "home"), USERPROFILE=str(self.work / "home"))
        self.j("config", "set", "security.credential_guard", str(enabled).lower())
        self.env["CCX_CLAUDE_BIN"] = str(FAKES / "fake_claude_capacity.py")
        out = self.j("run", "--from", "user", "--to", "claude", "--tier", "T1", "--mode", "read",
                     "--new", "--context", "off", "--no-ab", "--review", "off", "--no-escalate",
                     "Read the parser")
        return out, self.rec(out["run_id"])

    def test_claude_capacity_to_codex_keeps_both_guards_and_warning(self):
        out, rec = self.run_switch(True)
        assert [(a["agent"], a["kind"]) for a in rec["attempts"]] == [
            ("claude", "capacity"), ("codex", "ok")]
        guards = [a["credential_guard"] for a in rec["attempts"]]
        assert guards == [
            {"status": "Unknown", "mechanism": "claude-permissions-deny", "rules_added": True},
            {"status": "Unknown", "mechanism": "unverified"}]
        assert rec["credential_guard"]["status"] == "Unknown"
        assert rec["credential_guard"]["mechanism"] == "unverified"
        assert "rules_added" not in rec["credential_guard"]
        assert rec["credential_guard"]["attempts"] == [
            {"n": n, "agent": a["agent"], "model": a["model"], **guards[n]}
            for n, a in enumerate(rec["attempts"])]
        warning = rec["credential_guard_warnings"][1]
        assert warning == {"attempt": 1, "agent": "codex", "message": credential_guard.launch_warning("codex")}
        assert "Unknown" in warning["message"]
        for receipt in (out, self.j("show", out["run_id"])):
            assert receipt["credential_guard"] == rec["credential_guard"]
            assert receipt["credential_guard_warnings"] == rec["credential_guard_warnings"]

    def test_disabled_switch_adds_no_receipt_fields(self):
        out, rec = self.run_switch(False)
        assert [a["agent"] for a in rec["attempts"]] == ["claude", "codex"]
        for item in (out, rec, *rec["attempts"]):
            assert "credential_guard" not in item and "warnings" not in item
            assert "credential_guard_warnings" not in item
        # Reapply the disabled recording path to an actual receipt. Both stored
        # JSON and compact receipt remain byte-for-byte identical, including key order.
        before = json.dumps(rec), json.dumps(compact(rec))
        credential_guard.record_guard(rec, rec["attempts"][-1], None)
        assert (json.dumps(rec), json.dumps(compact(rec))) == before


@pytest.mark.parametrize("statuses, expected", [
    (["Pass", "Unknown"], "Unknown"), (["Unknown", "Pass"], "Unknown"),
    (["Pass", "Fail", "Unknown"], "Fail"), (["Pass", "Pass"], "Pass")])
def test_top_level_keeps_weakest_status(statuses, expected):
    rec = {"attempts": []}
    for n, status in enumerate(statuses):
        current = {"n": n, "agent": "claude", "cli": "claude", "model": "fake"}
        credential_guard.record_guard(rec, current, {"status": status, "mechanism": "test"})
        rec["attempts"].append(current)
    assert rec["credential_guard"]["status"] == expected
    assert [a["status"] for a in rec["credential_guard"]["attempts"]] == statuses


def test_interrupted_attempt_retains_launch_guard(tmp_path, monkeypatch):
    from ccx import ledger, recover
    from ccx.config import Paths

    rec = {"run_id": "fake-run", "attempts": [], "current": {
        "n": 0, "agent": "codex", "cli": "codex", "model": "fake", "effort": "low"}}
    guard = {"status": "Unknown", "mechanism": "unverified"}
    credential_guard.record_guard(rec, rec["current"], guard)
    monkeypatch.setattr(ledger, "claim_final", lambda *args: True)
    monkeypatch.setattr(ledger, "load_run", lambda *args: rec)
    monkeypatch.setattr(ledger, "write_record", lambda *args: None)
    monkeypatch.setattr(ledger, "append", lambda *args: None)
    monkeypatch.setattr(recover, "partial_usage", lambda *args, **kw: ({}, None))
    recovered = recover.close_dead(Paths(tmp_path), "fake-run", "killed", "interrupted", "fake interruption", "run")
    assert recovered["attempts"][0]["credential_guard"] == guard
    assert recovered["credential_guard"]["attempts"][0]["status"] == "Unknown"
    assert "Unknown" in recovered["credential_guard_warnings"][0]["message"]
