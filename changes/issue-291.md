- Preserve credential guard evidence per attempt across capacity fallback; include weakest-state summaries and
  pre-launch `credential_guard_warnings` in receipts when enabled, while leaving disabled receipts unchanged.
  Keep guard warnings and non-Pass status visible with the lead's line-output preference; top-level mechanism
  and rules-added evidence describe the weakest attempt, not the entire run. Fixes #291.
