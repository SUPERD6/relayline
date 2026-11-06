# Model capacity recovery

English · [中文](capacity.zh.md)

When a failed CLI reports `Selected model is at capacity`, ccx records `kind=capacity`,
separately from exhausted subscription quota, authentication and transport errors.
Only the last CLI error/turn result supplies capacity evidence; earlier recovered errors cannot override
the actual failure. Existing quota, unsupported-model, authentication and environment verdicts take priority.
Recognized error envelopes and explicit CLI error text use the shared quota-signal classifier;
ordinary assistant/tool output and HTTP 429 alone do not establish capacity exhaustion.

This bug fix is enabled by default. To restore the previous retry behavior:

```console
ccx config set defaults.capacity_fallback false
```

Recovery skips already attempted agent/model pairs, including other effort levels for the same model,
and uses the remaining configured ladder first. If none remain, the existing cross-vendor fallback
selector may supply one alternative. There are at most two capacity switches per run. Each switch
starts a fresh session with the original brief. Existing budget checks still apply.
`--no-escalate` removes the remaining ladder; `--no-fallback` disables the additional cross-vendor
fallback as before. Set both to stop after the first capacity error.
An explicit resume/follow-up stops on capacity instead of silently discarding its conversation.
An automatically continued new task may recover, but the fresh session receives a complete task prompt.

Receipts add `capacity_recovery` entries with source/target rungs, `reason=model_at_capacity`, and
`action=switch|stop`; attempt records add `capacity_stop` evidence. Capacity failures do not mark a
model permanently unavailable, update quota pressure, or count as failures of model ability.
Recovery entries also include `same_vendor`, `from_tier`, `to_tier`, and `tier_upgrade` (null when
the configured tiers are not comparable). Tier upgrades are explicit; `cost_increase=null` makes no
claim about actual prices. Capacity stops break warm lanes, automatic session/seat reuse and merged-task
repair; the UI keeps them open rather than judging the task wrong. Checkpoints retain the existing
`reason=error` contract and record capacity plus the resume command in their note.
Existing commands, options and exit codes are retained. Disabling the setting retains legacy kinds.

Evidence: **engineering check**, synthetic error events and fake CLI subprocesses only.
Real-provider behavior and Windows/Linux/macOS CI are **Unknown**; no live CLI evaluation was run.
