- Eval: new read-only `scripts/eval/ledger_replay.py` (#380), standard library only. From a ledger (`--ledger` /
  `--hub`, optionally the hub's `run.json` records and scored result rows joined by label) it reports, per task
  category and first rung, the judged right rate (final and on the first rung) with a Wilson 95% interval and n, the
  mean `ae_usd`, and the calibration of task-routing's `p` / `chain_p` against what happened (gap and Brier score).
  The first rung is read from `actual_first_rung` when a row has it (#379), else `first_rung`, else `rungs[0]`. An
  optional `--rule` (a rung per category) gives that rule's estimated right rate and cost only where the history has
  at least `--min-n` judged runs for that cell; the rest is marked unsupported. Small samples and non-randomized
  history are flagged. Reads only the files named; refuses paths under `eval-codex-home`; no default changes.
