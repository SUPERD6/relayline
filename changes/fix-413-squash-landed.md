- `ccx q accept` / `ccx q ls`: a worktree piece whose work was landed by squash, cherry-pick or rebase (new commits,
  so not an ancestor) now counts as already in the checked-out branch, so it no longer shows up as ready again or
  gets an empty `merge --no-ff`. A branch that is not an ancestor counts when merging it would change nothing
  (`git merge-tree --write-tree`, git 2.38+) or when every one of its commits has an equal patch there (`git cherry`).
  A piece only part of whose commits landed, or whose landing was reverted, still reads as not landed; so does a
  squash whose files changed again afterwards (the conservative side) (#413).
