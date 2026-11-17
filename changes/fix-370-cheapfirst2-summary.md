- `scripts/eval/unified_summary.py p4` now prints the `dispatch` block (escalation rate, first-rung and escalation
  spend, status, stop_reason) for round 2's `ccxcheapfirst2` arm as well, as pre-registration section 4 asks for
  group B; that arm's stop_reason has no escalation-rate stop (it runs with `--max-escalation-rate none`).
  `ccxcheapfirst` output is unchanged (#370).
