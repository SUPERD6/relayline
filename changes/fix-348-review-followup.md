- Evaluation: `round2_tasks.py` follow-up from the independent review of #356: commits that change test support files
  (conftest, helpers, data) or delete/rename a test are excluded with that reason; `prepare` installs no kept
  package (not only the task's own), so `env-check` cannot fail through another repository's dependencies; src-layout
  repositories get `src/` on `PYTHONPATH` during round 2 validation only (P4/P5 unchanged); `repos`/`select` leave
  their own outputs out of the earlier-task corpus; the brief corpus also reads long `prompt`/`task`/`instruction`
  text; literals outside asserts are listed for review; the manifest skips `.git` and `__pycache__`.
