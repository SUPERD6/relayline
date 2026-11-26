- Relay (#523): the session-start hook (`ccx mem delta`, both tools) adds one plain-text line when the workspace has an
  unfinished relay packet from the other tool (no `continue-*` record yet): packet id, one-line goal, the
  `ccx relay continue` command and a reminder to confirm the old session is stopped. Read-only; nothing is launched.
  Off with `relay.enabled` (default false): then, and with no packet, the hook prints nothing extra. Checked against
  the hooks docs (Claude Code 2.1.316, codex-cli 0.164.0); fake-CLI tests only, no real-run recording yet.
