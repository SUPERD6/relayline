- Eval: new read-only `scripts/eval/routing_calibration.py` (#429), standard library only, reusing `ledger_replay.py`
  (same inputs, same outcome rule: a scorable result row's `ok`, else the last non-probable `verify`). By task-size
  signal (`b`, files, minutes, band, coupling, clarity; a missing signal is its own bucket, never guessed) it reports,
  for "self" (`selfrun` samples, outcome = the person's `ok` flag) and "delegated" (ledger runs), the right rate with
  k, n and a Wilson 95% interval, cost, wall time, and per bucket a Newcombe-interval comparison (verdict
  `insufficient` below `--min-n` judged runs per arm). From the ordered buckets it gives a threshold candidate
  (`self_ok_up_to`, `delegate_better_from`; null = Unknown). Eval and real use are separate strata. Reads only the
  files named; refuses paths under `eval-codex-home`; changes no default (`small_self`, `routing.default` untouched).
