- Evaluation (#375, B part): 8 final authored B tasks on the `cronlite` starting library, `r2b-cronlite-1` ... `-8`
  (`source: "authored"`, author model Opus 5.5), in `scripts/eval/round2_bc/cronlite/tasks/`: job tags and pausing
  kept by the store; `L` for the last day of the month; time windows that honor blackout calendars with a deferral
  limit; flapping alerts and stricter, calendar-aware missed runs; UTC calendar export and an `ical` command; a
  registry `check` command with a `retry-overlap` warning; day/weekday full lists following the either rule; load
  estimates following each job's overlap policy. The starting tree is unchanged and the development task SHAs stay
  as frozen. Checks in `docs/research/data/round2-bc/b-formal-cronlite-{build,check,native,leak}.json`: two builds
  give the same SHAs; `build.py check` 8/8 valid (hidden tests fail on start, pass on the reference, the whole suite
  passes on the reference); P4-native validation 8/8; leak/similarity clean (highest ratio 0.32). The tasks are not
  merged into a final task file yet. No model was called.
