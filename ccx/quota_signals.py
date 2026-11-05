"""Conservative relay-only quota evidence; legacy verdicts remain unchanged.

Claude fixtures are captured CLI events. Codex quota coverage is synthetic.
Ordinary model/tool prose, HTTP 429 alone, auth and transport errors are not quota.
"""
from __future__ import annotations

import json
import re


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
        if re.match(r"^(?:api error:\s*)?(?:429 too many requests:\s*)?usage limit (?:reached|exceeded)\b", low):
            return {"kind": "quota", "source": "explicit_usage_text"}
        return {"kind": "unknown"}

    event = value.get("type")
    error = value.get("error")
    code = error.get("code", error.get("type")) if isinstance(error, dict) else value.get("code", error)
    if code in ("authentication_failed", "authentication_error", "invalid_api_key", "unauthorized") or value.get("status") in (401, 403):
        return {"kind": "auth", "source": "structured_error"}
    if code in ("network_error", "connection_error", "timeout"):
        return {"kind": "network", "source": "structured_error"}
    protocol_error = event in ("error", "turn.failed", "result") or value.get("is_api_error_message") is True
    if protocol_error and (code == "usage_limit_reached" or value.get("api_error") == "usage_limit_reached"):
        return {"kind": "quota", "source": "usage_limit_reached"}
    if value.get("hook_event_name") == "StopFailure" and error == "rate_limit":
        return {"kind": "quota", "source": "StopFailure"}
    if event == "rate_limit_event":
        info = value.get("rate_limit_info") or {}
        if isinstance(info, dict) and info.get("status") == "rejected" and (info.get("rateLimitType") or info.get("resetsAt")):
            return {"kind": "quota", "source": "rate_limit_event", "resets_at": info.get("resetsAt")}
    if code is not None:
        return {"kind": "unknown"}  # explicit non-quota error type beats its free-form message
    # Only error envelopes may use the conservative text fallback, never assistant/tool/user prose.
    if event in ("error", "turn.failed"):
        message = error.get("message", "") if isinstance(error, dict) else value.get("message", "")
        return identify(message) if isinstance(message, str) else {"kind": "unknown"}
    return {"kind": "unknown"}
