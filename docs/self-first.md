# Experimental self-first routing

English · [中文](self-first.zh.md)

`ccx config set routing.default self_first` prefers doing tasks in the current conversation.
The shipped value is `auto`: existing behavior, policies, JSON meanings, verdicts and exit codes stay unchanged.
This switch has engineering checks only; real CLI cost, wall time and correctness have **not been measured**.
Restore the existing behavior with `ccx config set routing.default auto`.

With `self_first`, `ccx route` and `ccx propose` advise doing the task yourself, and ordinary automatic
`ccx run` routing refuses delegation unless at least one condition holds:

| Condition | Existing input reused |
|---|---|
| Lead quota is tight | Existing quota readings or `--quota LEAD=USED`; any valid window has used share greater than `quota.avoid_above` (0.8), or projected share greater than 1.0 |
| Lead context is large | `--lead-ctx` on route/propose, else the current lead session; at least `policy.bands.lead_ctx_large` tokens (150000) |
| Explicit assignment | A concrete `--to`, `--model`, `--provider` or `--role` (or the corresponding task spec) |
| Independent parallel work | Explicit `--independent-parts` on run/route/propose or `independent_parts: true` in a task spec |

Missing quota or context readings remain `Unknown`; they do not satisfy a condition. No task-size or prose
keyword guesses establish parallelism or explicit assignment. On route/propose, supply `--lead` to identify
the lead when it cannot be detected. `self_first.checks`, `matched` and `why` show the decision in the route,
proposal ledger or run's `route` receipt. `eligible` only permits the existing routing checks to continue;
it neither forces delegation nor authorizes it. Existing small-task, quota, budget, autonomy and acceptance
checks still apply. `--force` keeps its explicit override; `routing.mode=off` remains the master switch.
An explicit `--role`, including a fixed-model role, matches `explicit_request`. Its internal sizing override
does not count as a user `--force`: the receipt's `forced` field reflects only the user's actual flag.

`--independent-parts` declares that the task has independent blocks the lead can delegate concurrently.
It does not instruct the child to start its own sub-agents. The existing run `--parallel` keeps that separate
child-execution behavior and does not satisfy the self-first parallel condition. Use both flags when both
intentions apply; neither option is removed.

If reading the quota fails (file or parse error), `quota_tight` is also `Unknown`.
`checks.quota_missing` lists named windows present in the quota reading whose used share is unavailable,
including expired windows. `quota_tight: false` means none of the observed valid windows is tight, not that
every window is known. With no valid windows, `quota_tight` stays `Unknown`; window names absent from all
readings are not guessed. A known tight window still satisfies the condition even when another is missing.

The current context-source values are `given` (explicit `--lead-ctx`), `lead_session` (read from the lead's
session) and `none` (unavailable). Only `given` and `lead_session` readings are reused, including zero.
Estimates, defaults and other source labels are not accepted as readings: without a real session reading,
the context condition stays `Unknown` even if a cost estimate contains a large token count.

The existing whole-workflow policies are unchanged: `fast` always plans self, while `balanced` uses task size
and context. Neither expresses these four conditions. This small gate in `[routing]` reuses their inputs
without adding another model-selection policy. Without a matching condition it also stops a picked tier
from pre-authorizing a proposal; a matching condition still respects that tier's own decision.

No command or option was removed. Existing started-session resume, ask and discuss paths are unchanged.

## User force and internal routing calls

Only a `--force` parsed from the CLI creates the positive `_user_force` marker. Self-first never infers user
intent from a routing spec's `force`, including batch JSON or the older `_self_first_force` key. Ordinary
`force` still has its existing model-selection/A-B meaning. CLI run and batch carry the marker; queue refill
and warm lanes preserve it when actually supplied. A literal `--force` in the brief after `--` is not a flag.

A queue piece is already assigned for delegation by `q run` / `q resume`. It therefore qualifies as
`checks.explicit_request: true`, with `checks.explicit_request_source: "queue"` and `source=queue` in `why`.
Without a CLI `--force`, its `forced` is false. This is an explicit request, not a force override; the
existing quota, budget, autonomy, acceptance and routing-mode gates keep their meanings.

The `ccx/` force-source audit found these five internal routing sites:

| Internal site | Self-first handling | Regression coverage |
|---|---|---|
| `commands/workqueue.py`, `_one` | Queue assignment is explicit; internal `force=True` is not user force | `test_queue_piece_records_explicit_queue_request` |
| `commands/memory.py`, `_handoff_by_model` | Automatic transcript fallback must satisfy the gate; it cannot override it | `test_transcript_handoff_internal_force_does_not_launch` |
| `commands/delegation.py`, `_route_pick` role branch | Advisory model sizing; final advice uses actual CLI intent | `test_advisory_role_and_rubric_force_is_not_user_force` |
| `commands/delegation.py`, `_route_pick` rubric branch | Advisory model sizing; final advice uses actual CLI intent | `test_advisory_role_and_rubric_force_is_not_user_force` |
| `plan.py`, `resolve_role` fixed-model sizing | Keep sizing force; copy the CLI marker unchanged; role is explicit | `test_fixed_role_reports_explicit_assignment_and_actual_force` |

Also checked: relay launches its native CLI directly (`--force-unconfirmed` is a separate flag); resume,
review and merge-repair use `Request` without a routing `force` field. None supplies an internal force to
`resolve` or `_plan`. The `setup.py` `init_hub(force=True)` call replaces hub wiring, not a routing decision.
These paths do not manufacture a user-force marker and retain their existing behavior.
