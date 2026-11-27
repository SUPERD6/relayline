- eval(p4): a row whose sub-agent never started ("could not start <agent>", e.g. WinError 206) is now invalid
  (`invalid_reason` = `subagent_start_failed`, field `start_failed`) and counts toward `--max-invalid-rows`: the group
  stops once more than that many such rows exist (event field `start_failed_rows`). A receipt that is merely missing or
  says error stays `receipt_error` and is not capped (Fixes #586).
- eval(unified_summary): `p4` counts `arms.<arm>.valid` with the same rule as `--paired` and P4's own summary
  (`invalid_reason`, `receipt_error`, `environment_error`), so cost ratios no longer mix in start-failed rows.
- Difference from the round-2 prereg (not a retro edit): the registered stop list (section 0: a, b, c, d) has no cap on
  start failures; this adds one for the rerun, with the same limit (3). Registered verdict rules are unchanged.
