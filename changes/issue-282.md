- Fix `ccx verify --list` to work without `--sample`, returning a read-only `pending` list of unjudged runs.
  Add opt-in `--days`, `--project` and `--state` filters for listing and sampling; retain the seven-day default
  and existing `--sample N [--list]` JSON and interactive behavior. Engineering checks only; no real CLI evaluation.
  Reject listing combined with verdict arguments; resolve worktrees to their main project, handle missing/invalid
  paths, and compare project names without case on Windows. Retry record reads and expose an `unreadable` count.
