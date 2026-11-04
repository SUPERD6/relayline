- Accept or reject several memory suggestion IDs in one command, returning per-ID results and continuing past
  missing or already handled IDs with a nonzero exit code. Single-ID output fields and all existing commands and
  options are preserved; `accept --text` / `--topic` with several IDs fails before any writes.
- Mark unhandled suggestions older than `memory.suggest_expire_days` as expired when read (default 14 days;
  0 disables expiry). Keep their records for deduplication, omit them from pending lists and session-start hints,
  and include an `expired` count in `ccx mem suggestions`.
- Cover batch processing, single-ID compatibility, override validation and fixed-clock expiry through subprocess
  CLI tests outside the repository; document the commands and setting in English and Chinese.
