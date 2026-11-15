- `--worktree` write runs: sub-agents are told not to commit "even if the task says to" and to leave their changes
  uncommitted (first prompt and same-session continue). Codex's workspace-write sandbox cannot write a worktree's git
  directory (`index.lock` refused), so a brief asking it to commit used to end with a dirty worktree and a sub-agent
  asking the lead to commit (#334). The receipt now has `commit`: `state` (uncommitted / committed), the uncommitted
  `files` (up to 20, `.ccx/` left out) and `next` (commit them yourself, or `ccx autonomy merge <id>`); `note` flags a
  sub-agent that committed anyway. The run record keeps `commit_state`. Codex's sandbox is not widened (no
  `--add-dir`, no `writable_roots`). Kept: every command and option; `ccx autonomy merge` still commits a worktree's
  uncommitted work before merging (`tests/test_merge.py` unchanged and passing).
