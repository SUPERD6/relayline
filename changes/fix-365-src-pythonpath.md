- Evaluation: round-2 B/C runs put `src/` before the root on `PYTHONPATH` for a task selected with `src_layout`
  (#365), as `round2_tasks.py` validated it: `p4_long_session.py` sets it per task for the lead, its sub-agents and
  the acceptance check (and says so in the lead prompt), and `long_environment.validate_task` (the
  `--validate-native` pre-check) reads the task's `src_layout`. Other tasks keep the root only and an unchanged
  prompt; hidden-test scoring is #367.
