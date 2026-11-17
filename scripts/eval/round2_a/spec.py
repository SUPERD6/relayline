"""Authoring helpers for the round 2 A1/A2 tasks (#375). Data only: no model is called here.

A task module defines TASKS (a list built with ctx() or mem()). scripts/eval/round2_a_tasks.py turns the modules into
the frozen task files that strength_retest.py reads (--tasks) and checks every task offline.

trace: {hidden test function: [fragments]}; every fragment must appear (normalized) in the brief or in the
convention text (A1 settle, A2 memory). conventions: the 2-3 fragments of the convention text that the hidden tests
check; each must be in some trace entry, and the naive implementation (repository default / dropped option) must fail
at least one test traced to it.
"""
from __future__ import annotations

import textwrap


def D(text: str) -> str:
    """Dedented code block, no leading blank line, one trailing newline."""
    return textwrap.dedent(text).strip("\n") + "\n"


def ctx(id, *, files, brief, settle, hidden, reference, trace, naive=None, reversed=None, conventions=(),
        neutral=False):
    return {"kind": "context", "id": id, "files": files, "brief": brief, "settle": settle, "reversed": reversed,
            "hidden": hidden, "reference": reference, "naive": naive, "conventions": list(conventions),
            "trace": trace, "neutral": neutral}


def mem(id, *, files, brief, memory, hidden, reference, trace, naive, conventions, distractors=(), visible=None):
    return {"kind": "memory", "id": id, "files": files, "brief": brief, "memory": memory, "hidden": hidden,
            "reference": reference, "naive": naive, "conventions": list(conventions), "trace": trace,
            "distractors": [list(d) for d in distractors], "visible": visible}
