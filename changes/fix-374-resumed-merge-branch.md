- Fixed (#374): `ccx autonomy merge` (and the L2 auto-merge after a run) named a resumed run's branch
  `ccx/<its own run_id>`, but a resume works in the first run's worktree, whose branch is `ccx/<first run_id>`:
  the dry run found nothing to count and `--apply` failed, for `--base head` and `--base upstream` runs alike. The
  branch is now the one the worktree has checked out, accepted only when it is `ccx/<id>` of the run or of a run up
  its resume chain; a worktree that is detached or was moved to another branch is refused (`the worktree is on X,
  not ccx/<id> ...`) instead of committing to one branch and merging another. Runs that were never resumed merge as
  before.
