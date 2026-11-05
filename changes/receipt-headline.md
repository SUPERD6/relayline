- Add a first-field headline to serialized compact receipts, including P4 execution-ok receipts whose checks failed,
  while preserving existing JSON meanings, commands, options, verdict defaults and exit codes. Document execution versus
  acceptance and audit all eight historical P4 lead responses without changing their results or evaluation protocol.
- `headline` is a new default-on display field, not a new verdict. Default check logging also adds `stdout_path`,
  `stderr_path`, `stdout_truncated`, `stderr_truncated`, and `failed_cases`, writing at most 2 × 256 KiB per check
  even when baseline comparison is off; existing `tail` remains unchanged.
