- Evaluation (#442): `scripts/eval/round2_tasks.py prepare` no longer reports a pinned kept dependency as installed
  when its download produced no file of the package (it now says `installed: false` with the reason; a pin installed
  from files an earlier run left after a failed download carries a warning). A run where pytest's pin download failed
  had shown pytest as installed, and every candidate's baseline then failed with "No module named pytest"; that
  round-2 B/C selection is void, and prepare and select must be run again. The output gains `runner_missing`, decided
  by actually importing pytest in `--ext-python` (pip list is only the record); `prepare` exits 1 when it is not
  empty, and `select` checks the import before it starts. The command also prints how many project downloads,
  dependency-group requirements and installs failed. pip itself is never pinned or reinstalled (`NEVER_PIN`).
