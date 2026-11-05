"""Relay-only conservative classifier. Codex quota samples below are synthetic."""
import json
from pathlib import Path

import pytest

from ccx.quota_signals import identify

DATA = Path(__file__).parent / "data" / "real_signals"


def test_captured_claude_events():
    rows = [json.loads(line) for line in (DATA / "claude_rate_limit_20261031.jsonl").read_text(encoding="utf-8").splitlines()
            if line and not line.startswith("#")]
    assert len(rows) == 3
    assert all(identify(row)["kind"] == "quota" for row in rows)


@pytest.mark.parametrize("sample", [
    "429 Too Many Requests", "network error 429 quota", "401 usage limit reached", "quota",
    {"type": "user", "message": "usage limit reached"},
    {"type": "assistant", "message": "usage limit reached"},
    {"type": "item.completed", "item": {"type": "command_execution", "output": "usage limit reached"}},
    {"type": "error", "message": "429 Too Many Requests"},
    {"type": "error", "status": 401, "message": "usage limit reached"},
    {"type": "error", "code": "server_error", "message": "usage limit reached"},
    {"type": "error", "error": {"code": "server_error", "message": "usage limit reached"}},
    {"type": "rate_limit_event", "rate_limit_info": "malformed"},
    {"type": "error", "error": {"code": "authentication_failed", "message": "usage limit reached"}},
    {"type": "error", "error": {"code": "network_error", "message": "usage limit reached"}},
    {"type": "rate_limit_event", "rate_limit_info": {"status": "allowed", "rateLimitType": "five_hour"}},
    {"type": "rate_limit_event", "rate_limit_info": {"status": "rejected"}},
    {"hook_event_name": "StopFailure", "error": "authentication_failed", "error_details": "429"},
])
def test_negative_controls(sample):
    assert identify(sample)["kind"] != "quota"


def test_synthetic_codex_and_structured_priority():
    assert identify({"type": "turn.failed", "error": {"code": "usage_limit_reached"}})["kind"] == "quota"
    assert identify({"type": "error", "message": "429 Too Many Requests: usage limit reached"})["kind"] == "quota"
    assert identify('{"type":"error","error":{"code":"authentication_failed"}}\nusage limit reached')["kind"] == "auth"


def test_probe_readings_are_not_refusals():
    for name in ("quota_refresh_20261101.jsonl", "claude_probe_readings_20261101.jsonl"):
        for line in (DATA / name).read_text(encoding="utf-8").splitlines():
            if line and not line.startswith("#"):
                assert identify(json.loads(line))["kind"] != "quota"
