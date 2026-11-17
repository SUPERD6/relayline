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
NEEDED = ("[ccx sub-task]", "Add a docstring to a.py.", "## Task", "## Finish", "Workspace:", "Permission:",
          "Final message = the JSON result", "do not commit")


def test_default_is_off_and_only_a_real_true_turns_it_on():
    from ccx import delegate
    assert delegate.slim_brief({}) is False
    assert delegate.slim_brief({"brief": {"slim": False}}) is False
    assert delegate.slim_brief({"brief": {"slim": "false"}}) is False
    assert delegate.slim_brief({"brief": {"slim": True}}) is True
    assert delegate.slim_brief({"brief": {"slim": "true"}}) is True


def test_on_keeps_only_the_needed_parts_in_every_mode():
    for name in CASES:
        p, off = grab(name, SLIM), grab(name)
        assert len(p.encode()) < len(off.encode()), name
        for s in NEEDED:
            assert s in p, (name, s)
        for s in (prompts.KEEP_TESTS, prompts.WIRING, prompts.ANSWER, "Project context (read first)"):
            assert s not in p, (name, s)
        # ccx's own reviewer runs no tests, so it has no builder advice to point at
        assert (prompts.GUIDANCE_LINE.split("{")[0] in p) == ("review" not in name), name


def test_on_boundaries_acceptance_command_and_reviewer_rules_stay():
    assert "read-only" in grab("codex-read", SLIM)
    assert "you may edit files" in grab("codex-write", SLIM)
    for name in ("codex-write-check", "claude-write-worktree-check"):
        assert "`python -m pytest -q tests/test_a.py`" in grab(name, SLIM), name
    for name in ("claude-review", "codex-review"):
        r = grab(name, SLIM)
        assert prompts.REVIEW_FINISH in r, name           # no tests, nothing modified: the reviewer's permission
        assert "modify nothing" in r, name


def test_on_writes_the_guidance_file_the_line_names():
    out = B.capture("codex", "write", tiers_extra=SLIM)
    line = [ln for ln in out["prompt"].splitlines() if ln.startswith("Guidance")][0]
    assert "guidance.md" in line
    for s in (prompts.KEEP_TESTS, prompts.WIRING, prompts.ANSWER):
        assert s.strip() in out["guidance"]
    assert B.capture("codex", "write")["guidance"] is None      # off: no file


if __name__ == "__main__":
    if "--make-golden" in sys.argv:
        GOLDEN_FILE.parent.mkdir(exist_ok=True)
        GOLDEN_FILE.write_text(json.dumps(all_off(), indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print("wrote", GOLDEN_FILE)
