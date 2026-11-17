- `ccx q accept` / `ccx q ls`: whether a worktree piece is already in the checked-out branch now looks at the commit
  its worktree has checked out (and at its run's branch when that exists), not only at `ccx/<run>`: a resumed piece
  merged by hand no longer shows up as ready again, and new commits on a detached worktree are no longer taken for
  landed. With the worktree gone, the old fallback stays (#402).
