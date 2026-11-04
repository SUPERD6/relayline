- Accept or reject several memory suggestion IDs in one command, returning per-ID results and continuing past
  missing or already handled IDs with a nonzero exit code. Single-ID output fields and all existing commands and
  options are preserved; `accept --text` / `--topic` with several IDs fails before any writes.
- Mark unhandled suggestions older than `memory.suggest_expire_days` as expired when read (default 14 days;
  0 disables expiry). Reads compute expiry in memory without writing the table; existing add/accept/reject writes
  also persist computed expiry. Keep records for deduplication, omit expired suggestions from pending lists and
  session-start hints, and include an `expired` count in `ccx mem suggestions`. Invalid expiry settings warn once
  and fall back to 14 days; persisted expired suggestions never become pending again.
- Cover batch processing, single-ID compatibility, override validation and fixed-clock expiry through subprocess
  CLI tests outside the repository; document the commands and setting in English and Chinese.
