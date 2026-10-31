# What ccx does, and how

English · [中文](features.zh.md) · back to the [README](../README.md)

## Seven things it does

| | What | Where it stands |
|---|---|---|
| **1. Each other's lead and sub-agent** | Claude Code leads and Codex works, or the other way round; DeepSeek leads too (as `dsh`, or as Claude Code on a DeepSeek model) and takes work (through Claude Code, Codex, or `dsh`); Gemini CLI takes work (experimental, untested). One adapter per CLI; `ccx agents` lists what each can do, the version tested, official or community. | Both directions run for real; DeepSeek as lead (dsh, and Claude Code on DeepSeek) and as sub-agent (all three routes) for real; Gemini experimental, untested |
| **2. Two models talking directly** | `ccx ask` gets a quick second opinion from the other vendor; `ccx resume` follows up in the same sub-session; `ccx send` puts a message into a live Codex session; `ccx say` / `ccx board` let open Claude Code, Codex and DeepSeek sessions in one project write to each other (each turn sees what is new for it; Claude Code desktop only sees it on its next turn, a DeepSeek session runs `ccx board` itself); `ccx discuss` lets 2–3 models from different vendors talk a costly decision through (propose, find faults, judge; at most 3 rounds) and shows it as a conversation in `ccx ui`. From outside: Remote Control from your phone, or `ccx intake` takes tasks you file as labelled issues in a private repository and reports back there ([docs](intake.md)). | The first three work for real; `ccx discuss` ran for real twice, two vendors and then three (Codex, Claude, DeepSeek; [notes](research/2026-10-25-discuss-three-vendors.md)); `ccx intake` experimental: only with a stand-in `gh`, not real GitHub |
| **3. Shared memory** | A personal layer (your hub: memory, skills, MCP, ledger) and a project layer (`.ccx/`: context, journal, handoffs, checkpoints). The session-start hook brings only the other side's new lines; `ccx handoff` passes the baton, `ccx fresh` moves a long conversation to a fresh one of the same tool. A **shared work context** ([docs](shared-context.md)): what a session has been doing lately, read by code from each tool's session file, goes with delegated tasks (`ccx run --context`), on demand (`ccx peek`) and as one line per turn — each tool still keeps its own context. | Works for real; shared work context: first try right 36/36 vs 7/36 without, on tasks built to need it ([A/B](research/2026-10-25-shared-context-ab.md)) |
| **4. Splitting the work** | A five-question difficulty score → agent, model, effort and the odds; when doing it yourself is cheaper, or the task should be split first, it says so instead of delegating. `ccx batch` / `ccx q` run pieces in parallel (`--lanes N`, off by default: small pieces for one agent continue a few warm sessions instead of each starting one); `ccx task resume` continues a long task after a stop. | Routing works for real but priors are uncalibrated; the queue only with stand-ins |
| **5. Cheap and fast** | Slim sub-agent start-up; `ccx lead` shows what every turn of the lead re-reads (`--breakdown` part by part, `--cache` where the prompt cache broke, `--suggest` a model for the lead itself); `ccx sum` gives the lead only what matters of a big output. | The tools exist; how much they save depends on the lead using them (see below) |
| **6. No drop in quality** | ccx reruns the acceptance command itself (`--check`); another vendor's model reviews the diff (`--review`); every run gets a verdict (`ccx verify --ok 0 --reason wrong`), and runs nobody judged get a probable one from the evidence after 12 hours; `ccx trial` runs a week-long comparison. | Works for real; the automatic verdicts haven't been spot-checked yet |
| **7. You stay in control** | Config changes are a dry run first and backed up before applying; `ccx undo` reverts a run's edits; `--mode read` / `--worktree` leave your working tree alone; sub-agents can't delegate further; `ccx ui` shows on this machine who works on what and what waits for your call, and its buttons (stop, verify, one more round, budget) show the exact `ccx` command and run it only on a second click. | Works for real; `ccx ui` opened in Edge and the app's built-in browser only |

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/architecture-dark.svg">
  <img alt="Architecture: Claude Code, Codex and DeepSeek connect to ccx, each can lead or take work; a lead hands a brief to another, which runs headless and returns JSON; ccx routes, reruns the check, asks another vendor to review, and writes a receipt for every delegated run (cost, check, review, verdict, undo) into the ledger, and reads the other tools' sessions for the shared working context; below: the personal layer (hub: shared memory, skills, MCP, ledger), the project layer (.ccx: context.md, journal, board, handoffs, checkpoints, undo snapshots, queue) and ccx ui, a local page with the receipts and where tokens go. Gemini CLI: a worker adapter, not run for real" src="assets/architecture-light.svg" width="100%">
