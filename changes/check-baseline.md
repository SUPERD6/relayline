- Add experimental `[check] baseline = "on_fail"` (default `"off"`): compare complete failing case lists against a
  clean dispatch-time Git checkout with saved original file bytes (including LF/CRLF), stop check repair/escalation
  for baseline-only failures, and restrict repair
  prompts to new cases. Unknown comparisons keep existing behavior; no commands, options or default verdicts removed.
- Retain bounded stdout/stderr paths for every acceptance check and baseline check, plus baseline elapsed time in
  run records and baseline details in receipts, including merged batches' per-piece checks. Validated with fake
  CLIs and temporary Git repositories only.
- Add default-on check output retention even with baseline comparison off: `stdout_path`, `stderr_path`,
  `stdout_truncated`, `stderr_truncated`, and `failed_cases` are additive fields. Each check writes up to
  2 × 256 KiB (stdout and stderr); `tail` is unchanged. Receipts also add the default `headline` display field.
- Preserve full bracket-paired parametrized case IDs and reject unbalanced IDs as Unknown. Remove source-tree
  PYTHONPATH entries from baseline checks and record actual Python `import_origins`; unobservable imports or
  imports from the source tree cannot establish baseline-only failures.
- Document that `check_baseline_failed`, like `check_failed`, has `ok=true` and CLI exit code 0: scripts must
  inspect acceptance fields rather than rely on process exit alone.
