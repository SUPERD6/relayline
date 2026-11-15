# Questions and similar projects

English · [中文](faq.zh.md) · back to the [README](../README.md)

**Not the similarly named projects:** relayline was called `claude-codex-bridge`, but it is not
[CCB](https://github.com/SeemSeam/claude_codex_bridge) (`SeemSeam/claude_codex_bridge`, a visible terminal workspace
for watching and steering many agents) and not OpenAI's official [codex-plugin-cc](https://github.com/openai/codex-plugin-cc)
(sends work from Claude Code to Codex only). See [Similar projects](#similar-projects).

## Questions

**Doesn't a second agent cost more tokens?** Yes: 3.3× the tokens in the measured small tasks, about the same
dollars (ratio 1.02) because the sub-agent was cheap, and about 23 s slower. What delegating saves is the lead's own
requests (one fewer per task, when the lead answers as soon as ccx's check passed); that is worth money only when
each lead request re-reads a long conversation, and so far that is extrapolated. A lead that reran the tests itself
paid for the sub-task on top. For tiny tasks ccx tells you to do them
yourself (`delegated: false`). Most of the money goes on the lead re-reading its own conversation every turn, which
is what `ccx lead`, `ccx sum` and `ccx fresh` are for. `ccx report` shows the difference from your own runs;
`ccx trial` runs a week-long comparison.

**I'm on a subscription, not the API.** Costs are shown at API prices so runs can be compared; the dashboard also
shows how much of each tool's quota went where. When one tool runs out, the work moves to the other (experimental: tested with stand-ins only, no real quota stop yet).

**Is it safe to let a sub-agent edit files?** Edits stay in the task's folder, every write run is snapshotted for
`ccx undo`, and `--mode read` or `--worktree` keep your tree untouched. Details in [SECURITY.md](../SECURITY.md).

**Read-only or allowed to edit?** Without `--mode`, ccx decides from the task text: analysis words (review,
explain, compare, 分析, 解释 …) mean read-only, edit words (fix, add, refactor, 修复, 改成 …) mean it may edit, and
an unclear text keeps the old default (edit) and says so. `--mode` always wins. A read-only sub-agent that finds it
must edit stops with `needs_write` and hands the decision back to you.

**Does it drive the chat apps?** No. Both sides run in their work mode (`codex exec`, `claude -p`) — the same agents
you use in a terminal, not a web chat.

**Which tools work?** **Leads: Claude Code, Codex and DeepSeek (tested on a real machine).** DeepSeek leads either as
DeepSeek Harness (`dsh` 0.2.1-rc.3, headless, handed work to Codex) or as Claude Code running a DeepSeek model (handed
work to Claude); ccx tells it from the environment and records the lead's vendor as deepseek. Codex running a DeepSeek
model is recognised from its config or `CCX_LEAD=deepseek-codex`, not tested as a lead. Gemini CLI and the configured providers cannot lead. **Sub-agents:** Claude Code and Codex in both directions; DeepSeek through Claude Code
(calibrated on real tasks), through Codex (one small read-only task) and as `dsh` (read, write and resume run for real;
ccx also finds the `dsh` that ships in the DeepSeek Harness desktop app on Windows). Gemini CLI is adapted
(community) but **experimental, untested**; Kimi, GLM, Qwen and OpenRouter are configured, untested. One adapter per CLI (`ccx/agents/`);
`ccx agents` lists what each can do; adding one is described in [CONTRIBUTING.md](../CONTRIBUTING.md) (start from
`ccx/agents/_template.py` and `tests/fakes/fake_template.py`).

**Official or community?** *Official* (Claude Code, Codex CLI): each release runs real read, write and resume tasks
on the version in the adapter's `tested_version` (the release check). *Community* (Gemini CLI, `dsh`, new adapters):
written from the CLI's `--help` and docs and tested with a stand-in; `dsh` has also run for real (read, write, resume). `ccx doctor` warns when the installed
version's major.minor differs from `tested_version`: for an official one, run the release check before relying on
it; for a community one it means not verified on that version.

**Can two models discuss directly?** Yes, in a few ways: `ccx ask` for a one-off second opinion, `ccx resume` to
follow up in the same sub-session, `ccx send` into a live Codex session (delivered when it is between turns), and the
board (`ccx say`) for open sessions in one project. For a costly decision, `ccx discuss` runs up to three rounds
between models from different vendors (one proposes, one finds faults, one judges), passing only the points between
turns; the lead asks you before starting one.

**Chinese text in a run's JSON looks like `���`.** On a Chinese Windows, Python prints to a pipe in the code page (cp936/GBK), and a tool reading that pipe as UTF-8 shows `���`; the files ccx writes are UTF-8 and fine. Read them with `ccx show <run>`, or set `PYTHONUTF8=1` for the shell that runs your own Python one-liners. When ccx reads a sub-agent CLI's output (its stdout and stderr, Codex's last message) it tries UTF-8, then the machine's code page, and keeps undecodable bytes as `\xNN` rather than replacing them (#335).

## Similar projects

Checked 2026-10-24 (stars and dates from the GitHub API; they change). Details, sources and what is unconfirmed:
[docs/research/landscape.md](research/landscape.md).

| Project | What it does | Stars · last push · license | How ccx differs |
|---|---|---|---|
| Claude Code's built-in sub-agent (Task tool) | Claude Code hands a sub-task to a sub-agent of its own, on its own quota; nothing to install | built in | The closest alternative, measured in rounds 3–5 (dev set; hold-out pending): about as often right; cost per success round 3 built-in $0.069 vs ccx $0.071, round 5 built-in $0.114–0.202 vs ccx $0.116–0.135 (the lean builtin2 arm, $0.114, beat ccx's r5h, $0.135); wall time round 3 41 s vs 63 s, round 5 276–316 s vs 236–267 s ([measured](measured.md)). What ccx adds: another vendor's model and quota, ccx re-running your `--check`, a cross-vendor review, a ledger, `ccx undo`. |
| [openai/codex-plugin-cc](https://github.com/openai/codex-plugin-cc) | OpenAI's official Claude Code plugin (2026-03-30): Codex reviews, delegated tasks, moving a session to Codex, background jobs | 34.5k · 2026-07 · Apache-2.0 | It is Claude → Codex only and doesn't pick models or record cost. ccx works both ways and adds model choice by cost, a ledger and the lead's own cost. Meant to work side by side (different commands and hooks), but not tested together yet; `ccx doctor` says when it is installed. |
| [PAL MCP](https://github.com/BeehiveInnovations/pal-mcp-server) (`clink`) | An MCP server bringing many model providers into one CLI; `clink` starts another CLI as a sub-agent | 11.8k · 2025-12 · Apache-2.0 | PAL offers more models and tools via API keys; ccx uses the two CLIs' subscriptions, picks by success odds and cost, and calibrates on real outcomes. |
| [CCB](https://github.com/SeemSeam/claude_codex_bridge) (`SeemSeam/claude_codex_bridge`) | A visible multi-agent terminal workspace for 16 CLI families, with message queues and take-over | 3.6k · 2026-10 · AGPL-3.0 | CCB is about watching and steering agents together; ccx is headless delegation focused on cost. A different project despite the similar name. |
| [sendbird/cc-plugin-codex](https://github.com/sendbird/cc-plugin-codex) | A Codex plugin that calls Claude Code (the reverse of the official plugin) | 226 · 2026-10 · Apache-2.0 | Codex → Claude only. |
| [umum-ai](https://github.com/umum-ai/claude-codex-bridge) / [Jayden-X-L](https://github.com/Jayden-X-L/claude-codex-bridge) `claude-codex-bridge` | Codex from Claude with mid-run instructions / two-way review loops | 10 / 16 · 2026 · MIT | Each focuses on one part (steering, review); no model choice or accounting. |
| [claude-codex-memory-sync](https://github.com/DaizeDong/claude-codex-memory-sync), [mycelium](https://github.com/conradomateu/mycelium), [memorize](https://github.com/shakystar/memorize) | Sync skills, instructions, MCP and memory between the tools | 1–31 · 2026 · MIT | Config and memory only; in ccx shared memory supports delegation. |

What ccx doesn't have: a visible split-screen view; instructions added to a sub-agent while it is working (`ccx send`
reaches a live Codex session only between its turns); a vote among providers (`ccx discuss` ends with one judge);
moving a whole conversation into Codex. What it is still missing: a saving measured with real, long lead conversations (see the top of this page).