</picture>

## Commands: everyday first, nothing removed

`ccx -h` lists the everyday commands only: `setup`, `doctor`, `run`, `ask`, `resume`, `stop`, `undo`, `verify`,
`show`, `q`, `ui`, `mem`, `handoff`, `lead` (and `demo`). `ccx advanced` (same as `ccx -h --all`) lists every group: memory and
context, accounting and reports, between agents (the commands open sessions call: `peek`, `board`, `say`, `reply`),
advanced (the hub, several projects, installing: `init`, `projects`, `where`, `intake`, `sync`, `config`,
`uninstall`, `repair`, `agents`), maintenance, and developer last. `ccx dev` lists the developer commands (`trial`,
`ab`, `bench`, `improve`, `namecheck`); `ccx dev trial ...` is `ccx trial ...`. In `ccx run -h`, `ccx resume -h`,
`ccx verify -h` and `ccx lead -h` the rarely used options sit under an "advanced" heading. This is help layout only:
every command and option keeps its name and parses as before (`tests/data/cli_surface.json` froze the full list
and a test checks it).

## See it live: `ccx ui`

`ccx ui` opens a page on this machine: what waits for you (red = your call, amber = check the result, teal = a question for you),
who works on what (one column per agent, new agents get their own), and how the quota windows are going. Click a
block for the reason, the evidence and its buttons (a run stopped by the machine itself, `kind: env`, shows its fix
hint and `ccx doctor` instead of "Try again"; an empty hub says what to run first). It is also the manager's board: every project in the `ccx projects`
catalog (a work queue there shows even without a recent run; quiet projects are one line; a project's approval rules
are quoted on its page), and what this month's sub-agents spent; how much was saved appears only once `ccx trial` has
measured it (measured totals so far about even, docs/measured.md; the same rule as `ccx report`). A button that changes something — stop a run, record right or wrong, one more fix round,
continue, let it edit, change a queue's budget — first shows the exact `ccx` command it will run and runs it only
on a second click; one that starts a sub-agent says it costs money and runs in the background. The page sends only
which button, never a command; the server runs only a fixed list of ccx commands, as an argument list, from this page
only (same origin, a token, a one-time confirmation). Suggested notes have a yes / no button. Showing the page reads
only files ccx and the tools already write — no model is called — listens on 127.0.0.1 only, and exits about a minute after
the page is closed (up to 5 minutes if it was a background tab).
A review card shows, side by side, what the agent says (its summary and how it says it verified) and what ccx ran
(the check command, its exit code and the last ~800 characters of output), then the files actually changed and the
diff, computed from ccx's own snapshots of the run (the tree before it, `undo.json`, to the tree it left, `end.json`
or `undo.json`'s `after`), never from the folder as it is now; when the files the agent named and the files actually
changed differ, a red box lists the difference. Long diffs are cut with a visible "truncated" note; runs from before
these snapshots show the agent's own list with a note. The home page lists every run going on now (agent, time so
far, tokens when known) with its stop button, which asks for the same second click. A background tab says so in its
"still open" signal, and the server then waits 5 minutes instead of one before it exits. To-do chips are buttons
(keyboard reachable) and new to-dos are announced to screen readers.
Each to-do on the home page starts with what you need to do (a coloured chip: your call, check the result, a
question for you), then the agent's own words, then where it is. A finished write run's card has **Undo this run**
next to the diff (`ccx undo <id> --apply`: puts back the files from ccx's snapshot, moves new files aside, starts
nothing, and is not a verdict by itself; the confirm box lists the files, and when `ccx undo`'s dry run would also
put back files the run did not change, such as a later commit or your own edits, the page refuses and points to
`ccx undo <id>` in a terminal), and a run whose independent review still finds problems has **The review is
wrong: accept** (`ccx verify <id> --ok 1` with a note saying so). A queue piece in a worktree goes in one order, in the
page and in `ccx q ls` alike: your verdict first (`ccx q done`), then **Merge into the project** (`ccx q accept`, in
the background, after its `--dry-run` says it would merge: a protected branch checked out is said on the page). After a verdict the side panel moves on to the next piece that waits for you (also j / k). Each
project card says who leads it, with a link to its switch-lead panel; text meant for your lead (not a command) is
labelled "paste this to your lead".
Its **Agent conversation** page shows what the agents wrote to each other on the board (`ccx say`), newest thread first; a thread stopped by the machine-message cap and a message that asks you (`@person`) show as to-dos, and you can reply from the page: shown first, written on a second click as you (via ui), at most 4000 characters, never run ([board](board.md#seeing-it-and-answering-in-ccx-ui)). `ccx ui --export snapshot.html` writes a static copy; `ccx config set ui.lang zh|en` picks the language.
Its **Measured & where tokens go** page (read only) has three parts. (1) The published numbers (the hold-out and round-5 tables: arm, right, cost per success, wall median; the hold-out's external-repository rows, the clean ones, as their own small table; each table's limits in one line and a link to [measured](measured.md); a test checks every cell, by arm and run, against the tables in measured.md and measured.zh.md), then your own numbers from your ledger (runs, ok rate, API-equivalent $ per ok run, by mode and by agent), labelled "your runs, not a controlled comparison". (2) Where tokens go: one ledger across Claude and Codex, grouped by task (else label, else run); each run shows its fresh, cached, cache-write and output tokens and API-equivalent $ (and, when its logs say so, how many requests its own conversation made, the input of its first request and the mean input of one: the prefix re-sent each time, which is what a token-saving change has to lower; child sessions' requests are not counted there, while the token columns do include them), then its own child sessions (Codex children from the run record's `codex_children`, Claude ones from the sub-run's `<session>/subagents/*.jsonl`) and their share of the run; a run's own total already includes them. A run that resumes or continues an earlier one shows only what its children added (the earlier run's record is taken off, whatever the filter or group), and a Claude session taken up by several runs gives each run only the helper turns of its own time window. The share is not capped: above 100 % the page says the counts disagree. Filters: today / 7 days / all, and a project ("All projects" shows all of them even when `ccx ui --project` was used). Totals by agent come biggest first. The newest 40 tasks are listed and the page says how many were left out, with their tokens and $. (3) Lead conversations: the lead sessions that delegated, newest first; opening one reads its session file then (not before) with the same functions as `ccx lead --breakdown` and `ccx lead --cache`: what every turn re-reads, part by part, the advice, and the turns where the prompt cache broke with the likely cause. Only a session the ledger names is read; answers are capped in size; every label and line of session text is escaped; an empty hub says what to run.
**Who leads**, on each project page (and under a task's history): the lead now, when each lead worked (from the
handoff records in `.ccx/handoffs/`), and "Continue with Codex" / "Continue with Claude" (and DeepSeek where `dsh` is
installed). The button runs `ccx handoff --to <other> --by <current> --cwd <project>` through the same second click,
adding `--from-transcript <current> --no-model` when the current lead's conversation file for that folder exists (by
code, never a model); the answer is the handoff file and the one line to give the other tool when you open it there
(Claude Code and Codex also show the handoff once at session start; for DeepSeek the line tells it to read the file).
Without that conversation file the handoff is a blank template, and the page says so before and after: fill it in
first. The task timeline marks who was leading when the task was asked and every switch since. This is the only new
write path on the page.
**`ccx demo`** (or `ccx ui --demo`) shows all of this without an account: it writes made-up data (two projects, runs
in every state with a real snapshot diff, one hand-off's full receipt — cost, the check ccx ran, the other vendor's
review — the reviews as runs of their own, a work queue, a stopped board thread and an `@person` question, a month of
costs, per-request numbers and a Codex helper session for the token page) into a new folder in the system's temporary folder, points only its own process there, and serves the same
page, marked "demo data". It works offline and starts no agent: a button that would start one shows its command
only; a verdict or a handoff is written into the demo folder, which is removed when the page closes (`--keep` or
`--dir` keeps it; `--export FILE` writes a static copy and then deletes the folder too). `--dir` takes only a new or
empty folder, or an earlier demo folder.
Evaluations and tests (eval-* labels, `--no-ab`, ccx's probes, runs in the temporary folder or a project's `.ccx`
folder) stay hidden until you press "show evaluations and tests"; `ccx verify RUN --dismiss --note why` clears a
leftover from "waits for you" without counting it right or wrong, and routing never learns from it.

Screenshots: `ccx demo`'s data, taken by `python scripts/make_shots.py`.

<img alt="ccx ui overview: what waits for you across projects (questions, your calls, results to check), what is running (demo data)" src="assets/ui/overview-en.png" width="100%">

<img alt="ccx ui task page: a task as an org chart, one column per worker; the side panel is one hand-off's receipt: who, cost, the check ccx ran again, the review, the verdict, the files actually changed (demo data)" src="assets/ui/task-en.png" width="100%">

<img alt="ccx ui decision card: a run whose review still finds problems, what the agent says beside what ccx ran (demo data)" src="assets/ui/judge-en.png" width="100%">

<img alt="ccx ui as the manager's board: projects, the current leads, this month's spend (spend only until a saving is measured), who is reliable at what (demo data)" src="assets/ui/month-en.png" width="100%">

<img alt="ccx ui, where tokens go: one ledger across agents, requests per run, a Codex helper session under its run (demo data)" src="assets/ui/tokens-en.png" width="100%">

<details><summary>Chinese interface; dark theme</summary>

<img alt="ccx ui overview in Chinese (demo data)" src="assets/ui/overview-zh.png" width="100%">

<img alt="ccx ui task page in Chinese, with the receipt (demo data)" src="assets/ui/task-zh.png" width="100%">

<img alt="ccx ui manager's board in Chinese: projects and this month's spend (demo data)" src="assets/ui/k6-month-zh.png" width="100%">

<img alt="ccx ui task page in English, dark theme (demo data)" src="assets/ui/task-en-dark.png" width="100%">

</details>

The screenshots above come from `ccx demo`'s made-up data (`python scripts/make_shots.py`); `python scripts/ui_demo.py`
still builds a throwaway hub with real ccx runs on stand-in CLIs, nobody's real work.

## How it works (one example)

In Claude Code you say: "make `loader.py` accept a custom delimiter and add tests."

1. **Score and brief.** Claude (lead) scores the task on 5 items: 2 files, one module, clear goal, low risk, an
   existing pattern to follow. It writes a brief of under 200 words: the goal, the files to look at, and what
   "done" means.
2. **Pick a model.** It runs `ccx run --from claude --files 2 --coupling one --clarity goal "…"`. ccx asks the
   **task-routing** skill for each agent:model:effort's success probability and cost per success. Here it picks
   `codex:gpt-6.1-sol:medium`. If doing it yourself is cheaper, or the task should be split first, ccx says so and
   delegates nothing.
3. **Run headless.** ccx runs `codex exec -m gpt-6.1-sol -c model_reasoning_effort="medium" …`. The session id is
   saved the moment it appears. Codex reads the files, edits and runs the tests on Codex's own quota.
4. **Return a summary.** Codex must answer in a JSON schema (`status / summary / files_changed / verification / …`).
   Claude reads only that, glances at `git diff`, and records its verdict with `ccx verify <run_id> --ok 1`.
   A passed check says what it passed on: `check passed (covers: tests/test_x.py)` lists the test files the
   pytest / unittest command names (folders expanded; "not known" for other commands), adds `(only -k …)` when a
   filter or a node id runs part of them, and flags `basis changed` when the sub-agent edited one of them or a
   `conftest.py` above them, "tests added by the sub-agent in …" when it only added tests to one, and "written by
   the sub-agent" / "only tests the sub-agent wrote" for new test files. It is shown in the result, the recap line,
   `ccx show` and the ledger. When every test file the check ran was written or changed by the sub-agent in that
   run, the run is not plain ok: kind `ok_self_checked` (still exit 0; `check.basis` and `needs_lead` say "not
   independently verified", `ccx ui` asks the person, it is never auto-judged right). `[escalate] on_self_checked`
   decides what else happens: `review` (default) has it reviewed against the task text, `rung` has one stronger
   rung redo it first, `off` only labels it. A read run that answers nothing (an empty summary) is
   not ok: kind `no_answer`, with a hint to ask again on a stronger tier.
5. **Recover from problems.**
   - Codex reports `blocked`: ccx continues **in the same Codex session** one rung up (high), with no re-briefing.
   - Codex says done but ccx's own `--check` fails: it climbs a rung too (in the same session when the agent stays
     the same). With `ccx config set defaults.focused_retry true` that attempt is handed the failing command and the
     last ~2000 characters of its output and told to fix only that (default off until a measured round backs it).
   - Codex is out of quota: Claude takes over (experimental: tested with stand-ins only, no real quota stop seen yet).
   - A timeout or crash: `ccx resume <run_id>` continues (as does `ccx task resume` for a checkpointed task),
     keeping the run's label, acceptance check and review setting (`ccx resume` takes `--check` / `--review` to
     change them; `ccx task resume` always keeps them).
   - You want it to stop: `ccx stop <run_id>` ends the sub-agent and everything it started; `ccx resume` goes on.
6. **Learn and report.** Every run goes into a ledger and back into task-routing / task-split, so the next pick is
   better. `ccx report` builds a dashboard: who spent how many tokens of which kind, quota use and spend; a saving only once `ccx trial` has measured one.

The other way round, run the same command inside Codex with `--to claude`: Codex leads, Claude Code is the sub-agent.
Codex's sandbox decides whether that works: ccx writes its run records into the hub and the sub-agent needs the
network. `ccx doctor --codex-lead` checks it (row "Codex as lead (sandbox)"; plain `ccx doctor` shows it as one info line). On Windows only `danger-full-access` worked in real
runs (codex-cli 0.164): in `workspace-write` the commands run as a separate sandbox account, and a Claude sub-agent
started there refused every edit, even with the hub and `~/.claude` as writable roots and the network on.
**Safety:** full access means every command the Codex lead runs has your rights, with no sandbox (your files, the
network, your credentials); use it only for a lead you would trust at your own keyboard. A narrower way, by Codex's
docs but **not yet checked on a real run**: keep `workspace-write` and let only ccx's hand-out commands
(`run`, `ask`, `resume`, `discuss`) run outside the sandbox with a Codex rule: `ccx doctor --codex-rule >>
~/.codex/rules/ccx.rules` (rules are experimental in Codex; `ccx doctor` then says Unknown, not ok).

**Does the sub-agent know what you discussed with the lead?** Not directly: copying a long conversation into every
sub-agent would be expensive, and Claude and Codex can't share a context window anyway. The sub-agent gets the
brief (the lead's distilled summary), the project background, shared memory and the files themselves. What gives
continuity is the **sub-session**: the next task from the same conversation, folder and agent within an hour
continues the same sub-session automatically, so it remembers what it already read and did (`--new` for a fresh one).
From Claude Code to a Claude sub-agent, `--fork` can start it from a copy of your whole conversation.

## Where shared things live

Everything personal lives in **your hub** folder. `ccx init --hub <path>` sets it and stores it in
`~/.ccx/config.toml`. The default is `~/.ccx-hub`, and `CCX_HUB` overrides it. The repo holds no personal content.

| What | Where | How both tools see it |
|---|---|---|
| memory snapshot "1" | `memory/MEMORY.md` | Claude: `@import` in `~/.claude/CLAUDE.md`; Codex: a managed block in `AGENTS.md` |
| memory increments "+2" | `memory/journal.jsonl` + `ccx/cursors.json` | a SessionStart hook runs `ccx mem delta --as <me>`: only the other side's new lines, once |
| skills | one copy each (`hub/skills/`) | linked into both tools (junction / symlink) |
| MCP servers | `mcp/servers.json` | `ccx sync` registers them with `claude mcp add-json` / `codex mcp add` |
| project background | `<project>/.ccx/context.md` | every brief points to it; the sub-agent reads it itself |
| runs / ledger | `ccx/runs/`, `ccx/ledger.jsonl` | `ccx show` / `ccx stats` / `ccx report` |
| learned estimates | `ccx/routing-state.json`, `ccx/split-state.json` | shared by both agents, updated after each verified run |
| settings | `ccx/settings.toml` | `ccx config set ...` |
| work queue | `<project>/.ccx/queue/` | `ccx q tree`; open work is shown at session start |

**Which memory for what.** A standing rule the user states ("always commit each change") belongs in the user's
shared instructions file, added only once the user agrees. A fact about a project goes into `ccx mem add --project`
(with `--source` where it came from). A note that is no longer true is replaced (`--supersedes N`), not left next
to the new one; one nobody has checked for 30 days is shown as "to check" (`ccx mem stale`, `ccx mem verify N`);
`ccx mem search` finds older ones, and a session start carries at most ~600 tokens of new lines. Each tool's own
automatic memory stays its own: ccx doesn't copy one into the other.

**Finding and sorting notes.** `ccx mem search` ranks notes by BM25: a rare word counts more than a common one and a
note needn't contain every word (`--all-words` keeps the old filter, `--limit N`). Every note has one of five kinds —
preference, constraint, fact, pitfall, event (偏好 / 约束 / 事实 / 坑 / 事件), else other: `ccx mem add --kind`, and
an older note's kind is guessed from its topic or words when it is read (`ccx mem kinds --list`; the journal is never
rewritten). With `[memory] by_kind = true` a session start carries only new preferences and constraints, a
sub-agent's brief picks pitfalls, facts and others by BM25, and events are found by search only. It is off by default,
so starts and briefs carry what they did; whether to turn it on is decided by measurement (the confirmation
run), since the week-long H11 trial was voided on 2026-10-26. `ccx mem compact --by project`
writes one short block per project to `memory/scenes.md`; `[memory] start_scene = true` adds the current project's
block at a session start (off by default: a start's notes are already capped at ~600 tokens).

**Hooks never hold up a turn.** The session-start hook (`ccx mem delta`) and the per-turn hook (`ccx turn`) stop at
`[hooks] timeout_s` (default 2 s; `ccx config set hooks.timeout_s N`, 0 = no limit): past it they print nothing and
exit 0, and `ccx/hook-timeouts.jsonl` gets one line (command, seconds, the step it was in). `ccx doctor` shows how
many there were in the last 7 days.

**Which shared skills are used.** `ccx skills stats [--days N] [--json]` counts, from the Claude Code and Codex
session files, how often each shared skill (hub `skills/` plus this repo's) was loaded in each tool and when last,
and lists the ones never loaded with an estimate of the tokens their descriptions take every turn (from characters,
not a tokenizer). Read only: it suggests, it deletes nothing. A first `ccx setup` also offers, once and only on a
terminal, to look through the last 7 days of sessions with `ccx mem suggest`'s rules (no model) and asks about each
preference or pitfall it finds; only the ones you say yes to are written (`ccx mem accept`'s path).

## Tiers (`config/tiers.toml`, override in `hub/ccx/tiers.toml`)

Fixed tiers are the fallback. With rubric flags, task-routing picks by success probability and cost per success,
and calibrates itself from real outcomes.

| Tier | Work | Codex | Claude Code | Gemini CLI (experimental) |
|---|---|---|---|---|
| T0 | two or three steps | don't delegate | don't delegate | don't delegate |
| T1 | mechanical | gpt-6-luna · low | haiku · low (no MCP loaded) | flash-lite |
| T2 | routine development | gpt-6.1-sol · medium | sonnet · medium | flash |
| T3 | hard | gpt-6.1-sol · high | opus · high | pro |
| T4 | critical / research | gpt-6-astra · xhigh | opus · max | pro |

Gemini uses the CLI's aliases, so new model releases need no config change. Gemini CLI has no effort flag.
DeepSeek Harness (`--to dsh`): deepseek-flash at low / high / max for T1-T3, deepseek-v4-pro · max for T4.

**Pay-per-token agents** (the providers in `[providers.*]` and `dsh`) spend real money, so each has a `daily_usd` cap
(default $1); a provider whose key isn't in your environment takes part in nothing (`ccx agents` shows `ready`). A
model without a known price is refused, since its spend couldn't be counted against the cap. They are never picked as
a quota fallback or as a reviewer on their own; only DeepSeek through Claude Code is in automatic routing (it has
calibration and prices), the others need `--provider` / `--to` until they are calibrated.

## Experimental: lean sub-agent switches (`[subagent]`, off until measured)

Three switches in `config/tiers.toml` (override in `hub/ccx/tiers.toml`) change what a delegated sub-agent loads at
its start. Each ships at today's behaviour and stays there until a before / after measurement shows the right-rate does
not drop ([plan and arms](research/2026-10-30-b3-lean-switches-plan.md)). There is no per-run flag. Every run records
the switches it ran with in run.json (`subagent_switches`); a ledger row names the ones away from the default.

**Measured 2026-10-31: all three keep their defaults and stay experimental**
([report](research/2026-10-31-b3-lean-switches.md)). `codex_memories = false` Unknown; `clean = true` Fail (3
hold-out pairs lost); `codex_lean_tools = true` Fail under the registered rule (right 29 vs 30), undecided in a
post-hoc reading. No switch showed a reliable token saving in the paired comparison.

| Key (default) | When changed | Risk |
|---|---|---|
| `codex_memories = true` | `false`: every Codex rung gets only the three memory settings the evaluation's clean room uses (`features.memories`, `memories.use_memories`, `memories.generate_memories` = false); never `--ignore-user-config`, which would also drop provider and sandbox settings | low: the hold-out run hc1 ran with memories off |
| `clean = false` | `true`: Codex / dsh get an empty HOME of their own per run (`hub/ccx/agent-home/<run>`, emptied at the start, others removed after a day). That removes only `~/.agents/skills`: CODEX_HOME stays, so `~/.codex/AGENTS.md`, `~/.codex/skills` and memories still load; DSH_HOME, the git config and toolchain homes that exist (`~/.rustup`, `~/.cargo`, `~/.local`) stay pinned to the person's own, but other tools a test command runs see the empty HOME too. Claude gets `--disable-slash-commands` and `--setting-sources project,local` (no user settings or skills; MCP stays as `--mcp` / `[claude_subagent] mcp` asks). The prompt gains one line asking for the summary in the brief's language; a Claude sub-run gets the Agent tool only with `--parallel`. A `--fork` run keeps the lead's start on every attempt | medium: on Claude, personal skills (a verification skill, say) and user settings no longer reach the sub-agent; on Codex only the `~/.agents` skills go |
| `codex_lean_tools = false` | `true`, write runs only: Codex without web search (`-c web_search="disabled"`), image generation and goals (`--disable`), and on OpenAI's own server without apps / plugins (checked on codex-cli 0.164.0); read runs keep web | low; a write task that needs current docs from the web loses them |

Not to be confused with `[subagents]`, which caps what a sub-agent's own sub-agents may spend. That section has one
experimental key too, `fork_turns = "all"` (default: nothing added). With `"none"`, a `ccx run --parallel` Codex run (native,
not through a provider) is also told to start its own sub-agents with `fork_turns="none"` (a `spawn_agent` parameter of codex-cli 0.164.0) and
to write into each one's message the files, goal, constraints and check it needs, so a child does not re-read the
parent's history on every request. Claude's Agent tool never passes the parent's conversation, so Claude runs are
unchanged. Such a run records `parallel_fork_turns` (`all` or `none`; `parallel_fork_turns_moved` when it
went on to another agent). Off until measured (M3).

### Experimental: `ccx batch --merge` (`[merge]`, off until measured)

A sub-agent's input is mostly a prefix re-sent on every request, so five small pieces run separately pay that start
five times. With `--merge` (or `[merge] default = true`; `--no-merge` turns it off for one batch), write pieces of one
batch that share folder, agent, model rung or tier, worktree and namecheck setting, carry an estimate of at most
`piece_minutes` (5; a piece without `minutes` is never merged) and declare no common path (`paths`, a list; in a batch
plan `files` stays the routing estimate) run as one run of up to `max_pieces` (5) pieces and `total_minutes` (15).
That run never escalates and starts no sub-agents of its own. Afterwards each piece is judged on its own: by its
`check` when it has one (whatever the run's overall status), else by its own `[id] done|partial|failed` line in the
summary; a piece with neither is `unconfirmed` (not done, not redone: look at the diff). Pieces not done get one
follow-up in the same session; a piece whose check still fails, or that still reports failed or partial, becomes a
run of its own on the usual ladder. If the run stopped for a reason a retry would meet again (quota, login, `ccx
stop`, timeout, the machine, budget), nothing more starts: those pieces are `not_run`, for `ccx resume` of the run
that stopped. If the review (after its fix round) or ccx turns the merged diff down as a whole (`review_issues`,
`review_failed`, `no_changes`, `check_broken`), no piece counts as done, whatever its own check said. After a follow-up
or a spun-off run, checks that had passed are run again and the last result counts. `results`
keeps one entry per piece (with `merged_run`, `merged_with`, `piece_state`), and `ccx undo <run> --piece <id>` puts
back only the paths that piece declared (no verdict; only for a merged run in the project folder: in a clean repository
parallel writers get worktrees, which have no undo snapshot). Follow-up and spun-off runs carry `merge_of` in run.json and the
ledger, and a `merge` ledger event lists every piece's outcome. Costs: reviews judge the whole diff (the 50-line
trigger counts every piece; a follow-up and a spun-off run may be reviewed again), wall time is longer, and the exit
code is 2 when any merged piece is not done (a piece run alone keeps `ccx run`'s exit code). An explicit `--merge`
wins over `[lanes] default` and an explicit `--lanes` over `[merge] default`; both on the command line is an error.

## Safety

- Sub-agents **may edit files** by default:
  - Codex: `workspace-write` sandbox.
  - Claude: `acceptEdits` plus a tool allow-list; only git/python/pytest/npm/node commands are allowed.
  - Gemini: `auto_edit` approval mode.
  - DeepSeek Harness: `DSH_PERMISSION_MODE=workspace-write` (`read-only` with `--mode read`); ccx also turns off its
    default session-log upload to DeepSeek and its telemetry for these runs.
  - `--mode read` makes any of them analysis-only. Parallel writers go to separate git worktrees.
- A sub-agent cannot delegate again (`CCX_DEPTH`).
- `ccx sync` is a dry run unless `--apply`:
  - Each changed file is backed up once a day.
  - Codex's `config.toml` only gets one marked hook block, validated with a TOML parser before writing.
  - MCP servers are added only through each tool's own CLI.
- ccx never reads or copies account credentials. Provider keys are read from your environment and never stored.
