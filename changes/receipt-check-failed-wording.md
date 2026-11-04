- Show `outcome=check_failed` or `outcome=check_broken` in receipts when the external check did not pass,
  and explicitly label self-checked recaps as not independently verified. Ordinary successful recaps,
  JSON `ok` values, exit codes, verdict rules and merge gates are unchanged.
- Include the failed or broken check outcome in terminal summaries even when the worker reports `done`;
  keep the existing inspection or repair hint instead of suggesting a positive verdict.
