# Experimental quota relay

[中文](relay.zh.md)

Evidence: **engineering check**, fake CLIs and captured Claude event replay only.
Default: `[relay] enabled = false`. Existing delegation verdicts, JSON fields, commands and exit codes are unchanged.
This feature captures a handoff and explicitly starts a new lead at another vendor; it does not take over an open terminal or desktop conversation.

## Capture and continue

Run in the Git workspace (replace `SESSION_ID` with the source session id):

```text
ccx config set relay.enabled true
ccx sync --only hooks --apply
ccx relay capture --session-id SESSION_ID --goal "Finish the parser" --progress "Parser partly implemented" --next-step "Review diff and run parser tests"
```

`capture` stores session-scoped context for a later hook. Refresh it at useful milestones; it does not extract goals or progress from private transcripts.
The Claude `StopFailure` hook has matcher `rate_limit` and invokes `ccx relay capture --hook`.
It saves an atomic packet and a `.notification.json` file under the workspace's `.ccx/relay/`.
Packets include the explicit goal, progress, next step, source session, Git HEAD, bounded staged/unstaged diffstats, uncommitted file list and the continuation command. Full diff hunks are never stored.
Missing context is `Unknown`; a missing goal blocks continuation. Untracked files are listed, not copied. No private transcript is read.
Capture installs a local `.ccx/relay/.gitignore` to keep packets out of Git. File lists are capped at 200 entries (512 characters each), diffstats and context summaries at 4,096 characters each. Dirty-file fingerprints read at most 200 paths / 8 MiB within the snapshot deadline, store only SHA256, and skip private paths and outside symlinks. Hook capture keeps two seconds per Git command and six seconds for its snapshot. Manual capture/continue default to 30 seconds per Git command and 120 seconds per snapshot; `--git-timeout-seconds 60` raises these to 60/240 seconds. This setting also applies when a continuing lead saves another handoff. It does not change the model's wall-time budget or any configuration key. A timeout saves a minimal packet with an Unknown snapshot, reason and retry hint before notification. Unknown Git snapshots block continuation: inspect `git status`, recapture manually with a longer timeout, then continue with that timeout. Sub-agent hooks (`CCX_DEPTH > 0` or `CCX_ROLE=subagent`) are silent no-ops.

Stop the old session, its child tasks and its quota auto-resume wait first. Then use the packet id printed by capture:

```text
ccx relay continue PACKET_ID --to codex --budget-seconds 300 --old-stopped
ccx relay continue PACKET_ID --to codex --budget-seconds 300 --old-stopped --launch
```

Those stop instructions apply to confirmed quota handoffs (`state=quota_stopped`).
A bare StopFailure `rate_limit` instead saves `state=rate_limit_unconfirmed` and
notifies “可能只是限速，可以等一下或手动接续”, without recommending that the old session stop.
Inspect such a packet with `relay continue ... --to codex --budget-seconds 300`;
preparation needs neither force nor a stop attestation. Actual launch requires
explicit `--force-unconfirmed --old-stopped --launch`. Force does not bypass the
workspace lock, live-writer checks, Git reconciliation or budget. Old StopFailure
and rate_limit_event packets without `usage_confirmed=true` also require force.

The first command prepares a prompt and argv without launching a model. `--launch` explicitly starts supervised `codex exec --json --sandbox workspace-write` or `claude -p --output-format stream-json --verbose --permission-mode acceptEdits --permission-prompts none` in the same workspace. Claude's native file-edit permission mode is not an OS sandbox equivalent to Codex's sandbox; other tools can still be denied. No permission bypass is enabled. A zero exit without observable workspace changes reports `no_changes`, not success; verification remains `not-run`.
A zero child exit with Unknown change detection instead reports `changes_unknown`,
asks the person to inspect `git status`, and makes the ccx command exit 2. The saved
`exit_code` still describes the child, so it can remain zero in that record.
Claude Code **2.1.316 --help** was rechecked on 2026-11-05: `--permission-prompts none`
denies anything that would prompt, even with `acceptEdits`. Packets have no exact,
trusted check-command field, so relay adds no `--allowedTools` grants. Its Claude
prompt explains native edit permission, possible Bash/PowerShell/test denial, and
requires exact blocked commands plus `not-run` tests if checks cannot execute.
The budget is a required positive, finite **wall-time limit in seconds**, not a dollar ceiling. Dollar accounting/caps for this new-lead path are **Unknown / not implemented**. Native CLI child-task spending is not bounded separately.
Before either preparation or launch, ccx checks staged/unstaged diffstats, HEAD and current status. A changed HEAD requires manual reconciliation and a fresh packet. A changed dirty workspace is reported to the new lead for inspection, never reset.
The new lead is told to inspect partial work and run relevant checks before editing. This instruction is not proof the model obeys it; `verification` stays `not-run`.
The supervisor records argv, prompt, PID, exit code and stdout/stderr logs locally; budget expiry stops the child process tree and retains partial files.
An explicit quota refusal in the new lead's output also saves a fresh handoff and notification, even with exit code zero; it never launches another vendor automatically.
An exclusive durable packet claim prevents duplicate launch, while a workspace-wide lock prevents different packets launching together. Locks record PID/time; stale locks require manual orphan-process reconciliation. Failure to spawn releases both claims. Before launch ccx checks known live run PIDs in the same Git workspace (including subdirectories). Native processes without ccx records and native auto-resume remain Unknown: `--old-stopped` is still a required user attestation, not proof that all writers stopped. Killing the supervisor externally may leave its CLI alive; there is no watchdog or automatic recovery.

