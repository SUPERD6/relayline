- Evaluation (#515): P4 (`p4_long_session.py`) now records the between-units check made right after each unit on that
  unit's row, as r5, batch and p13 already did. Before, every episode was closed with the last check, so one outside
  pytest seen after the last unit marked every earlier, already finished row `env_clean = false` (round-2 B dev
  rerun `r2-dev-b2`: 8 of 8 rows, where only the last one overlapped). The environment stop is unchanged. A row whose
  check never ran because the run broke records "between-units check did not run after this unit" and is not clean.
