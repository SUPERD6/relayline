# Experimental small-task lead guidance

English · [中文](lead-slim.zh.md)

`[lead] slim_small = false` ships **off**. Enable with `ccx config set lead.slim_small true`.
Run `ccx sync --only memory --apply` to refresh existing managed blocks; the normal `ccx turn` hook
also emits the guidance. Both use `ccx.lead_slim.small_guidance`; sub-agent hooks omit it.
Disable with `ccx config set lead.slim_small false` and sync again to remove it from managed blocks.
An already running conversation may retain previously loaded instructions; use a fresh session after switching.

With the switch enabled, a lead that can already identify a clearly small task implements and checks it
without first calling ccx, writing a brief, or loading the delegation skill. The existing file limit
`routing.small_self_files` applies (default 1 implementation file); this is guidance, not a new hard refusal.
Uncertain sizing, required ccx worktree/undo/resume/other-vendor support, large lead context, or known tight
quota use the normal delegation path. Existing context/quota thresholds are reused. Picked tiers and cost-based
small-task sizing emit no shortcut guidance: their existing routing rules decide. No quota or context probe is
added just for the shortcut. Unknown size does not imply small.

Commands, flags, JSON meanings, exit codes, refusal bypasses, acceptance checks, reviews and escalation rules
are retained. `ccx run` still follows its existing behavior when invoked; enabling guidance does not prove
that a model will follow it or preserve the same routing decisions.

Evidence: **engineering check**, not measured savings. The opt-in r5 arm `ccx3cand` enables the Stage 3
candidate switches plus this switch, and uses compressed instructions with the same delegation command,
check/review/wait/acceptance behavior. It is a prompt-and-config experiment. Its small branch has no
`small_self_run` ledger event; absent event evidence stays null/Unknown instead of inventing a decision.
The new `fresh2` split and historical overhead analysis are described in
[the delivery report](research/2026-11-05-lead-slim.md).
