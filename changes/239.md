- A fresh run's first message now opens with ccx's fixed rules; the run id, the lead and the workspace come after
  them (`ccx run id: <id>; lead: <who>`), so runs in the same folder start with the same ~700 characters (about 200
  tokens) a provider's prefix cache can reuse (P0-11 item 4). Small and not measured: Claude sub-agents and
  `--worktree` or cross-folder Codex runs gain nothing (their requests differ before ccx's text). `[ccx sub-task`
  still starts the message; a sub-session's title in Claude Code's resume list no longer shows the run id.
