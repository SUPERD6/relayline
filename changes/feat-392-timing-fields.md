- Run records and the ledger keep handover timings (#392), added only: per attempt `started_at`, `first_event_at`
  and `startup_seconds` (CLI process launch to its first stdout line, monotonic clock: process start-up, not the
  first model request); for each attempt's last check `check_started_at` and `check_seconds`, passed checks too
  (before, only a failed one kept `check_seconds`); a recorded review's `started_at`, `ended_at`, `seconds` and
  `background`. Ledger rows add `startup_seconds`, `check_seconds`, `check_timing` and `review_timing`.
  `scripts/eval/handover_overhead.py` uses them for the startup and the check/review wall time (a background review
  that overlaps the check counts once) and subtracts startup from the agent's wall (a summary mixing rows with and
  without startup keeps it in every unit); rows written before stay `Unknown`. `scripts/eval/r5.py` (`phase_wall`)
  and `r5_timeline.py` (`run_parts`) no longer count the final check twice now that it is also on the last attempt
  (also fixes the same double count in old check-baseline records). The check's own `seconds` now come from a
  monotonic clock. Receipts (one line and whole result) and defaults are unchanged.
