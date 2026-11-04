- Keep completed hook hints at the existing deadline and move session-start archival to a windowless background
  worker with an OS lock and child reaping; preserve normal output, timeout defaults and exit codes.
- Read the ledger once per report invocation, including nested statistics, and cache unchanged Codex discovery
  headers in process. Keep JSON fields and all commands/options; add synthetic timings and exact output regressions.
