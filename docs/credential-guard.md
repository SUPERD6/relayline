# Credential directory guard (experimental)

English · [中文](credential-guard.zh.md) · [Threat model](threat-model.md)

Enable with `ccx config set security.credential_guard true`. It is **off by default**;
existing commands, options, sandbox defaults, JSON meanings and verdicts are retained.
Append directories with `ccx config set security.credential_dirs "path-one;path-two"`.
Relative entries use the task's original working directory. This is an engineering
check, not measured protection against a hostile agent.

The guard runs before ordinary `ccx run` delegated attempts, including its resume,
fallback and reviewer paths. The separate `ccx relay` direct-Popen launcher does
**not** use this guard. Do not assume relay has these rules.

Only credential targets are denied: `.credentials.json` and `auth*` in default
and configured Claude homes; `auth*` (including `auth.json`) and root `*.sqlite*`
databases/sidecars in default and configured Codex homes; the entire project
`.ccx/eval-codex-home`; and explicitly configured extra directories. Skills,
`projects/*/memory`, tool-results and other home contents are not blanket-denied.
Original and child homes are both included. Relative environment home paths use
the original task cwd or worker cwd, respectively, never ccx's process cwd.
`resolve(strict=False)` adds canonical aliases alongside original spellings. It
queries filesystem metadata (not pure string manipulation) to follow links,
junctions and supported Windows short names; no file content or directory listing
is read. Resolution failures retain the original spelling; alias coverage is not
guaranteed. Tests use temporary paths and a deterministic alias resolver stand-in.

Claude receives additive `permissions.deny` Read rules for the sensitive targets
and Bash command-pattern denies for recognizable path spellings.
Existing settings and denies are preserved. Inline settings are required when
enabled; uninspectable settings and permission bypass are refused before launch.
User configuration files are not edited. Read rules also cover recognized file
commands, but arbitrary Python/Node programs, recursive searches from a parent,
`cd ~ && cat .claude/.credentials.json`, path aliases and MCP can bypass tool rules.
On Windows, Bash rules include drive-letter/backslash, Git Bash `/c/...` and
`//c/...` forms, plus lowercase and uppercase whole-path spellings. Bash wildcard
rules are **case sensitive**; arbitrary mixed-case spellings remain a bypass. Read
paths use Claude's documented `//c/...` drive normalization; this is not a claim
that every tool matcher is case insensitive. A warning precedes launch. Use external
OS isolation when these paths must be inaccessible to every process.

Codex (since #289) runs under a **permission profile** instead of its legacy sandbox mode: ccx replaces its
own `-c sandbox_mode="read-only"` / `"workspace-write"` with `-c default_permissions="ccx-credential-guard"` and
an inline `-c permissions.ccx-credential-guard={extends=":read-only"|":workspace", filesystem={<target>="deny", ...}}`
for the same targets as Claude. Nothing is written to the user's Codex config; `exec resume` gets the same arguments.
Launch is refused (configuration error, no attempt) when the arguments cannot be inspected or would defeat the
profile: `--sandbox`/`-s`, `--dangerously-bypass-approvals-and-sandbox`, `--approve-for-me`, `-p/--profile`,
`sandbox_mode="danger-full-access"`, an existing `default_permissions`/`permissions.*`/`sandbox_workspace_write`
override, a `--config=` spelling, an unparseable Codex config file, or, on Windows, the **unelevated** sandbox
(`windows.sandbox` from a later `-c` or the first config file that sets it). Measured (below): the unelevated
sandbox refuses to start any thread with deny-read entries, and the **elevated** sandbox enforces them by adding
`CodexSandboxUsers:(DENY)(R)` ACEs to the matching files and directories. **Those ACEs stay after the run**; they
affect only Codex's sandbox accounts, not you or the Codex process itself, and `icacls <path> /remove:d CodexSandboxUsers`
removes them. Codex's permission profiles are **beta**. Not covered: MCP servers, Codex's in-process tools (for
example image viewing), and reads by the Codex process itself. Codex docs say a `sandbox_mode` in any loaded config
file selects the legacy sandbox instead of a profile; codex-cli 0.164.0 still applied the `-c` profile when checked,
so ccx does not refuse but records `config_sets_sandbox_mode: true` and says so in the warning. Config files checked:
`CODEX_HOME/config.toml` (unless `--ignore-user-config`) and `.codex/config.toml` from the task directory up to its
repository root. Managed (`requirements`) config is not inspected. Linux/macOS enforcement (bubblewrap / Seatbelt per
Codex docs) was **not** run here.

Codex records `credential_guard: {status: "Unknown", mechanism: "codex-permission-profile", rules_added: true}`,
plus `windows_sandbox` (`elevated`, `default` when unset, ...) on Windows. Other adapters emit a warning **before launch**
and add `{status: "Unknown", mechanism: "unverified"}`; their sandbox arguments are preserved.
Claude records `status: "Unknown"` and `mechanism: "claude-permissions-deny"`: injected rules do not prove isolation.
`rules_added` means only that rules were injected into the launch settings.
Observed refusals are counted after each attempt: Codex `access_denied_commands` = shell commands that exited non-zero
with an access-denied message (`Access is denied`, `Permission denied`, `Operation not permitted`, ...); Claude
`refused_tool_calls` = the CLI's own `permission_denials` count. Both count refusals **whatever caused them** (the
guard, the sandbox, the allow-list): they are not attributed to the guard alone, and a read through a non-shell tool
is not seen. The top-level values are run totals. No credential contents or protected path list is added to the
record or warning.
CLI authentication and startup configuration loading are outside tool-level denies.

