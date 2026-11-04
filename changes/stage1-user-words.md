- Add experimental, default-off `delegate.user_words`, an 8000-character configurable cap, and
  `ccx run --user-words-file` to carry sanitized original interface requirements alongside the lead's brief;
  reuse the snapshot on retries and resume without adding original text to the accounting ledger.
- Add opt-in `ccx2uw` evaluation arm with ccx2's unchanged lead instructions and flags, unit-local config
  readback, and `user_words_mode` telemetry. Evidence: engineering checks only; correctness benefit unknown.
  Existing commands, options, exit codes and verdict rules are preserved.
- Decode fake Codex/Claude prompt pipes explicitly as UTF-8, matching the runner's byte encoding even with
  Windows cp936 stdio; cover Chinese prompt artifacts, retry, resume and fallback under forced legacy stdio.
  Preserve already-decoded StringIO input supplied by runpy wrappers used in evaluation and review tests.
