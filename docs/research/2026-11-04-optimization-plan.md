# Optimization plan (2026-11-04)

English · [中文](2026-11-04-optimization-plan.zh.md) · [Research reports](README.md)

## Goal and current status

This round has two goals: **(1) the default path does not get worse; (2) at least one scenario has a reproducible
positive effect.** Not every feature must become positive. This plan promises neither stars nor popularity.

Evidence level for this plan's future work: **not run**. Outcome: **Unknown**. The table proposes thresholds;
each stage must commit its own preregistration before running, fixing them and the decision order. Do not change
them after starting. Follow the [engineering standards](../engineering-standards.md) for evidence, metrics,
data retention and stop rules. Contribution workflow stays in [CONTRIBUTING](../../CONTRIBUTING.md).

`self` means the lead does the work itself. The ccx default path may do small tasks itself rather than delegate.
Stage 4 tests delegation on larger work and long sessions, with the lead reading only a one-line result.
That comparison measures the whole workflow; if delegation and lead reading policy both change, their effects
are not isolated. Count all lead, sub-agent, review, repair, failed and interrupted attempts in spend.

## Stages and budget

All amounts are estimated API-equivalent USD, not measured costs.

| Stage | Work | Estimate | Threshold or output |
|---|---|---|---|
| 0 | Rerun self on the held-out set; offline analysis of `ledger-repair` and pytest temporary-directory permission failures | About $3 | Separate code and environment effects |
| 1 | Fix sandbox behavior; pass the user's original wording to sub-agents; calibrate doing small tasks itself; test-based review (off by default) | No evaluation fee | engineering check |
| 2 | Replay the 29 pg3b receipts through test-based review | $2–5 | Catch rate ≥ 50%; false-block rate ≤ 20% |
| 3 | Unused small tasks: self vs the ccx default path | $5–8 | Correct count ≥ self − 1; cost per success ≤ 1.2× self |
| 4 | Large tasks and long sessions: do everything itself vs delegate and let the lead read only a one-line result | $10–15 | Total spend ≤ 0.8× self; correct count no lower than self; median wall time ≤ 2× self |
| 5 | Repeat qualifying results for another round; real-issue benchmark in external repositories | $15–25 | At least two rounds for public numbers |

**Total hard cap: $60.** Include all attempts in this round, including failures and interruptions. Stop if any
stage exceeds 1.5× the upper end of its estimate, or before the total would exceed $60. Stage 1 authorizes no
paid evaluation. Do not start a unit that would exceed a cap. Stop and ask the maintainer for budget changes.

The estimates and thresholds are proposals until each stage's preregistration fixes them. Stage 0 must record
the set's previous use: tasks reused after earlier hold-out runs are no longer unseen. Stages 0 and 2 are
diagnostics/development, not final-set evidence. Replaying historical receipts is an **engineering check**;
it cannot alone establish a benefit on fresh tasks or justify a default change. If review calls a real CLI,
retain its data and report the measured cost separately from the replay's engineering verdict.

Preregister sample sizes, code pins, groups, rounds, metrics, thresholds, decision order, budget and interruption
handling before each stage. Freeze a fresh final set for stages 3–5; do not tune on its outcomes. Record repeat
use in stage 5. If a final-set failure prompts a change, return to development and reserve new final tasks.
Same-version comparisons use the same tasks, conditions and evaluation protocol in both arms.
Use an independent clone on an idle machine, one evaluation at a time. Retain all rows and raw results; report
all-row and clean-row metrics separately when needed. Do not relabel environment failures as task errors.

Passing one stage does not turn a feature on. A default change needs a decision and linked report. Allow at most
two improvement rounds per item. If both fail, leave it off or limit it to a demonstrated scenario, and publish
the negative result. Do not spend indefinitely trying to force every item to become positive.

## Starting evidence and limits

These are existing observations, not outcomes of this plan. Source reports contain the version pins and data
links. They do not provide a same-version control for the proposed work.

| Evidence | Known result | Scope and limit |
|---|---|---|
| measured: [pg1, 2026-10-31](2026-10-31-polyglot-pg1.md), pin `5d4bd01` | self 25/30; ccx2 12/30 | 30 small, strict-interface tasks; one round. Do not generalize to larger work. |
| measured: [pg3b, 2026-11-03](2026-11-03-pg3b-receipts.md), pin `b9d1d54` | 15 of 29 `ok_self_checked` receipts were wrong; review passed all 29 | This is the replay development pool. Ordinary `ok` evidence was insufficient. It does not establish review performance on unseen tasks. |
| measured: [hc2, 2026-11-04](2026-11-04-hc2-holdout.md), 0.6.0 candidate, pin `b9d1d54` | 28/30 overall; 25/27 clean; $0.088 per success on clean rows; median wall time 168 s | Self was not rerun. Code and environment effects were not isolated. These tasks have been reused. Money is API-equivalent. |
| measured, historical: [hc1, 2026-10-29](2026-10-29-hc1-holdout.md) | Old-code experiment; see the report for its pin and sample | Historical only; not a control for the current version. |
| measured: [B3, 2026-10-31](2026-10-31-b3-lean-switches.md) | Lean switches did not demonstrate savings | Pins and sample limits are in the report. Keep current defaults and experimental status; no further investment. |

## How the result changes the positioning

| Outcome | Positioning |
|---|---|
| Large-task savings established and no regression | Lead with cheaper large-task work, within the tested scenario. |
| Only no regression established | Lead with cross-tool handoffs, continuity across quota limits and trustworthy receipts. |
| Neither established | Narrow the tool's role; do more work itself by default. |

These are conditional choices, not present claims that those benefits have been demonstrated. Publish negative
and positive results together, with sample size, version, date, limits and report links. External publication
still requires the maintainer's approval.
