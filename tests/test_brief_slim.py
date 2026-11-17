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


if __name__ == "__main__":
    if "--make-golden" in sys.argv:
        GOLDEN_FILE.parent.mkdir(exist_ok=True)
        GOLDEN_FILE.write_text(json.dumps(all_off(), indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print("wrote", GOLDEN_FILE)
