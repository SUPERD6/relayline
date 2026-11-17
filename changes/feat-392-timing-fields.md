- Run records and the ledger keep handover timings (#392), added only: per attempt `started_at`, `first_event_at`
  and `startup_seconds` (CLI launch to its first event, monotonic clock); per check `check_started_at` and
  `check_seconds`, passed checks too (before, only a failed one kept `check_seconds`); a recorded review's
  `started_at`, `ended_at`, `seconds` and `background`. Ledger rows add `startup_seconds`, `check_seconds`,
  `check_timing` and `review_timing`. `scripts/eval/handover_overhead.py` uses them for the startup and the
  check/review wall time (a background review that overlaps the check counts once) and subtracts startup from the
  agent's wall; rows written before stay `Unknown`. The check's own `seconds` now come from a monotonic clock.
  Receipts (one line and whole result) and defaults are unchanged.
