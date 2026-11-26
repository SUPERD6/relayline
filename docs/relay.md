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
Packets include `captured_at` (UTC ISO 8601, fixed form `YYYY-MM-DDTHH:MM:SSZ`, the time capture started, before the Git snapshot is taken; packets saved before this field exists simply lack it and still load). Its meaning depends on who captured: for a `StopFailure` hook it approximates the quota event time (off by a few seconds); for a manual `ccx relay capture` it is when the person ran the command; when a continuing lead hits a limit and saves another handoff it is after that lead ended. To judge a time limit such as "continued within N hours of the event", separate packets by `source` / `quota_signal.source` first, the explicit goal, progress, next step, source session, Git HEAD, bounded staged/unstaged diffstats, uncommitted file list and the continuation command. Full diff hunks are never stored.
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

The first command prepares a prompt and argv without launching a model. `--launch` explicitly starts supervised `codex exec --json --sandbox workspace-write` or `claude -p --output-format stream-json --verbose --permission-mode acceptEdits --permission-prompts none` in the same workspace. Claude's native file-edit permission mode is not an OS sandbox equivalent to Codex's sandbox; other tools can still be denied. No permission bypass is enabled. A zero exit without observable workspace changes reports `no_changes`, not success; verification remains `not-run` unless the person gave an explicit `--check` (below). Each `<packet>.continue-*.json` launch record carries `started_at` (same UTC format; later than the workspace-lock claim and earlier than the child process start; absent in older records) and, once the record reaches a final state (including supervisor interrupted / wall-time budget), `ended_at` (same format; absent while the continuation is still running and in records written before #483, where readers fall back to the file modification time).
If relay's own post-processing after the child exits (quota-signal parsing, handoff capture, workspace snapshot) raises, the record is finalized as `state=postprocess_error` with a short `error` and `ended_at` (the child's `exit_code` is kept) and the exception is re-raised, so the record never stays `running`; whether the work finished is then Unknown and the daily quota page judges it `unknown`, not failure (#487).
A zero child exit with Unknown change detection instead reports `changes_unknown`,
asks the person to inspect `git status`, and makes the ccx command exit 2. The saved
`exit_code` still describes the child, so it can remain zero in that record.
Claude Code **2.1.316 --help** was rechecked on 2026-11-05: `--permission-prompts none`
denies anything that would prompt, even with `acceptEdits`. Without an explicit `--check` packets have no
trusted check command, and with one relay still adds no `--allowedTools` grants. Its Claude
prompt explains native edit permission, possible Bash/PowerShell/test denial, and
requires exact blocked commands plus `not-run` tests if checks cannot execute.
The budget is a required positive, finite **wall-time limit in seconds**, not a dollar ceiling. Dollar accounting/caps for this new-lead path are **Unknown / not implemented**. Native CLI child-task spending is not bounded separately.
Before either preparation or launch, ccx checks staged/unstaged diffstats, HEAD and current status. A changed HEAD requires manual reconciliation and a fresh packet. A changed dirty workspace is reported to the new lead for inspection, never reset.
The new lead is told to inspect partial work and run relevant checks before editing. This instruction is not proof the model obeys it; `verification` stays `not-run` unless an explicit `--check` was run by ccx.
The supervisor records argv, prompt, PID, exit code and stdout/stderr logs locally; budget expiry stops the child process tree and retains partial files.
An explicit quota refusal in the new lead's output also saves a fresh handoff and notification, even with exit code zero; it never launches another vendor automatically.
An exclusive durable packet claim prevents duplicate launch, while a workspace-wide lock prevents different packets launching together. Locks record PID/time; stale locks require manual orphan-process reconciliation. Failure to spawn releases both claims. Before launch ccx checks known live run PIDs in the same Git workspace (including subdirectories). Native processes without ccx records and native auto-resume remain Unknown: `--old-stopped` is still a required user attestation, not proof that all writers stopped. Killing the supervisor externally may leave its CLI alive; there is no watchdog or automatic recovery.

## A new session is told about an unfinished packet (#523)

With `relay.enabled = true`, the session-start hook that already runs `ccx mem delta` (Claude Code and Codex) adds one
plain-text line when this workspace holds a packet that came from the *other* tool, is in state `quota_stopped`,
`rate_limit_unconfirmed` or `captured`, and has no `<packet>.continue-*.json` record yet: the packet id, the one-line
goal, and the `ccx relay continue ...` command, with the reminder to make sure the old session is stopped and to ask the
person first. It only looks: it never continues or launches anything, so the old-session-stopped attestation and the
person's yes stay as they were. With relay off, no packet, or a packet from the same tool, the hook prints nothing extra.
Checked against the hooks docs on 2026-11-26 (Claude Code 2.1.316, codex-cli 0.164.0): plain stdout of a SessionStart
hook is added to the context in both tools (`hookSpecificOutput.additionalContext` is the JSON form; ccx keeps plain
text, as for its other start-up lines, and for Codex `hook_text` puts a plain first line before it so the output is not read as JSON).
Not recorded on a real Claude→Codex run yet (fake-CLI tests only).

## Explicit `--check`: verification by a command ccx runs itself (#522)

Default: no `--check`, nothing below happens, and `verification` stays `not-run` exactly as before. The feature is inside the same `relay.enabled` switch; there is no second switch.

```text
ccx relay capture --goal "Finish the parser" --check "python -m pytest -q tests/test_parser.py"
ccx relay continue PACKET_ID --to codex --budget-seconds 300 --old-stopped --launch --check "python -m pytest -q tests/test_parser.py"
```

* The only accepted source is a `--check` the person types, at capture (saved in the packet as `check` = `cmd`, `source` `capture-flag`, `sha256`) or at continue (`source` `continue-flag`; it replaces the packet's own and marks `overrides_packet`). A packet is data, not authorization: it sits in the workspace, which the new lead (and the old one) can write, and a hash or source label anyone can compute proves nothing. So a check stored in a packet is **shown but never run** unless the person also passes `--use-packet-check` (or types `--check` again) at continue; with `--use-packet-check`, a field with no known `source`, a `sha256` that does not match `cmd`, or a malformed value is **refused with a reason, at preparation and at launch, and nothing is run**. The check runs with your permissions outside the new lead's sandbox, on files the lead may have changed (a `conftest.py`, say), and its command line is told to the lead and written (first 200 characters) to the ledger: no secrets in it. The command stays in the session's saved context, so a later capture in that session carries it unless you give another.
* The model is never told to run it and gets no extra permission (no `--allowedTools` change). The prompt only says ccx will run it.
* After the child process has ended (the workspace lock is still held, so no other writer), ccx runs the command in the same workspace with the ordinary check runner (`workspace.run_check`: same shell rules, same tail), then writes `verification` = `pass` / `fail` / `broken` and a `check_result` (exit code, seconds, output tail, `timed_out`) into the launch record, and one `relay_check` row into the ledger (`ccx` hub `ledger.jsonl`, skipped by run aggregators). `fail` includes a timeout (`check_result.timed_out`); `broken` means the command could not test anything (missing Bash, pytest usage error, could not start). A failing or broken check makes `ccx relay continue` exit 2, whatever the child's own exit code was.
* `--check-timeout-seconds` (default 900) bounds the command (on Windows, a hung grandchild process of a `shell` command may outlive the timeout: known limit of the shared check runner, tracked separately). The check runs whatever the child's state was (exited, `no_changes`, budget stop), because it judges the workspace, not the child; it does not run when the supervisor itself was interrupted. Preparation without `--launch` shows the check and runs nothing.
* A quota-stopped child's next handoff packet carries the check that was actually run forward. While it runs the record says `state=checking`; an interrupt writes `check_interrupted`.

## Codex → Claude: only for Codex sessions ccx started (#525)

Checked on 2026-11-26 with codex-cli **0.164.0** (`codex --version`, `codex exec --help`; no model was run) against the
[Codex hooks reference](https://learn.chatgpt.com/docs/hooks): it documents `SessionStart`, `SessionEnd`, `SubagentStart/Stop`,
`PreToolUse`, `PermissionRequest`, `PostToolUse`, `PreModelRequest`, `PostModelRequest`, `PreCompact`, `PostCompact`,
`UserPromptSubmit`, `Stop` and `Interrupt`, and **nothing for usage limits** (no `StopFailure`, no quota or rate-limit event
or matcher). So a Codex session the person started in the app or the terminal gives ccx no signal: it is **not covered**,
and ccx installs no Codex quota hook.

What is covered: a Codex session **ccx itself launches** (`ccx run` / `ccx delegate --to codex`). ccx reads its
`codex exec --json` events; when the run ends on a confirmed usage-limit refusal and no fallback took the task over, it saves
a relay packet (`source: codex`, goal = the brief, state `quota_stopped`) and a notification, and the result carries a
`relay` field with the `ccx relay continue PACKET --to claude ...` command. Off unless `relay.enabled`; only a confirmed
quota counts (not capacity, auth or an unconfirmed rate limit); it never launches Claude by itself, and a failure here
never fails the delegation. A `ccx relay continue --launch` child that hits quota already saved its own next packet (above).

Real shape: the wording is **captured** (codex-cli 0.164.0 log, 2026-11-25: `You've hit your usage limit. Visit
https://chatgpt.com/settings/usage to purchase more credits or try again at <time>.`) and matched in both `error` and
`turn.failed` envelopes. The JSON envelope that `exec --json` wraps around it has **not** been captured (the docs name the `error` and
`turn.failed` events but no fields): **Unknown** until a real refusal is recorded; then the synthetic samples are replaced.

## Signals and native overlap

`ccx/quota_signals.py` prioritizes protocol evidence: rejected known usage windows and explicit `usage_limit_reached` or usage-limit wording in error envelopes. StopFailure and rejected rate_limit_event signals without that evidence remain `rate_limit_unconfirmed`; a reset time or requests-per-minute limit alone does not confirm exhausted quota. Authentication/transport/billing errors, normal usage readings and arbitrary tool/user/model prose do not count as quota. Existing delegation quota classification remains unchanged.
Claude fixtures in `tests/data/real_signals` are captured and redacted. **Codex quota samples are synthetic** except the refusal wording (captured, see above); the `exec --json` envelope is still Unknown.

Checked on 2026-11-05: `claude --version` / `claude --help` = **2.1.316**; `codex --version` / `codex exec --help` = **0.164.0**. No real model was invoked.

* [Claude hooks reference](https://code.claude.com/docs/en/hooks#stopfailure): StopFailure output and exit code cannot continue the turn. The implemented terminal bell uses the documented `terminalSequence` exception; it is ignored in `-p`/SDK sessions. The file notification remains available.
* [Claude settings reference](https://code.claude.com/docs/en/settings-reference#autocontinueatusagelimit): native `autoContinueAtUsageLimit` waits for the same account's reset and resumes automatically (default true, since 2.1.234). This overlaps with waiting/recovery, not cross-vendor handoff. ccx does not edit that setting. Stop the native wait before switching vendors to avoid two writers. Exact `quota_auto_resume_*` Notification matcher names were not found in the official pages fetched in this check: **Unknown**.
* [Codex non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode): `codex exec --json` exposes events for a separately supervised session. The fetched [Codex hooks reference](https://learn.chatgpt.com/docs/hooks) did not establish an equivalent quota StopFailure hook: **Unknown**. No Codex quota hook is installed.

## One-minute desktop check (2026-11-05; pending user verification)

1. Enable relay and apply hook sync as above in a disposable Git project. The desktop Code tab does not support `/hooks`, so check registration in one of two ways: (a) run interactive `claude` in a terminal and type `/hooks`; or (b) read `hooks.StopFailure` in `~/.claude/settings.json` (ccx writes `~/.claude/settings.json`; on Windows that is `%USERPROFILE%\.claude\settings.json`; whether the desktop app reads the same file has not been verified separately). Either way, look for matcher `rate_limit` → `ccx relay capture --hook`. If a desktop session does not trigger the hook, reopen the session and try again.
2. If a normal session is already at its natural usage limit, submit one harmless prompt. Look for a new `.ccx/relay/*.notification.json` and its packet. Confirm the packet names the desktop session, HEAD and dirty files. If no limit is present, stop after checking hook visibility: real desktop event delivery remains **Unknown**; do not spend tokens to exhaust quota.
3. Stop the old session and its automatic resume. Use `relay continue ...` without `--launch` to inspect the prepared handoff in the other direction.

2026-11-10: a simulated StopFailure event fed to the hook command (stdin) wrote `.ccx/relay/*.notification.json` (state `rate_limit_unconfirmed`). Desktop hook execution on a real usage limit and notification visibility are still **Unknown**. This check can verify hook registration immediately; actual rate-limit delivery needs an already limited session and is not promised within one minute.

When a real quota event happens, record it with the [event log template and steps](quota-event-log.md); "the hook did not fire" is a normal outcome there (native auto-continue may have taken over).

To disable: `ccx config set relay.enabled false`, then `ccx sync --only hooks --apply`. A stale installed capture hook is also a silent no-op while disabled. Uninstall removes only ccx's relay handler and preserves other handlers.
