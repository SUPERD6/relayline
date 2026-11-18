- strength evaluation (`strength_retest.py` / `strength_runner.py`): every unit is now denied the checkout the run
  starts from, its `scripts/eval/` and `docs/research/data/`, the `--tasks` file, the person's homes and hub, and each
  new `--hide PATH` (repeatable; resolved, de-duplicated, a missing path or one holding the units' Python refused),
  in every spelling (as given, resolved, 8.3 short name). Claude units get Read/Edit deny rules; Codex units cannot be
  confined and are audited. Each unit's tool calls are audited (`path_audit`: forbidden paths, content patterns such
  as `round2_a`, a `cd` or recursive search above the unit, a search of a forbidden path's parent); a hit makes the row
  invalid or stops the default group. `--out` inside a denied folder is refused. Dry runs with `--tasks` or `--hide`
  print an `isolation` field. Default behaviour changed: before, units could read the round-2 A tasks' generators and
  hidden tests (#454).
