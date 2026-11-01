# relayline (formerly claude-codex-bridge) — instructions for coding agents (Claude Code, Codex, DeepSeek, Gemini CLI)

`ccx` lets Claude Code, Codex and DeepSeek be each other's lead / sub-agent (Gemini CLI: sub-agent adapter,
not run for real), with shared skills, MCP, incremental memory, resumable runs and token accounting. Python 3.11+, standard library only.

**When you need to know where things stand** (picking the next item, not for a small fix): `docs/STATUS.md` is one
page (now, next three, how sure we are); history is in `docs/STATUS-archive.md`, changes in CHANGELOG.md (plus `changes/*.md` not yet folded in).
`.ccx/handoff.md`, if it exists, is the previous session's local notes. Don't read these up front for an unrelated
task: whatever you read is re-read on every later turn. Keep STATUS one page (EN + ZH) when you finish an item.

## Layout
- `ccx/` — the CLI (`python ccx.py -h`): `cli.py` (parser + `main`), `commands/` (one module per command group,
  each with `register(sub)`: `delegation`, `memory`, `install`, `records`; shared helpers in `common`),
  `setup.py` (the `ccx setup` wizard), `delegate.py` (run loop) with `prompts.py` (what a sub-agent is told),
  `plan.py` (which rungs, fallback), `workspace.py` (worktree, check, undo), `verdicts.py` (verify, probable
  verdicts), `review.py` (independent review), `agents/<name>.py` (one adapter per CLI: argv,
  parser, files, vendor, capabilities), `runners.py` (running a CLI, shared parsing),
  `learn.py` (bridge to the skills), `memory.py` / `project.py` (shared + project memory, handoff),
  `sync.py` (wiring into both tools), `ledger.py` / `usage.py` / `report.py` (accounting, dashboard),
  `board.py` (open sessions writing to each other, docs/board.md), `archive.py` (session archiving), `stop.py` (`ccx stop`), `doctor.py`.
- `skills/` — standalone skills: `agent-delegate`, `task-routing`, `task-split`, `task-checkpoint`, `project-manager`.
- `config/tiers.toml` — defaults (tiers, permissions, slim start-up, sessions, providers).
- `tests/` — fake CLIs in `tests/fakes/`; never call real CLIs in tests.
- `docs/` — DESIGN, DECISIONS (bilingual table), STATUS (one page) + STATUS-archive, research.

## Rules
- Run `python -m pytest -q tests` before every commit; all must pass (CI: a PR runs Windows 3.11 + Ubuntu 3.13, a push to
  main runs Linux/Windows/macOS × 3.11–3.13; check main's run after a merge, see CONTRIBUTING).
- Generic only: no personal paths, names or data in the repo. Personal things live in the user's hub.
- Links and images in README.md must be absolute URLs: it is also the PyPI page, which resolves no relative link
  (`tests/test_packaging.py` checks it; README.zh.md is not on PyPI and may keep relative links).
- Keep the core: no command or option is removed; a PR that changes one says in a line what it kept and how that
  was checked. Paths not run for real are called experimental where they are described.
- Docs are bilingual: `x.md` (English) + `x.zh.md` (Chinese), linking to each other. For real decisions, update
  docs/DECISIONS.md.
- A PR adds one `changes/<PR>.md` with its CHANGELOG lines and does not edit CHANGELOG.md or docs/STATUS.md:
  the lead session updates STATUS and folds the notes in when releasing (`scripts/collect_changes.py`,
  see `changes/README.md`). This keeps parallel PRs from conflicting.
- Verify external CLI facts against `--help` / official docs before relying on them; note the version checked.
- Never touch credentials; never hand-edit the tools' config files outside ccx's marked blocks.
- Small commits with clear messages; bump `ccx/__init__.py`, `pyproject.toml` and both `plugin.json`
  (`.claude-plugin/`, `.codex-plugin/`) for releases.
