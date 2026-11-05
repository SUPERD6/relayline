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
Packets include the explicit goal, progress, next step, source session, Git HEAD, staged/unstaged diffs, uncommitted file list and the continuation command.
Missing context is `Unknown`; a missing goal blocks continuation. Untracked files are listed, not copied. No private transcript is read.
Keep `.ccx/` ignored by Git; local packets can contain source diffs and must not be published blindly.

Stop the old session, its child tasks and its quota auto-resume wait first. Then use the packet id printed by capture:

```text
ccx relay continue PACKET_ID --to codex --budget-seconds 300 --old-stopped
ccx relay continue PACKET_ID --to codex --budget-seconds 300 --old-stopped --launch
```

The first command prepares a prompt and argv without launching a model. `--launch` explicitly starts supervised `codex exec --json --sandbox workspace-write` or `claude -p --output-format stream-json --verbose` in the same workspace, with native tools available and no permission bypass.
The budget is a required positive, finite **wall-time limit in seconds**, not a dollar ceiling. Dollar accounting/caps for this new-lead path are **Unknown / not implemented**. Native CLI child-task spending is not bounded separately.
Before either preparation or launch, ccx runs `git diff` and `git diff --cached`, checks HEAD and records the current status. A changed HEAD requires manual reconciliation and a fresh packet. A changed dirty workspace is reported to the new lead for inspection, never reset.
The new lead is told to inspect partial work and run relevant checks before editing. This instruction is not proof the model obeys it; `verification` stays `not-run`.
The supervisor records argv, prompt, PID, exit code and stdout/stderr logs locally; budget expiry stops the child process tree and retains partial files.
An explicit quota refusal in the new lead's output also saves a fresh handoff and notification, even with exit code zero; it never launches another vendor automatically.
An exclusive durable launch claim prevents launching the same packet twice. After a crash, inspect the saved PID/record and stop orphan writers before capturing a fresh packet. Killing the supervisor externally may leave its CLI alive; there is no watchdog or automatic recovery in this minimum version.

## Signals and native overlap

`ccx/quota_signals.py` prioritizes protocol evidence: rejected Claude usage windows, explicit `usage_limit_reached`, and Claude's `StopFailure` `rate_limit` error. HTTP 429 alone, authentication/transport errors, normal usage readings and arbitrary tool/user/model prose do not count. Existing legacy quota classification remains unchanged.
Claude fixtures in `tests/data/real_signals` are captured and redacted. **Codex quota samples are synthetic**, not a captured real refusal.

Checked on 2026-11-05: `claude --version` / `claude --help` = **2.1.316**; `codex --version` / `codex exec --help` = **0.164.0**. No real model was invoked.

* [Claude hooks reference](https://code.claude.com/docs/en/hooks#stopfailure): StopFailure output and exit code cannot continue the turn. The implemented terminal bell uses the documented `terminalSequence` exception; it is ignored in `-p`/SDK sessions. The file notification remains available.
* [Claude settings reference](https://code.claude.com/docs/en/settings-reference#autocontinueatusagelimit): native `autoContinueAtUsageLimit` waits for the same account's reset and resumes automatically (default true, since 2.1.234). This overlaps with waiting/recovery, not cross-vendor handoff. ccx does not edit that setting. Stop the native wait before switching vendors to avoid two writers. Exact `quota_auto_resume_*` Notification matcher names were not found in the official pages fetched in this check: **Unknown**.
* [Codex non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode): `codex exec --json` exposes events for a separately supervised session. The fetched [Codex hooks reference](https://learn.chatgpt.com/docs/hooks) did not establish an equivalent quota StopFailure hook: **Unknown**. No Codex quota hook is installed.

## One-minute desktop check (2026-11-05; pending user verification)

1. Enable relay and apply hook sync as above in a disposable Git project. Open `/hooks` in a **fresh desktop Code session**, and check for `StopFailure` → `rate_limit` → `ccx relay capture --hook`.
2. If a normal session is already at its natural usage limit, submit one harmless prompt. Look for a new `.ccx/relay/*.notification.json` and its packet. Confirm the packet names the desktop session, HEAD and dirty files. If no limit is present, stop after checking hook visibility: real desktop event delivery remains **Unknown**; do not spend tokens to exhaust quota.
3. Stop the old session and its automatic resume. Use `relay continue ...` without `--launch` to inspect the prepared handoff in the other direction.

Desktop hook execution and notification visibility have **not been tested**. This check can verify hook registration immediately; actual rate-limit delivery needs an already limited session and is not promised within one minute.

To disable: `ccx config set relay.enabled false`, then `ccx sync --only hooks --apply`. A stale installed capture hook is also a silent no-op while disabled. Uninstall removes only ccx's relay handler and preserves other handlers.
