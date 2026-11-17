- `ccx run --dry-run` (#379): shows the rungs a run would try, `planned_first_rung` (routing's pick), `first_rung`
  (where it starts) and `rung_why` (one reason each for vendor, model and effort, from the signals the pick used,
  plus `changes` when the start moved before running); runs nothing and writes nothing. Real runs record
  `planned_first_rung`, `actual_first_rung` (the first rung that really took the task: capacity, quota and
  missing-model switches do not count) and `rung_why`; the one-line result adds the two rungs only when they
  differ. No default and no pick changed.
