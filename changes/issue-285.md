- Preserve actual changed paths and the last assistant event in timeout receipts for worktree and original-checkout runs.
  Reuse `defaults.timeout_sec` (still 1800 seconds) and add experimental `defaults.timeout_reminder = false` for an
  up-front partial-result reminder, without changing existing receipt fields, timeout verdicts or exit codes.
- Keep timeout evidence in its original attempt after a successful retry; expose it at the top level only for a final
  timeout. Collect changed paths without reading diff bodies or untracked file contents, and retain the final 4000
  characters of long assistant messages. Cover timeout recovery, large files and incomplete JSON events with fake CLIs.
