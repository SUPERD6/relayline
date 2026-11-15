- Add experimental `check.sensitivity = "off" | "warn" | "escalate"` (default off), reusing dispatch-time baseline
  snapshots to detect checks that already passed before the change or retain identical pytest failures.
  Record sensitivity, fixed cases and baseline wall time; insensitive receipts ask the lead for a requirement test.
  Opt-in `escalate` advances an unverified cheap-first result to the requested rung within existing limits;
  `--no-escalate` retains the original rung and returns the hint. Existing commands, options and defaults remain.
  Pass-to-fail regressions stay unknown and retain failure output; unverified retries verify against the task text,
  and identical-failure retries identify pre-existing cases without focused failure repair.
