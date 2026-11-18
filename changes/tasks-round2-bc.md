- Evaluation (#375): round-2 B authored tasks, stage 0 and 1. `scripts/eval/round2_bc/build.py` builds one bare git
  repository per authored library (`round2-authored/<lib>`) deterministically (fixed author, committer and dates,
  text normalized to LF, so the commit SHAs are the same on every machine): the starting tree, then one commit per
  task on top of it; `check` exports each task in the `round2_tasks.py authored` layout and runs that check. Two
  standard-library-only starting libraries (`tabula`, delimited text tables; `cronlite`, cron schedules and a job
  registry) and the four B development tasks, frozen in `docs/research/data/round2-bc/b-dev.json` with their check,
  native validation and leak reports. C is moved to round 3 (maintainer, 2026-11-18).
