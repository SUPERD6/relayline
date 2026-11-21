- Docs (#497): round 2 pre-registration change log (EN + ZH) gets a 2026-11-20 entry with the full formal and development
  commands for A1, A2, A1x, A2x and B (`--tasks-sha256` for A, `--hide <everyday checkout>` for A and B plus one `--hide`
  per other worktree holding task folders for B, no `--claude-home` for A1x/A2x), the raw-byte SHA-256 of the six task
  files, and a pointer sentence after each earlier command. Mechanical completion only; thresholds, sample sizes and
  budgets are unchanged. `strength_retest.py execute -h` and `strength-tools` (EN + ZH) now state the same `--budget`
  ceiling as the code: min($10, units x $0.15) with `--tasks`, context $4 and memory $3 without it (help text only,
  behaviour unchanged).
