- Credential guard (opt-in, still off by default) now covers Codex: ccx replaces its own `-c sandbox_mode=...` with an
  inline Codex permission profile (`default_permissions="ccx-credential-guard"`, `extends=":read-only"|":workspace"`,
  `filesystem` deny entries for the same credential targets as Claude) and adds `--ignore-rules` so execpolicy allow
  rules cannot run commands outside the sandbox. Launch is refused when the arguments would bypass or hide the
  profile, and on Windows with any sandbox other than elevated (unelevated refuses deny-read entries). Receipts
  record `mechanism: "codex-permission-profile"`, `windows_sandbox`, `config_sets_sandbox_mode`, and observed refusal
  counts (`access_denied_commands` for Codex, `refused_tool_calls` for Claude; run totals at top level, not
  attributed to the guard alone). Measured on codex-cli 0.164.0 / Windows: the elevated sandbox enforces the deny
  with persistent `CodexSandboxUsers` DENY ACLs. Status stays `Unknown`. Fixes #289.
