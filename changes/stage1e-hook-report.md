- Keep completed hook hints at the existing deadline and move session-start archival to a windowless background
  worker with an OS lock and child reaping; preserve normal output, timeout defaults and exit codes.
- Read the ledger once per report invocation, including nested statistics, and cache unchanged Codex discovery
  headers in process. Keep JSON fields and all commands/options; add synthetic timings and exact output regressions.
- Serialize archival with resume restoration and running-state publication, skip active sessions, bound external
  archive commands to 30 seconds with child cleanup, and resolve relative hub paths before launching workers.
- Reuse process-group/tree cleanup for archive timeouts, including Windows command wrappers; avoid waiting again
  on descendant-owned output pipes after timeout.
- Keep resume best effort when the archive lock budget expires, recording `archive_restore_lock_timeout` in the
  run record; retain existing cleanup/retry assertions while scoping their fake to the archive command.
