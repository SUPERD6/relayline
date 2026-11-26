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


REAL_CODEX_TEXT = ("You’ve hit your usage limit. Visit https://chatgpt.com/settings/usage to purchase more credits "
                   "or try again at Dec 2nd, 2026 8:09 AM.")


def test_codex_usage_limit_wording_from_the_cli_log_in_both_error_envelopes():
    # Wording captured from codex-cli 0.164.0's own log (2026-11-25); the exec --json envelope is not captured (#525).
    assert identify({"type": "error", "message": REAL_CODEX_TEXT})["kind"] == "quota"
    assert identify({"type": "turn.failed", "error": {"message": REAL_CODEX_TEXT}})["kind"] == "quota"
    stream = "\n".join(json.dumps(e) for e in ({"type": "turn.started"}, {"type": "error", "message": REAL_CODEX_TEXT},
                                              {"type": "turn.failed", "error": {"message": REAL_CODEX_TEXT}}))
    assert identify(stream)["kind"] == "quota"
    # the same sentence in ordinary assistant prose is not a refusal
    assert identify({"type": "item.completed", "item": {"type": "agent_message", "text": REAL_CODEX_TEXT}})["kind"] == "unknown"


def test_synthetic_codex_and_structured_priority():
    assert identify({"type": "turn.failed", "error": {"code": "usage_limit_reached"}})["kind"] == "quota"
    assert identify({"type": "error", "message": "429 Too Many Requests: usage limit reached"})["kind"] == "quota"
    assert identify('{"type":"error","error":{"code":"authentication_failed"}}\nusage limit reached')["kind"] == "auth"


def test_probe_readings_are_not_refusals():
    for name in ("quota_refresh_20261101.jsonl", "claude_probe_readings_20261101.jsonl"):
        for line in (DATA / name).read_text(encoding="utf-8").splitlines():
            if line and not line.startswith("#"):
                assert identify(json.loads(line))["kind"] != "quota"


@pytest.mark.parametrize("extra,expected", [
    ({}, "rate_limit_unconfirmed"),
    ({"error_details": "429 Too Many Requests"}, "rate_limit_unconfirmed"),
    ({"error_details": "usage limit reached"}, "quota"),
    ({"error_details": "You've hit your 5-hour limit · resets 1am (America/New_York)"}, "quota"),
    ({"rate_limit_info": {"status": "rejected", "rateLimitType": "five_hour"}}, "quota"),
    ({"rate_limit_info": {"status": "allowed", "rateLimitType": "five_hour"}}, "rate_limit_unconfirmed"),
    ({"rate_limit_info": {"status": "rejected", "resetsAt": 1234}}, "rate_limit_unconfirmed"),
    ({"rate_limit_info": {"rateLimitType": [], "unifiedWindows": 1}}, "rate_limit_unconfirmed"),
    ({"error_details": {"code": "billing_error", "message": "usage limit reached"}}, "rate_limit_unconfirmed"),
])
def test_hook_quota_requires_usage_evidence(extra, expected):
    # Hook samples are synthetic; the 5-hour wording matches the captured CLI fixture.
    assert identify({"hook_event_name": "StopFailure", "error": "rate_limit", **extra})["kind"] == expected


@pytest.mark.parametrize("info", [{"status": "rejected", "rateLimitType": "requests_per_minute"},
                                  {"status": "rejected", "resetsAt": 1234}])
def test_rate_limit_event_without_usage_window_remains_unconfirmed(info):
    assert identify({"type": "rate_limit_event", "rate_limit_info": info})["kind"] == "rate_limit_unconfirmed"
