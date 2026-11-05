"""Opt-in P5 arm controls, shared by plans, prompts and receipt enforcement."""
from __future__ import annotations

ARMS = ("self", "ccxlong", "ccxlongcheap")
CHEAP = "ccxlongcheap"
MODEL, EFFORT = "gpt-6-luna", "medium"


def focused_brief(task):
    files = ", ".join(task.get("code") or [])
    return ("Work only on the request below. Start by reading these implementation files: " + files +
            ". Read additional files only when needed; avoid whole-repository dumps. Preserve existing tests; "
            "report any conflict with the request.\n\n" + task["brief"])


def initial_model_flags(arm):
    return f"--model {MODEL} --effort {EFFORT} " if arm == CHEAP else ""


def estimate_base(arm, ordinary):
    # No measured luna/medium long-task mix. Keep the ordinary workflow estimate
    # as a conservative planning proxy, never claim model-only price savings.
    return ordinary, ("Unknown: ordinary ccxlong planning proxy; luna/medium token mix and retries unmeasured"
                      if arm == CHEAP else "historical size-based workflow proxy")
