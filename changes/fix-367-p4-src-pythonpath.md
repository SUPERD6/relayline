- p4 evaluation: hidden-test scoring puts `src/` before the repository root on `PYTHONPATH` for tasks whose frozen
  selection says `src_layout: true`, matching round-2 task validation (#364); other tasks keep the root only. A
  round-2 dry run prints `src_layout_tasks` (#367).
