# P4 cumulative cost correction

[中文](2026-11-04-p4-cost-accounting.zh.md)

Evidence: engineering checks and a read-only replay of retained development results. No new model calls.
Task selection, gates, budget amounts and product behavior are unchanged.

Claude Code 2.1.316 resumed result events report session-cumulative `total_cost_usd` and `modelUsage`,
while `result.usage` covers the current invocation. Adding every reported total double-counted earlier
turns. Each episode/arm now keeps a separate validated cumulative baseline (initially zero).
`lead_cumulative_usd` retains the current total; `lead_previous_cumulative_usd` retains the previous trusted
total; `lead_usd` is their difference. `usd`, `known_usd`, episode totals, the budget and summaries use that difference.

`lead_result_usage` stores the current result usage; `lead_model_usage` sums counters across all models.
`cost_cumulative_check` is true only when each of `input_tokens`, `output_tokens`,
`cache_read_input_tokens`, `cache_creation_input_tokens`, accumulated across invocations, equals the
corresponding `modelUsage` counters `inputTokens`, `outputTokens`, `cacheReadInputTokens`,
`cacheCreationInputTokens`. Missing/non-integer/negative counters fail this check. `cost_errors` explains failures.
Missing, nonfinite, negative or decreasing costs, failed usage checks and session ID mismatches make lead
cost unknown (`lead_usd=null`, `usd=null`, `cost_complete=false`). Known child spend remains charged.
The last trusted baseline is preserved, and unknown accounting stops the run; a later receipt cannot
silently heal an unobserved gap. Failures with complete valid receipts still incur their measured cost.

`claude --version` and `claude --help` were checked again: **2.1.316**. Help describes `--max-budget-usd`
as a maximum API-call dollar amount in print mode, without specifying whether resume applies it to
one invocation or the entire session. That scope remains **Unknown** in the plan. The existing operational
envelope remains a scheduling policy, not a guaranteed invoice limit.

Read-only correction from any directory (legacy rows require their exact artifact run directory):

```text
python /path/to/repo/scripts/eval/p4_long_session.py --recompute /path/to/p4dev-results.jsonl --artifacts-root /path/to/p4dev-results-artifacts/20261104-231406Z --tag p4dev --split dev
```

The command prints corrected rows and the normal all/env_clean summaries to stdout; it never writes the
source results or calls preflight/models. New rows contain normalized counters and can be replayed without
`--artifacts-root`. Missing streams, gaps and mismatches stay unknown rather than using old inflated totals.

Retained development replay (same values for all rows and clean rows):

| Metric | self | ccxlong | ccxlong / self |
|---|---:|---:|---:|
| Cost, USD | 0.258323 | 0.397702 | 1.539553 |
| Correct / attempted | 1 / 3 | 0 / 3 | 0 / 1 |
| Median wall seconds | 47.563 | 135.688 | 2.852806 |

Each arm has only three of four preregistered tasks; the unchanged verdict is **Unknown**. Delegation and
one-line acceptance still change together. These partial development results do not support a benefit claim.

The lead authorized updating the shared fake CLI to match native receipts. It now emits cumulative cost
($0.10/$0.20/$0.30/$0.40), cumulative model counters and invocation-scoped usage; its per-invocation charge
remains $0.10. Existing assertions are unchanged. A separate regression checks both arms' cumulative and
invocation fields. The accounting validator and its fail-closed protections are unchanged by this follow-up.
