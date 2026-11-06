# Attempt time limits and partial receipts

English · [中文](timeouts.zh.md)

`ccx run` and `ccx resume` already use `defaults.timeout_sec` for each CLI attempt, including retries.
The default remains **1800 seconds (30 minutes)**. It is not a total budget for all attempts, checks and reviews.
Change it through the existing configuration command; subsequent attempts read the setting when their run starts:

```sh
ccx config set defaults.timeout_sec 2400
ccx config get defaults.timeout_sec
```

On a timeout, the receipt adds `timeout_context` to that attempt. Only when the final run kind is `timeout` does it
also appear at the top level of the run record and the result shown by `run`, `resume` and `show`. A successful retry
keeps the earlier timeout evidence inside its original attempt, without a top-level timeout field.
Existing status, kind, exit codes, `result` and `files_changed` meanings stay unchanged.
In particular, the existing `files_changed` still contains the worker's structured report, when available.

| New field inside `timeout_context` | Meaning |
|---|---|
| `files_changed` | Actual paths relative to the Git root, from `git diff --name-only` against the existing snapshot and `git ls-files --others --exclude-standard`. No diff bodies or untracked file contents are read. Includes tracked edits/deletions and newly untracked files; excludes pre-existing changes and `.ccx/`. Works in both a worktree and the original checkout. `null` means Unknown when no Git snapshot is available or Git evidence cannot be collected. |
| `last_assistant_message` | Last nonempty assistant text in the captured CLI JSON event stream. For messages longer than 4000 characters, retain the last 4000, where the partial result usually appears. Tool output, reasoning and errors are excluded. `null` means no assistant message was captured (Unknown). |
| `last_assistant_message_truncated` | Whether the captured message exceeded the character limit. |

The existing `diffstat` still summarizes changes. Partial files stay in place for inspection and `ccx resume <run_id>`;
the additional evidence does not turn a timeout into success. Git evidence has the same limits as the existing
snapshot logic (for example, ignored files are excluded). No recursive filesystem inventory is performed outside Git.

## Optional reminder (experimental)

```sh
ccx config set defaults.timeout_reminder true
# Restore the default:
ccx config set defaults.timeout_reminder false
```

Default **false** preserves existing prompts. When enabled, each attempt's prompt states its configured limit in
minutes and seconds and asks the worker to write a partial result (changes, checks, next step) as the limit approaches.
This also applies to resumed sessions and retries. This is an **up-front instruction**, not a timed notification:
ccx does not inject a new message into a running CLI. Support for runtime injection is **Unknown** here, and worker
compliance with the reminder is **Unknown**. A CLI killed before emitting any assistant text has no recoverable message.

Evidence: **engineering check** only, using fake CLIs with a one-second limit; no real-agent run or measured benefit.
All commands/options and existing timeout classification rules are retained.
