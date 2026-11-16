- The one-line lead view (`output.lead = line`) now keeps a compact `commit_state` for a clean `--worktree` run
  (state, next, any note, the first 5 files plus a count) and adds "N files uncommitted, see commit_state.next" to
  the recap, so a run with a passing `--check` no longer hides that its work is uncommitted (#350).
