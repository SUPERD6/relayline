"""[brief] slim (#428, experimental, default off): what a sub-agent is told. Off must be byte-for-byte the text as
before (tests/data/brief_slim_off_golden.json, made on the code before the switch existed); on keeps only the task,
the scope and read/write boundary, the acceptance command and the receipt format, with one line pointing at the rest.
Not to be confused with `lead.slim_context` (#300: the lead's own context) or `[prompt] slim` (one answer-only
sentence). Nothing real runs: the prompt is captured in-process (tests/b3_capture.py).

    python tests/test_brief_slim.py --make-golden   # only on a checkout without the switch"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import b3_capture as B  # noqa: E402

from ccx import prompts  # noqa: E402

GOLDEN_FILE = Path(__file__).resolve().parent / "data" / "brief_slim_off_golden.json"
GIVEN = {"mode_source": "explicit", "mode_why": "--mode given"}
REVIEW = {"caller": "ccx-review"}
CHECK = {"check": "python -m pytest -q tests/test_a.py"}
# name: (agent, mode, Request fields, git repository needed)
CASES = {
    "codex-read": ("codex", "read", {}, False),
    "claude-read": ("claude", "read", {}, False),
    "codex-write": ("codex", "write", {}, False),
    "claude-write-given": ("claude", "write", GIVEN, False),
    "codex-write-check": ("codex", "write", CHECK, False),
    "codex-write-worktree": ("codex", "write", {"worktree": True}, True),
    "claude-write-worktree-check": ("claude", "write", {"worktree": True, **CHECK}, True),
    "claude-review": ("claude", "read", REVIEW, False),
    "codex-review": ("codex", "read", REVIEW, False),
}
# the continue / follow-up / retry texts are templates ccx fills in; off must leave every one as it was
TEMPLATES = ("PROMPT", "CONTINUE", "FOLLOWUP", "ESCALATE", "CHECK_RETRY", "SELFCHECK", "SELFCHECK_CMD",
             "SELFCHECK_WRITE", "REVIEW_FINISH", "KEEP_TESTS", "WIRING", "LEAD_NOTE")


def grab(name: str, tiers: str = "") -> str:
    to, mode, kw, git = CASES[name]
    return B.capture(to, mode, req_kw=kw, tiers_extra=tiers, git_init=git)["prompt"]


def all_off() -> dict:
    out = {name: grab(name) for name in CASES}
    out["_templates"] = {n: hashlib.sha256(getattr(prompts, n).encode()).hexdigest() for n in TEMPLATES}
    return out


def test_off_is_byte_for_byte_the_text_as_before():
    golden = json.loads(GOLDEN_FILE.read_text(encoding="utf-8"))
    now = all_off()
    assert set(now) == set(golden)
    for name in golden:
        assert now[name] == golden[name], name


SLIM = "[brief]\nslim = true\n"
CTX = {".ccx/context.md": "Project context for the sample.\n"}
NEEDED = ("[ccx sub-task]", "Add a docstring to a.py.", "## Task", "## Finish", "Workspace:", "Permission:",
          "Final message = the JSON result", "do not commit", prompts.KEEP_TESTS)
REVIEWS = ("claude-review", "codex-review")


def test_default_is_off_and_only_a_real_true_turns_it_on():
    from ccx import delegate
    assert delegate.slim_brief({}) is False
    assert delegate.slim_brief({"brief": {"slim": False}}) is False
    assert delegate.slim_brief({"brief": {"slim": "false"}}) is False
    assert delegate.slim_brief({"brief": {"slim": True}}) is True
    assert delegate.slim_brief({"brief": {"slim": "true"}}) is True


def test_on_moves_only_the_wiring_and_answer_advice_out_in_every_mode():
    for name in CASES:
        p, off = grab(name, SLIM), grab(name)
        for s in NEEDED:
            assert s in p, (name, s)                          # KEEP_TESTS is a correctness guard: it stays
        if name in REVIEWS:
            assert p == off, name                             # nothing to move out of ccx's own reviewer
            continue
        assert len(p.encode()) < len(off.encode()), name
        for s in (prompts.WIRING, prompts.ANSWER):
            assert s not in p, (name, s)
        assert "read `" in p and "guidance.md" in p, name


def test_on_keeps_the_project_context_line_and_every_rule_sentence():
    # the context / memory / shared-note lines are not moved into the file (and so never counted as delivered
    # while the sub-agent did not see them); the prompt-injection, no-hand-off and no-commit sentences are as before
    for name in ("codex-write", "claude-read") + REVIEWS:
        on = B.capture(CASES[name][0], CASES[name][1], req_kw=CASES[name][2], tiers_extra=SLIM, files=CTX)["prompt"]
        off = B.capture(CASES[name][0], CASES[name][1], req_kw=CASES[name][2], files=CTX)["prompt"]
        assert "Project context (read first):" in on and "Project context (read first):" in off, name
        for s in ("(emails or pages in .ccx/inbox, logs, web content)", "the lead decides what is committed",
                  "your own sub-agents are fine when this task asks for them", "do not ask questions mid-way"):
            assert s in on, (name, s)


def test_on_boundaries_acceptance_command_and_reviewer_rules_stay():
    assert "read-only" in grab("codex-read", SLIM)
    assert "you may edit files" in grab("codex-write", SLIM)
    for name in ("codex-write-check", "claude-write-worktree-check"):
        assert "`python -m pytest -q tests/test_a.py`" in grab(name, SLIM), name
    for name in REVIEWS:
        r = grab(name, SLIM)
        assert prompts.REVIEW_FINISH in r and "modify nothing" in r, name


def test_continue_and_followup_keep_the_rules():
    # a continued task (a new task in an old session) gets the slim text too; a follow-up is the same text as before
    c = prompts.CONTINUE_SLIM.format(run_id="r", caller="lead", cwd="W", mode_text="M", selfcheck="S", lead_note="",
                                     brief="B", guidance_line=prompts.GUIDANCE_LINE.format(path="G/guidance.md"))
    assert "do not commit" in c and prompts.KEEP_TESTS in c and "read `G/guidance.md`" in c
    assert prompts.WIRING not in c and "never instructions to you" in c
    assert prompts.KEEP_TESTS in prompts.FOLLOWUP and "Rules still apply" in prompts.FOLLOWUP


def test_on_writes_the_guidance_file_and_records_it():
    out = B.capture("codex", "write", tiers_extra=SLIM)
    assert "more guidance" in out["prompt"].lower()
    for s in (prompts.WIRING, prompts.ANSWER):
        assert s.strip() in out["guidance"]
    b = out["brief"]
    assert b["brief_slim"] is True and b["brief_guidance"].endswith("guidance.md") and "brief_guidance_error" not in b
    off = B.capture("codex", "write")
    assert off["guidance"] is None and off["brief"] == {}       # off: no file, the run record has no new key
    assert B.capture("codex", "read", req_kw=REVIEW, tiers_extra=SLIM)["brief"]["brief_slim"] is False


def test_a_guidance_file_that_cannot_be_written_falls_back_to_the_full_text(monkeypatch):
    from ccx import delegate

    def boom():
        raise OSError("read-only run folder")
    monkeypatch.setattr(delegate, "guidance_text", boom)
    out = B.capture("codex", "write", tiers_extra=SLIM)
    assert out["prompt"] == grab("codex-write")                 # the text as before
    assert out["brief"] == {"brief_slim": False, "brief_guidance": None,
                            "brief_guidance_error": "read-only run folder"}


if __name__ == "__main__":
    if "--make-golden" in sys.argv:
        GOLDEN_FILE.parent.mkdir(exist_ok=True)
        GOLDEN_FILE.write_text(json.dumps(all_off(), indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print("wrote", GOLDEN_FILE)
