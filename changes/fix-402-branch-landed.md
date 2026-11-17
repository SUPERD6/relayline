- `ccx q accept` / `ccx q ls`: whether a worktree piece is already in the checked-out branch now looks at the commit
  its worktree has checked out (and at its run's branch when that exists), not only at `ccx/<run>`: a resumed piece
  merged by hand no longer shows up as ready again, and new commits on a detached worktree are no longer taken for
  landed. When the run's branch cannot be named and the worktree is off `ccx/*`, it still reads as not landed.
  Uncommitted changes are not looked at (squash and cherry-pick merges: see #413); with the worktree gone, the old
  fallback stays (#402).
