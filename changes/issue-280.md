- Add `git_pending` receipts for unresolved markers, unmerged paths and unfinished merge/rebase/cherry-pick steps.
  Experimental `git.auto_stage_resolved` (default false) lets the parent stage marker-free resolved conflict paths,
  never commit; preserve existing commands, options, JSON meanings, verdicts and exit codes.
- Restrict staging to UU/AA conflict paths changed since dispatch, leaving modify/delete and untouched conflicts
  for manual review. Bound conflict-only reads to 4 MiB, avoid heading/image false alarms, and record invalid
  staging configuration without losing receipts. Recheck only each candidate path before staging.
- Exercise changed, marker-bearing UU paths with dispatch snapshots; document that conflicts created during
  execution remain manual and that a standalone seven-equals line can conservatively be flagged as a marker.
