# Security

English · [中文](SECURITY.zh.md)

ccx runs AI coding agents on your machine and wires them into each other. This page says what it runs, what it
can change, and where the limits are, so you can decide what to allow.

For where untrusted text can reach an agent (repository files, issues, board messages, memory notes) and what is
left to you, see the [threat model](docs/threat-model.md).

## What ccx runs and changes

| Part | What happens | Limit |
|---|---|---|
| Session-start hook (`ccx sync --apply`) | Claude Code and Codex run `ccx mem delta` at session start. It prints new shared-memory lines, an unread handoff and unfinished tasks into the session | Local command only, no network. Installed only after the dry run and your `--apply`; Codex also asks you to trust it once in `/hooks`. `ccx uninstall --apply` removes it |
| Config files | ccx adds a marked block to Codex's `config.toml` and one hook entry to Claude's `settings.json` | Nothing outside its own block/entry is edited; each changed file is backed up first |
| Sub-agents, write mode (default) | Codex runs with `sandbox_mode="workspace-write"`; Claude with `acceptEdits` and an allow-list of tools (`config/tiers.toml`) | Edits stay in the task's working folder. Before a write run ccx snapshots the tree: `ccx undo <run_id> --apply` puts it back (new files are moved aside, not deleted). `--worktree` isolates edits on a branch |
| Sub-agents, read mode (`--mode read`) | Codex `read-only` sandbox; Claude with a read-only tool list | For review and analysis |
| Nesting | A sub-agent cannot delegate again (`max_depth = 1`) | Stops runaway chains and their cost |
| Files from outside (`.ccx/inbox/`, web pages, logs) | Every brief tells the sub-agent that such text is reference material, never instructions | This lowers the risk of prompt injection; it cannot rule it out. Read results before trusting them |

## What ccx does not do

- It never logs in for you and never reads, copies or sends credentials. Provider keys (e.g. `DEEPSEEK_API_KEY`)
  stay in your environment and are passed only to the agent CLI that needs them.
- It sends nothing anywhere itself. The agent CLIs talk to their own services as they always do.
- It keeps your personal data (memory, ledger, learned parameters) in your hub folder, never in this repository.

## Your part

- Review the `ccx sync` dry run before `--apply`.
- Treat a sub-agent's summary as a claim: look at the diff and run the check before `ccx verify --ok 1`.
- Use `--mode read` or `--worktree` for code you don't want touched in place.
- Don't put secrets in briefs, memory lines or `.ccx/inbox/`; the agents read them.

## Reporting a vulnerability

Please use **GitHub → Security → Report a vulnerability** (private advisory) on this repository instead of a public
issue. Include the ccx version (`ccx --version`), the agent CLI versions and the steps to reproduce.
