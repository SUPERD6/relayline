- Before creating a worktree, fetch only the current branch's upstream with a 15-second timeout and warn when
  the local HEAD is behind; failed or timed-out fetches warn once and do not stop creation. Never pull or change
  the worktree's local HEAD base automatically.
- Add `worktree.fetch` (default `true`) and `worktree.fetch_timeout` (default `15` seconds), both settable through
  `ccx config set`; disabling fetch uses the cached upstream distance without a network request.
- Record `base_behind` when known, including zero, in `run.json` / `ccx show --full`; omit it without an upstream
  or after a failed fetch, and keep compact output unchanged. No existing command or option was removed.
