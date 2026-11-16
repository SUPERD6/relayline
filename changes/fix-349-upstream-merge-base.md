- Fixed (#349): a `--base upstream` worktree run merged back with `ccx autonomy merge` counted the upstream's new
  commits as its own lines/files (the merge-base with a trailing local branch is the local tip), and `--apply` /
  `ccx q accept` merged those commits in too, an implicit pull. The count now starts from the run's `base_sha`
  (or that of the run it resumed), and both commands refuse while the local branch is behind that commit:
  `<branch> is N commit(s) behind <upstream> ... pull first`. `--base head` (the default) is unchanged.
