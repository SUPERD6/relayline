- `ccx run --worktree --base head|upstream` and `[worktree] base = "head"` (#336): `upstream` starts the worktree
  from the current branch's `@{upstream}` (`--no-track`); no upstream or a detached HEAD falls back to HEAD with a
  note. Default unchanged (`head`). When HEAD trails the upstream, the warning now also names `--base upstream`;
  `ccx run --bg --worktree` says it before detaching (stderr and `base` in the receipt), not only in the log and the
  later recap. Records of `--base upstream` runs add `worktree_base` / `base_ref` (`local_ahead` when local commits
  are left out). No option removed; no new network request (the existing `[worktree] fetch` refresh is reused).
