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

Codex and other adapters currently emit a warning **before launch** and add
`credential_guard: {status: "Unknown", mechanism: "unverified"}` to the run record.
Their existing sandbox arguments are preserved. Claude records `status: "Unknown"`
and `mechanism: "claude-permissions-deny"`: injected rules do not prove isolation.
`rules_added` means only that rules were injected into the launch settings. The
guard does **not** count refusals or attribute existing CLI denial counters to
these rules. Codex is **not protected by this guard**. No credential contents or
protected path list is added to the record or warning.
CLI authentication and startup configuration loading are outside tool-level denies.
Generated Claude settings are limited to 22,000 characters; the complete quoted
command is limited to 30,000 UTF-16 units, below Windows's 32,767-unit ceiling.
Excessive rules/settings fail before launch, without truncating away protection.
Invalid guard configuration uses the existing configuration-error exit (3) and a
finished `error` record, not an interrupted/killed attempt; no CLI attempt is begun.

## CLI evidence (2026-11-05)

- Checked local `codex-cli 0.164.0 --help`: `-c key=value`, read-only/workspace-write
  sandbox modes; these modes alone do not establish per-directory read denial.
- [Official Codex permission profiles](https://learn.chatgpt.com/docs/permissions)
  document filesystem `deny` and profile inheritance. Support and enforcement for
  those beta profiles on the checked CLI version/platform were **not established**.
  ccx does not pass speculative config keys or silently replace sandbox defaults.
- [Official Claude permissions](https://code.claude.com/docs/en/permissions)
  document deny precedence, absolute `//` Read patterns (Windows drive normalization),
  Bash `*` wildcards anywhere in a command pattern (including `Bash(*...*)`) and
  the arbitrary-program limitation. Checked official docs 2026-11-05; adapter baseline:
  Claude Code 2.1.309; no real Claude/model invocation was performed for this change.

Tests use temporary stand-in homes and `tests/fakes` only. They check path
construction, settings preservation, warnings and the `ccx run` launch wiring
from outside the repository. They do not establish real CLI or OS enforcement.