## Signals and native overlap

`ccx/quota_signals.py` prioritizes protocol evidence: rejected known usage windows and explicit `usage_limit_reached` or usage-limit wording in error envelopes. StopFailure and rejected rate_limit_event signals without that evidence remain `rate_limit_unconfirmed`; a reset time or requests-per-minute limit alone does not confirm exhausted quota. Authentication/transport/billing errors, normal usage readings and arbitrary tool/user/model prose do not count as quota. Existing delegation quota classification remains unchanged.
Claude fixtures in `tests/data/real_signals` are captured and redacted. **Codex quota samples are synthetic**, not a captured real refusal.

Checked on 2026-11-05: `claude --version` / `claude --help` = **2.1.316**; `codex --version` / `codex exec --help` = **0.164.0**. No real model was invoked.

* [Claude hooks reference](https://code.claude.com/docs/en/hooks#stopfailure): StopFailure output and exit code cannot continue the turn. The implemented terminal bell uses the documented `terminalSequence` exception; it is ignored in `-p`/SDK sessions. The file notification remains available.
* [Claude settings reference](https://code.claude.com/docs/en/settings-reference#autocontinueatusagelimit): native `autoContinueAtUsageLimit` waits for the same account's reset and resumes automatically (default true, since 2.1.234). This overlaps with waiting/recovery, not cross-vendor handoff. ccx does not edit that setting. Stop the native wait before switching vendors to avoid two writers. Exact `quota_auto_resume_*` Notification matcher names were not found in the official pages fetched in this check: **Unknown**.
* [Codex non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode): `codex exec --json` exposes events for a separately supervised session. The fetched [Codex hooks reference](https://learn.chatgpt.com/docs/hooks) did not establish an equivalent quota StopFailure hook: **Unknown**. No Codex quota hook is installed.

## One-minute desktop check (2026-11-05; pending user verification)

1. Enable relay and apply hook sync as above in a disposable Git project. The desktop Code tab does not support `/hooks`, so check registration in one of two ways: (a) run interactive `claude` in a terminal and type `/hooks`; or (b) read `hooks.StopFailure` in `~/.claude/settings.json` (the desktop app and the CLI share this file). Either way, look for matcher `rate_limit` → `ccx relay capture --hook`. Open a fresh desktop session afterwards so it picks up the file.
2. If a normal session is already at its natural usage limit, submit one harmless prompt. Look for a new `.ccx/relay/*.notification.json` and its packet. Confirm the packet names the desktop session, HEAD and dirty files. If no limit is present, stop after checking hook visibility: real desktop event delivery remains **Unknown**; do not spend tokens to exhaust quota.
3. Stop the old session and its automatic resume. Use `relay continue ...` without `--launch` to inspect the prepared handoff in the other direction.

2026-11-10: a simulated StopFailure event fed to the hook command (stdin) wrote `.ccx/relay/*.notification.json` (state `rate_limit_unconfirmed`). Desktop hook execution on a real usage limit and notification visibility are still **Unknown**. This check can verify hook registration immediately; actual rate-limit delivery needs an already limited session and is not promised within one minute.

To disable: `ccx config set relay.enabled false`, then `ccx sync --only hooks --apply`. A stale installed capture hook is also a silent no-op while disabled. Uninstall removes only ccx's relay handler and preserves other handlers.
