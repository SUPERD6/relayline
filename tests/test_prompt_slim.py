"""P0-11 item 2, [prompt] slim: a run the lead gave `--mode write` (no --check) is not told what to do with an
answer-only task; an inferred or default write mode, a read run and a run with --check are as before. What the
sub-agent receives, captured in-process (tests/b3_capture.py); nothing real runs."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import b3_capture as B  # noqa: E402

from ccx import delegate, prompts  # noqa: E402
from ccx.modes import resolve_mode  # noqa: E402

GIVEN = {"mode_source": "explicit", "mode_why": "--mode given"}


def finish(prompt: str) -> str:
    return prompt.split("## Finish", 1)[1]


def test_given_write_leaves_the_answer_sentence_out():
    for to in ("codex", "claude"):
        f = finish(B.capture(to, "write", req_kw=GIVEN)["prompt"])
        assert prompts.SELFCHECK_WRITE in f and prompts.ANSWER not in f
        assert "For a change, say in summary what changed" in f       # the rest of the text is unchanged
    assert prompts.SELFCHECK == prompts.ANSWER + prompts.SELFCHECK_WRITE


def test_inferred_default_read_and_check_keep_the_text_as_before():
    # an answer the brief asks for can read as a change ("What does add() return?" infers write)
    assert resolve_mode(None, "What does add() return in hello.py?")["source"] == "inferred"
    for kw in ({"mode_source": "inferred", "mode_why": "edit verb"}, {"mode_source": "default", "mode_why": ""}, {}):
        assert prompts.ANSWER in finish(B.capture("codex", "write", req_kw=kw)["prompt"]), kw
    assert prompts.ANSWER in finish(B.capture("codex", "read", req_kw=GIVEN)["prompt"])
    f = finish(B.capture("codex", "write", req_kw={**GIVEN, "check": "python -c pass"})["prompt"])
    assert "The acceptance check is `python -c pass`" in f


def test_slim_false_puts_the_sentence_back(monkeypatch):
    assert delegate.slim_prompt({}) is True
    assert delegate.slim_prompt({"prompt": {"slim": False}}) is False
    assert delegate.slim_prompt({"prompt": {"slim": "false"}}) is False
    monkeypatch.setattr(delegate, "slim_prompt", lambda cfg: False)
    assert prompts.ANSWER in finish(B.capture("codex", "write", req_kw=GIVEN)["prompt"])


def test_mode_given_is_what_the_cli_records():
    assert resolve_mode("write", "anything") == {"mode": "write", "source": "explicit", "why": "--mode given"}
