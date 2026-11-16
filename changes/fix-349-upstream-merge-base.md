- Fixed (#349): a `--base upstream` worktree run merged back with `ccx autonomy merge` counted the upstream's new
  commits as its own lines/files (the merge-base with a trailing local branch is the local tip), and `--apply` /
  `ccx q accept` merged those commits in too, an implicit pull. The count now starts from the run's `base_sha`
  (or that of the run it resumed), and both commands refuse while the local branch lacks that commit:
  `<branch> is missing N commit(s) that this run started from ... pull first` (a diverged branch is told to bring
  the upstream in with `git pull --rebase` or `git pull`). A resume chain that breaks (record missing or unreadable,
  a loop, over 20 resumes) is refused with `cannot tell where this run started` instead of falling back to the
  merge-base. `--base head` (the default) is unchanged.
