"""Issue #311: numeric status hints must not match inside identifiers or longer numbers."""
import json

import pytest

from ccx import quota, runners


@pytest.mark.parametrize("text", [
    "8c1b429c8b1a", "a401f3", "4290", "1429", "4010", "1401",
    "a429", "429z", "a401", "401z", "\u00e9429", "401\u00e9", "\u0130429", "\u0130401",
    "report8c1b429c8b1a.json", "resulta401f3.txt",
])
def test_embedded_numbers_are_not_status_hints(text):
    assert runners.classify(text) == "error"
    for cli in ("claude", "codex"):
        for stdout, stderr, error in ((text, "", None), ("", text, None), ("", "", text)):
            assert quota.stop_evidence(cli, stdout, stderr, error) == {"by": "unknown"}


@pytest.mark.parametrize("text, kind, hint", [
    ("HTTP 429", "quota", "429"),
    ("429 Too Many Requests", "quota", "429"),
    ("error 429:", "quota", "429"),
    ("(429)", "quota", "429"),
    ("429", "quota", "429"),
    ("_429_", "quota", "429"),
    ("status: 401", "auth", "401"),
    ("401", "auth", "401"),
    ("(401)", "auth", "401"),
])
def test_standalone_numbers_keep_classification_and_evidence(text, kind, hint):
    assert runners.classify(text) == kind
    for cli in ("claude", "codex"):
        for stdout, stderr, error in ((text, "", None), ("", text, None), ("", "", text)):
            evidence = quota.stop_evidence(cli, stdout, stderr, error)
            if kind == "quota":
                assert evidence == {"by": "hint", "hint": hint, "text": text}
            else:
                # stop_evidence records quota stops only, never authentication failures.
                assert evidence == {"by": "unknown"}


@pytest.mark.parametrize("parser", [runners.parse_claude, runners.parse_codex])
@pytest.mark.parametrize("text, kind, auth_problem", [
    ("file a401f3.txt failed", "error", False),
    ("request 1401 failed", "error", False),
    ("request 4010 failed", "error", False),
    ("file 8c1b429c8b1a.txt failed", "error", False),
    ("file \u0130401.txt failed", "error", False),
    ("status: 401", "auth", True),
    ("HTTP 429", "quota", False),
    ("Please LOGIN", "auth", True),
])
@pytest.mark.parametrize("source", ["stderr", "event"])
def test_parser_auth_flag_uses_the_same_boundaries(parser, text, kind, auth_problem, source):
    stdout, stderr = "", text
    if source == "event":
        stderr = ""
        if parser is runners.parse_claude:
            stdout = json.dumps({"type": "result", "is_error": True, "errors": [text]})
        else:
            stdout = json.dumps({"type": "error", "message": text})
    parsed = parser(stdout, stderr, 1, None)
    assert not parsed.ok
    assert parsed.kind == kind
    assert parsed.auth_problem is auth_problem


def test_normal_stream_with_fixed_429_session_id_has_no_stop_evidence():
    session_id = "d7792566-dd7b-4a82-85c5-8c1b429c8b1a"
    stdout = "\n".join(json.dumps(event) for event in [
        {"type": "system", "subtype": "init", "session_id": session_id},
        {"type": "result", "subtype": "success", "is_error": False, "session_id": session_id,
         "structured_output": {"status": "done", "summary": "OK", "files_changed": [],
                               "commands_run": [], "verification": "not-run", "open_questions": [],
                               "next_step": ""}},
    ])
    parsed = runners.parse_claude(stdout, "", 0, None)
    assert parsed.ok
    assert parsed.kind == "ok"
    assert parsed.session_id == session_id
    assert runners.classify(stdout) == "error"
    assert quota.stop_evidence("claude", stdout, "", None) == {"by": "unknown"}


@pytest.mark.parametrize("hint, kind", [
    (hint, kind)
    for hints, kind in ((runners.QUOTA_HINTS, "quota"), (runners.AUTH_HINTS, "auth"),
                        (runners.MODEL_HINTS, "model"))
    for hint in hints if not hint.isdigit()
])
def test_text_hints_keep_case_insensitive_substring_matching(hint, kind):
    text = "prefix" + hint.upper() + "suffix"
    assert runners.classify(text) == kind
    evidence = quota.stop_evidence("codex", text, "", None)
    if kind == "quota":
        assert evidence == {"by": "hint", "hint": hint, "text": text}
    else:
        assert evidence == {"by": "unknown"}


@pytest.mark.parametrize("hint", ["429", "401", "503"])
def test_match_skips_embedded_occurrences_and_returns_valid_position(hint):
    text = f"a{hint}f {hint}0 1{hint} ({hint})"
    assert runners.match_hint(text, (hint,)) == (hint, text.rindex(hint))
    assert runners.match_hint(f"a{hint}f", (hint,)) is None


def test_evidence_context_centers_on_valid_occurrence():
    text = "8c1b429c8b1a " + "x" * 350 + " HTTP 429"
    assert runners.classify(text) == "quota"
    evidence = quota.stop_evidence("codex", text, "", None)
    assert evidence["hint"] == "429"
    assert "HTTP 429" in evidence["text"]
    assert "8c1b429c8b1a" not in evidence["text"]


def test_numeric_match_position_uses_original_text():
    text = "\u0130: HTTP 429"
    assert runners.match_hint(text, runners.QUOTA_HINTS) == ("429", text.index("429"))


def test_hint_priority_and_fallback_are_unchanged():
    text = "QUOTA exceeded; HTTP 429"
    assert runners.match_hint(text, runners.QUOTA_HINTS) == ("429", text.index("429"))
    assert quota.stop_evidence("codex", text, "", None)["hint"] == "429"
    assert runners.classify("status: 401; HTTP 429") == "quota"
    assert runners.classify("status: 401; HTTP 429; unknown model") == "model"
    text = "8c1b429c8b1a; QUOTA exceeded"
    assert runners.classify(text) == "quota"
    assert quota.stop_evidence("codex", text, "", None)["hint"] == "quota"
    assert runners.classify("") == "error"
    assert runners.match_hint("", runners.QUOTA_HINTS) is None
