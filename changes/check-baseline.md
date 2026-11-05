- Add experimental `[check] baseline = "on_fail"` (default `"off"`): compare complete failing case lists against a
  clean dispatch-time Git checkout with saved original file bytes (including LF/CRLF), stop check repair/escalation
  for baseline-only failures, and restrict repair
  prompts to new cases. Unknown comparisons keep existing behavior; no commands, options or default verdicts removed.
- Retain bounded stdout/stderr paths for every acceptance check and baseline check, plus baseline elapsed time in
  run records and baseline details in receipts, including merged batches' per-piece checks. Validated with fake
  CLIs and temporary Git repositories only.
