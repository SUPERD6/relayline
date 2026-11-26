# Real quota event log (template and steps)

[中文](quota-event-log.zh.md) · related: [quota relay](relay.md)

Evidence: **engineering template** only. No real quota event has been recorded yet, so whether a real usage limit fires
the relay `StopFailure` hook is **Unknown** (only the simulated event of 2026-11-10 exists, see [relay.md](relay.md)).
This page gives one place to store the evidence when a real event happens. It adds no code and changes no default.

## Possible outcomes (all are normal results)

| Outcome | What you see | What it means |
|---|---|---|
| A. Hook fired | A new `.ccx/relay/*.notification.json` and packet appear around the event time | The hook works on a real limit; continue the relay |
| B. Native auto-continue took over | No new packet; the session shows a wait for reset and then resumes on its own, or waits visibly | **Not a bug.** Claude Code's `autoContinueAtUsageLimit` (default on since 2.1.234) handled the limit instead of ending the turn with an error |
| C. Hook did not fire, no native wait | No new packet, and the session simply stopped with a limit message | Probably a bug: open a bug issue (see step 7) |

How to tell B from C: (1) read `autoContinueAtUsageLimit` in `~/.claude/settings.json` (Windows:
`%USERPROFILE%\.claude\settings.json`); a missing key means the default, which is on; (2) in the desktop app, check the
auto-continue checkbox; (3) look at the recording: a countdown or "will resume" wording means B. Write down which of these
you could check. If none can be checked, write Unknown and leave the outcome as "undetermined".

## Steps when the event happens

Do these in order, one thing per step. Do not exhaust quota on purpose to test this.

1. Keep recording. Do not close the session window yet. Note the clock time you first saw the limit message.
2. Open a terminal in the project folder and run `claude --version`, then `codex --version`. Copy both lines into the log.
3. Run `git status` and copy the output into the log.
4. Run `dir .ccx\relay` (macOS/Linux: `ls .ccx/relay`) and copy the file names and times into the log. If the folder does not
   exist or has nothing new, write "no new files".
5. If a `*.notification.json` exists, open the newest one and copy its `state` and message lines (not the whole file).
6. Check the native auto-continue setting as described above and write what you found.
7. Decide the outcome (A, B or C). If A, continue with `ccx relay continue PACKET_ID --to codex --budget-seconds 300 --old-stopped`
   (see [relay.md](relay.md)), then run the checks the task needs and write the receipt line. If C, open a GitHub bug issue
   that links this log and states whether auto-continue was on.
8. Save the filled log as `.ccx/relay/events/<date>-quota-event.md` (local; `.ccx/` is not committed). Save the recording next to
   it or note where it is.

## What must not go into the repository (or any issue/PR)

- Private conversation text, prompts, transcripts and task content that is not public.
- Credentials: API keys, tokens, `auth.json`, cookies, anything under `~/.claude` or `~/.codex` other than the single
  setting value you read.
- Personal paths, user names and email addresses. Replace them with `<user>` or `<project>`.
- The recording itself. Keep it local; refer to it only by file name.
- Full packet files: they list file names and diffstats. Copy only the fields named in the template.

If a completed log is ever linked from a public issue, paste only the filled template after removing the items above.

## Template

Copy this block into the new file. Write `Unknown` for any field you could not read from an actual file or screen; never guess.

```markdown
# Quota event <YYYY-MM-DD>

- Time of event (local clock, with timezone):
- Claude Code version (`claude --version`):
- Codex version (`codex --version`):
- ccx version (`ccx --version`):
- What I was doing just before (one sentence, no private content):
- Which client hit the limit (desktop app / terminal / other):
- Did the hook fire? (yes / no / Unknown):
- `.ccx/relay/` files (names and times, or "no new files"):
- Notification `state` and message (copy the lines only):
- `git status` (paste):
- Native auto-continue: setting value in settings.json (on / off / key absent = default on / Unknown):
- Native auto-continue: desktop checkbox (on / off / Unknown):
- Was the session waiting for the limit to reset? (yes / no / Unknown):
- Outcome (A hook fired / B native took over / C hook did not fire / undetermined):
- Relay result, if continued (command used, final state such as `no_changes`, exit code):
- Checks run after the relay and receipt (command and pass/fail, or "not run"):
- Recording file name (not the file):
- Bug issue link, if outcome C:
- Anything else that is Unknown:
```
