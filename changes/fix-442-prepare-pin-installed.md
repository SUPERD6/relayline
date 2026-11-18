- Evaluation (#442): `scripts/eval/round2_tasks.py prepare` no longer reports a pinned kept dependency as installed
  when its download produced no file of the package (it now says `installed: false` with the reason); a run where
  pytest's pin download failed had shown pytest as installed, and every candidate's baseline then failed with "No
  module named pytest". The output gains `runner_missing`, and the command exits 1 when pytest is not in
  `--ext-python`. pip itself is never pinned or reinstalled (`NEVER_PIN`).
