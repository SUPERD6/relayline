- Fixed (#384): `ccx q accept` merged the branch name the queue noted when a piece's run ended. A detached worktree
  was noted as the literal `HEAD`, so accept merged `HEAD` into the project itself ("Already up to date") and
  marked the piece accepted with nothing landed; a worktree moved to another branch got its edits committed there
  while the old branch was merged; a resumed piece with no noted branch tried `ccx/<its own run_id>`, which does not
  exist. Accept now uses the same check as `ccx autonomy merge` (#374, `autonomy.run_branch`): it merges the branch
  the worktree has checked out, only when that is `ccx/<id>` of the piece's run or of a run up its resume chain,
  and refuses a detached or moved worktree with the reason. A piece noted as `HEAD` is no longer taken for already
  landed. Pieces on their own run's branch (`--base head` or upstream) land as before.
