- Evaluation (#375): round-2 B authored tasks, stage 0 and 1. `scripts/eval/round2_bc/build.py` builds one bare git
  repository per authored library (`round2-authored/<lib>`) deterministically (fixed author, committer and dates,
  no system or user git configuration, text normalized to LF, so the commit SHAs are the same on every machine): the
  starting tree, then one commit per task on top of it; `build --dev-out` writes the frozen development task file
  byte for byte, and `check` exports each task in the `round2_tasks.py authored` layout and runs that check. Two
  standard-library-only starting libraries of about 1500 source lines each (`tabula`, delimited text tables: reading,
  writing, kinds, queries, joins, grouping, statistics, validation, diffs; `cronlite`, cron schedules: parsing,
  next runs, a job registry, descriptions, phrases, blackout days, windows, offsets, overlap, run history, alerts,
  load, lint, storage, iCalendar, a CLI) with their own test suites, and the four B development tasks, frozen in
  `docs/research/data/round2-bc/b-dev.json` with their check, native validation and leak reports. C is moved to
  round 3 (maintainer, 2026-11-18).
