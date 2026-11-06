"""Conservative relay-only quota evidence; legacy verdicts remain unchanged.

Claude fixtures are captured CLI events. Codex quota coverage is synthetic.
Ordinary model/tool prose, HTTP 429 alone, auth and transport errors are not quota.
"""
from __future__ import annotations

import json
import re


def _usage_window(info) -> bool:
    if not isinstance(info, dict):
        return False
    windows = {"five_hour", "seven_day", "daily", "weekly", "monthly"}
    window_type, unified = info.get("rateLimitType"), info.get("unifiedWindows")
    rejected = ("rejected", "exceeded", "blocked")
    return bool((isinstance(window_type, str) and window_type in windows and info.get("status") in rejected)
                or isinstance(unified, dict) and any(isinstance(window, dict) and window.get("status") in rejected
                    for name, window in unified.items() if name in windows))


def _hook_usage(value: dict) -> bool:
    details = value.get("error_details")
    info = value.get("rate_limit_info")
    if isinstance(details, dict):
        info = info or details.get("rate_limit_info")
        if details.get("code") == "usage_limit_reached":
            return True
        if details.get("code") in ("billing_error", "authentication_failed", "network_error"):
            return False
        details = details.get("message", "")
    if _usage_window(info):
        return True
    if isinstance(details, str):
        if identify(details)["kind"] == "quota":
            return True
        # Captured Claude wording is in tests/data/real_signals; hook delivery is not measured.
        return bool(re.match(r"^you['’]ve hit your (?:\d+[- ]hour|daily|weekly|monthly) (?:usage )?limit\b",
                             details.strip().lower()))
    return False


def identify(value: dict | str) -> dict:
    """Return evidence, never infer exhausted subscription quota from HTTP status alone."""
    if isinstance(value, str):
        rows = []
        for line in value.splitlines():
            try:
                item = json.loads(line)
            except ValueError:
                continue
            if isinstance(item, dict):
                rows.append(identify(item))
        # Protocol evidence takes precedence over human-readable wording.
        if rows:
            return next((r for r in rows if r["kind"] == "quota"),
                        next((r for r in rows if r["kind"] != "unknown"), {"kind": "unknown"}))
        low = value.strip().lower()
        if re.match(r"^(?:api error:\s*)?(?:401|403|authentication|unauthorized|network|connection|timeout)\b", low):
            return {"kind": "unknown"}
        if re.match(r"^(?:api error:\s*)?(?:429 too many requests:\s*)?(?:usage limit (?:reached|exceeded)\b|you['’]ve hit your usage limit\b)", low):
            return {"kind": "quota", "source": "explicit_usage_text"}
        return {"kind": "unknown"}

    event = value.get("type")
    error = value.get("error")
    code = error.get("code", error.get("type")) if isinstance(error, dict) else value.get("code", error)
    if code in ("authentication_failed", "authentication_error", "invalid_api_key", "unauthorized") or value.get("status") in (401, 403):
        return {"kind": "auth", "source": "structured_error"}
    if code in ("network_error", "connection_error", "timeout"):
        return {"kind": "network", "source": "structured_error"}
    if code == "billing_error":
        return {"kind": "billing", "source": "structured_error"}
    protocol_error = event in ("error", "turn.failed", "result") or value.get("is_api_error_message") is True
    if protocol_error and (code == "usage_limit_reached" or value.get("api_error") == "usage_limit_reached"):
        return {"kind": "quota", "source": "usage_limit_reached"}
    if value.get("hook_event_name") == "StopFailure" and error == "rate_limit":
        confirmed = _hook_usage(value)
        return {"kind": "quota" if confirmed else "rate_limit_unconfirmed", "source": "StopFailure",
                **({"usage_confirmed": True} if confirmed else {})}
    if event == "rate_limit_event":
        info = value.get("rate_limit_info") or {}
        if isinstance(info, dict) and info.get("status") == "rejected":
            confirmed = _usage_window(info)
            return {"kind": "quota" if confirmed else "rate_limit_unconfirmed",
                    "source": "rate_limit_event", "resets_at": info.get("resetsAt"),
                    **({"usage_confirmed": True} if confirmed else {})}
    if code is not None:
        return {"kind": "unknown"}  # explicit non-quota error type beats its free-form message
    # Only error envelopes may use the conservative text fallback, never assistant/tool/user prose.
    if event in ("error", "turn.failed"):
        message = error.get("message", "") if isinstance(error, dict) else value.get("message", "")
        return identify(message) if isinstance(message, str) else {"kind": "unknown"}
    return {"kind": "unknown"}
