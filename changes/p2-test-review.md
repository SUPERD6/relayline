- Add experimental opt-in task-derived test review (`review.mode=tests`), real unittest execution, failure evidence,
  and explicit Unknown outcomes; preserve read-review prompts, legacy trigger settings, commands and exit codes.
- Add an offline-first pg3b replay audit with pinned reconstruction, budget reservations, hidden-material separation,
  denominator-preserving metrics, and the opt-in r5 `ccx2rt` arm. Real evaluation remains not run.
- Preserve original task text through run records, resumes and replay jobs (`--user-task-file` for a separate original),
  and give generated test subprocesses only an allowlisted runtime environment rather than parent credentials.
- Route test-method runtime exceptions through failure confirmation; audit the main checkout's saved pg3b data,
  mark report-based receipt inference, reuse named local exercise caches, and filter binary cache diff blocks.
- Accept `polyglot-benchmark.git` cache names, explicitly decode pin-check subprocess output as UTF-8, and retain
  the exact opt-in arm assertion with `ccx2rt` added.
