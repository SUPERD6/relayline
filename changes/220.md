- Codex's Windows sandbox prompt cancelled (error 1223) is an environment failure again: codex-cli 0.164.0 wraps the
  launcher's error as `CreateProcess { message: "Rejected(\"... orchestrator_helper_launch_canceled: ShellExecuteExW
  failed to launch setup helper: 1223\")" }`, and ccx skipped every line with "Rejected" as a policy refusal, so a run
  climbed to the next rung in the same session (2026-10-31 eval pg1: 13 units). Now only policy refusals are skipped
  (`blocked by policy`, any case, or the "`<command>` rejected: <reason>" shape such as "policy forbids commands
  starting with `rg`"), and the refused command's own quoted text never counts as a launcher marker. Such a run
  stops after one attempt with `kind: env`; its `env_error` keeps the error code; the hint, `needs_lead` and `ccx ui`
  say "sub-agent environment problem: sandbox authorization was cancelled (Windows error 1223)" for Codex alike, and
  that the current (elevated) sandbox mode needs one UAC approval or `[windows] sandbox = "unelevated"`.
- ccx itself no longer climbs, retries or continues after an environment failure: `ccx resume` of a `kind: env` run
  is refused (a `needs_lead` record, exit 2, nothing spent, `--bg` included) unless the new `--env-fixed` says the
  person fixed the machine; `ccx q run` treats `env` as backpressure (nothing new starts) and `restored` calls it
  `decide`; `ccx batch --lanes` starts no later piece; auto-continue and seats do not reuse that session. Kept: every
  command and option (`--env-fixed` is added), and the env run's own exit code 0. Limits: inside its one attempt
  Codex still retries by itself (about 250 s on pg1's first attempt), so each unit still spends one attempt; plain
  `ccx batch` without lanes starts its pieces in parallel as before.
