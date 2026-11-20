- Evaluation (#375): the round-2 B task set is frozen in `docs/research/data/round2-bc/b.json`: 42 upstream tasks
  (pre-registration section 2, B) and 18 authored ones (`r2b-tabula-1..10`, `r2b-cronlite-1..8`), each with its
  `source`, plus the four authored development tasks. `selection-b.json` merges the full upstream select of
  2026-11-18 with its resume over the 51 repositories whose `git log` failed transiently (resume scripts included,
  replayed candidates listed); one upstream task (networkx Leiden) is marked excluded because its hidden assertions
  compare partitions from fixed seeds that no brief can cover. `b-upstream-briefs.json` and `b-trace.json` hold the
  upstream briefs and their per-assertion traces; `b-check.json`, `b-leak.json`, `b-env.json` and
  `b-manifest.json` are the authored check, leak check, environment check and SHA-256 list; `selection-env/` keeps
  the top-pypi snapshot, repository list, prepare output and pip list the selection used.
  `scripts/eval/round2_bc/freeze.py` regenerates the merged selection and the task file. `round2_tasks.py leak` now
  records the files it left out of the corpus (`excluded_from_corpus`).
