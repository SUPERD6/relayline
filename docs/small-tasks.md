# Experimental small-task controls

[中文](small-tasks.zh.md)

Both new switches default to false. Existing commands, options, JSON meanings and exit codes remain available.

| Setting | Opt-in behavior |
| --- | --- |
| `routing.small_self_run` | Before `ccx run` starts or detaches, reuse the `routing.small_self` sizing rule. A known lead (not a ccx sub-agent, user or unknown caller) receives `state="small_self"`, `delegated=false`, advice and a `--force` hint. Exit 0 means nothing was delegated, as for the existing routing refusal. |
| `routing.strict_escalate` | In `ccx/plan.py`, unchecked writes and briefs matching the strict-interface rule skip the cheapest configured T1 rung (also Codex gpt-6-luna low). Stronger starts stay unchanged. This floor applies even with `--no-escalate`; it is not a retry. |

Run sizing uses `--files` or existing file paths named in the brief, or the existing experimental cost proxy when
`routing.small_self_by=cost`. Unknown size keeps delegating. Existing picked-tier, large-context, tight-quota
exceptions remain; `--worktree` also keeps delegating. Read tasks bypass the small-task gate. `--force` bypasses
the small-task gate, not the independent strict floor. `routing.small_self` remains an advisory-only switch.

Strict-interface detection is a case-insensitive lexical rule: `strict interface` / `strict-interface`,
`exact signature`, `exact output`, `exact match` (space or hyphen), `must return/raise/accept/match`,
or `严格接口`, `精确匹配`, `必须返回`. It can miss paraphrases or match quoted text; it does not prove interface correctness.
An ordinary write with `--check` does not escalate unless this rule matches. The run's route adds
`strict_escalate` with the old/new rung and trigger flags only when applied.

`scripts/eval/r5.py run --arms ccx2small` is opt-in. It uses ccx2's lead and command wording plus an instruction
to implement locally on `state=small_self`. Its own hub sets and asserts both switches before launching the lead.
Rows record `small_self_run.applied` and the ledger decisions, even when no ccx run starts. This bundled arm
changes two controls together and cannot attribute an effect to either one separately. No paid evaluation was run.

Evidence: **engineering check** only; effectiveness **Unknown**. Conservative calibration keeps
`small_self_files=1` and `small_self_overhead_usd=0.035`; see the
[development-data report](research/2026-11-04-small-calibration.md).
