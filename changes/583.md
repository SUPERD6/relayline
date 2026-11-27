- Evaluation (#546): the fat-context diagnostic arms for trade-off map cell 4, new and opt-in in
  `scripts/eval/p4_long_session.py` (`--arms fatself,fatnative,fatccx`, any subset, round-2 task files only; no
  existing arm, default, task file or preregistration changes). The same task is done by the lead itself, by Claude
  Code's built-in sub-agent (Agent tool, the `worker` definition earlier built-in arms used) or by Codex through ccx
  (the shipped default path, as `ccxlong`), after the lead has been filled to a measured context: `--fat-tier main`
  (225,000 tokens, the measured real re-read median) or `heavy` (360,000), or `--fat-tokens N`. The fill is a first
  turn of the same Claude session with deterministic, task-independent filler (`scripts/eval/fat_arms.py`), once per
  episode; its cost is recorded apart as `fill_usd` (not in a task's `usd`, but charged to the run budget and reserved
  before the episode starts); the real fill size is read from the stream (`fill_measured_tokens`) and a fill outside
  `--fill-tolerance` marks the row invalid and stops the run. Rows reuse the existing preflight, audit,
  accounting and `between_units`, and add `agent_calls`, `ccx_calls`, `worker_requests` and `arm_conformance` (a lead
  that did not follow its arm is an invalid row, kept). The dry run prints each arm's tools, agents, lead model, fill
  and budgets under `fat`; the summary has a descriptive `fat` section (no verdict: the rule is #547's
  preregistration). Checked with fake CLIs only; not run for real: `sonnet[1m]` availability, the filler's real
  tokens per character and whether `result.usage` counts native sub-agent tokens are Unknown until the #547 smoke
  test (the cost check fails closed, so a native row is cost-unknown, never silently wrong).