When enabled, each `attempts[n].credential_guard` preserves that attempt's launch
evidence, including attempts stopped by capacity fallback. Top-level `credential_guard`
keeps the weakest status across the run's attempts (`Fail`, then `Unknown`, then `Pass`),
with an `attempts` summary containing zero-based `n`, agent, model and guard evidence.
At equal status, `unverified` is weaker than injected rules. Its existing mechanism
and `rules_added` fields describe that weakest attempt, not the whole run; summaries
retain the others. For individual launch evidence, use `attempts[].credential_guard`.
Claude and Codex both report `Unknown`; injected rules or profiles do not imply `Pass`.
Launch warnings also appear in the run's `credential_guard_warnings` list with zero-based `attempt`,
agent and message. Compact `run`/`show` receipts include the aggregate and warnings.
With the lead's `line` preference, guard warnings or a non-`Pass` guard status keep
the full receipt visible. Direct line consumers also retain both guard fields.
Interrupted attempts retain their guard evidence when recovered. With the switch off,
none of these fields are added and existing receipt output is unchanged.

Generated Claude settings are limited to 22,000 characters; the complete quoted
command is limited to 30,000 UTF-16 units, below Windows's 32,767-unit ceiling.
Excessive rules/settings fail before launch, without truncating away protection.
Invalid guard configuration uses the existing configuration-error exit (3) and a
finished `error` record, not an interrupted/killed attempt; no CLI attempt is begun.

## CLI evidence (2026-11-05, Codex updated 2026-11-16)

- 2026-11-16 (#289): `codex-cli 0.164.0` on Windows 11. `codex exec --help` has `-c key=value`, `-p/--profile`
  (a config-file layer), `--sandbox`, `--ignore-user-config`; `codex sandbox --help` has `-P/--permission-profile`.
  [Official Codex permissions](https://learn.chatgpt.com/docs/permissions) (beta): `[permissions.<name>]` with
  `extends` and `filesystem` entries `read`/`write`/`deny`, selected by `default_permissions`; deny also blocks reads;
  globs supported; profiles do not compose with `sandbox_mode`; Windows `unelevated` refuses policies it cannot enforce.
- Measured with fake files only (`FAKE-TOKEN-FOR-TEST`), no model call: `codex sandbox -c permissions.g={...} -P g -- cmd /c type <file>`
  on the elevated backend refused denied files, a denied directory, absolute `auth*` / `*.sqlite*` globs and a
  `:workspace_roots` glob ("Access is denied."), left other files readable, and accepted missing paths; `icacls`
  then showed persistent `CodexSandboxUsers:(DENY)(R)` ACEs. The same on the unelevated backend failed every command
  ("Restricted read-only access requires the elevated Windows sandbox backend").
- Measured `codex exec` with the exact `-c default_permissions=... -c permissions.ccx-credential-guard={...}` arguments:
  unelevated home -> the thread did not start ("windows unelevated restricted-token sandbox cannot enforce deny-read
  restrictions directly; refusing to run unsandboxed"), no tokens spent; with the guard off the same task printed
  the fake token. A scratch home whose config also set `sandbox_mode = "danger-full-access"` gave the same refusal,
  i.e. the `-c` profile still applied. See the PR for the `ccx run --to codex` runs.
- [Official Claude permissions](https://code.claude.com/docs/en/permissions)
  document deny precedence, absolute `//` Read patterns (Windows drive normalization),
  Bash `*` wildcards anywhere in a command pattern (including `Bash(*...*)`) and
  the arbitrary-program limitation. Checked official docs 2026-11-05; adapter baseline:
  Claude Code 2.1.309; no real Claude/model invocation was performed for this change.

Tests use temporary stand-in homes and `tests/fakes` only. They check path
construction, settings preservation, the Codex profile arguments and refusals, warnings,
refusal counts and the `ccx run` launch wiring from outside the repository. They do not
establish real CLI or OS enforcement; the measurements above do, for the stated version and platform only.
