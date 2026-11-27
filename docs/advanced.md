# Advanced: every command and switch on one page

English · [中文](advanced.zh.md) · back to the [README](../README.md)

The README and `ccx -h` show the short path: install, `ccx setup`, `ccx run`, `ccx show`, `ccx verify`. Everything else
is here. **Nothing was removed**: each command, option and config key below still works as before; they are only
kept off the default path. The contents of this page come from `python ccx.py -h`, each command's `-h` and
`config/tiers.toml` (ccx 0.7.0); when they disagree with this page, they win.

## How to read the labels

| Label | Meaning |
|---|---|
| **Measured** | the option or its default has a published measurement; the source is linked or named |
| **Experimental** | shipped, off by default or on without a real-run test (the effect is Unknown or only partly measured) |
| **Measured, not recommended** | measured, and the candidate did not clear its gate (or the evidence is Unknown); kept for reproduction |
| **Shipped** | ordinary plumbing or a convenience; no claim about its effect is made |

Pass/Fail words follow [Features, "Experimental, measured, not recommended"](features.md#experimental-measured-not-recommended)
and [Measured](measured.md). They are historical results on older code, not a test of today's main.

## Where things are set

- `ccx -h`: the everyday commands. `ccx advanced` (same as `ccx -h --all`): every group. `ccx dev`: the developer
  commands (`ccx dev trial` is `ccx trial`). `ccx <command> -h`: one command in full. `ccx --version`.
- `ccx config list | get | set <key> <value>` changes the keys in the tables below and writes your personal config
  (`~/.ccx/config.toml`, or the file `CCX_CONFIG` names). Defaults are in `config/tiers.toml`; the same structure in
  `<hub>/ccx/tiers.toml` overrides only the keys you write there. Keys that `config set` does not know (the tier table,
  role table, providers, `[review] also` ...) are edited in that file.
- Project settings: `.ccx/` in the project (`ccx project init`), `.ccx/roles.toml` for roles, `.ccx/autonomy.toml`
  (a project can only lower the autonomy level).

## Commands

### Everyday (shown by `ccx -h`)

| Command | What it is for | Label |
|---|---|---|
| `setup` | guided first run: check, hub, init, sync (asks first), doctor, selftest. `--yes`, `--hub` | Shipped |
| `doctor` | check installs, logins and wiring. `--verbose`, `--codex-lead`, `--backfill-kinds` (one-off, see below) | Shipped |
| `doctor --codex-rule` | print a rule that lets a sandboxed Codex lead run ccx outside its sandbox | Experimental (not yet checked on a real run) |
| `run` | delegate one task to the other agent (all options below) | Measured: see [Measured](measured.md) |
| `ask` | quick read-only second opinion (`--to`, `--from`, `--cwd`, `--brief-file`) | Shipped |
| `resume` | follow up in the same sub-session. `--bg --wait`, `--env-fixed`, `--model --effort`, `--review`, `--check`, `--tier`, `--no-escalate`, `--budget`, `--max-usd`, `--namecheck`, `--from`, `--brief-file`, `--user-task-file` | Shipped |
| `stop` | stop a running delegation (its whole process tree). `--wait` | Shipped |
| `undo` | put back the files a write run changed; a dry run unless `--apply`; `--wrong` also records a verdict; `--piece` for a merged batch run | Shipped |
| `verify` | record your verdict (`--ok 1/0`, `--note`, `--reason`, `--dismiss`); the spot-check and sweep options are below | Shipped |
| `show` | show a run: `--full`, `--wait [SECONDS]`, `--any` for several ids | Shipped |
| `q` | the project's work queue: `add`, `ls`, `tree`, `budget`, `done`, `accept`, `run`, `resume` | Shipped |
| `ui` | live page: `--project`, `--no-open`, `--port`, `--days`, `--export FILE`, `--demo`, `--keep` | Shipped |
| `mem` | shared memory: `add`, `verify`, `search`, `stale`, `delta`, `show`, `status`, `compact`, `kinds`, `report`, `suggest`, `suggestions`, `accept`, `reject` | Shipped |
| `handoff` | pass the baton to the other lead: `--to` (required), `--by`, `--file`, `--next`, `--title`, `--from-transcript` (builds it from the old session file; with `--session`, `--no-model`, `--max-chars`), `--cwd`; `--minutes`, `--difficulty`, `--risk` only with `lead.model_by_task` | Shipped |
| `lead` | what each turn of your lead re-reads: `--breakdown`, `--cache`, `--suggest`, `--hours`, `--limit`, `--session`; `--hint`, `--threshold`, `--as` are for hooks | Shipped |
| `demo` | `ccx ui` on made-up data, no account needed: `--no-open`, `--port`, `--export`, `--dir`, `--keep` | Shipped |

### Memory and context

| Command | What it is for | Label |
|---|---|---|
| `ctx` | per-project context file every sub-agent reads: `init`, `show`, `add` | Shipped |
| `project` | the project layer (`.ccx/`): `init`, `status`, `compact` | Shipped |
| `fresh` | hand a long conversation to a fresh one of the same tool: `--as`, `--session`, `--note`, `--no-model`, `--max-chars`, `--launch`; `--minutes`, `--b`, `--risk` only with `lead.model_by_task` | Shipped; the model-by-task part is Measured, not recommended (Unknown) |
| `inbox` | keep a file or an email the user gave you in `.ccx/inbox` with one journal line: `--file`, `--name`, `--by` | Shipped |
| `skills` | `find` (search the shared library), `install` (`--apply`, `--replace`), `stats` | Shipped |

### Accounting and reports

| Command | What it is for | Label |
|---|---|---|
| `stats` | tokens and time per agent and tier: `--summary`, `--days` | Shipped |
| `report` | static HTML dashboard; `--days`, `--out`, `--no-lead`, `--publish`, `--include-evals`; `--daily [DAY]` (+ `--tz`, `--quota-events`, `--quota-workspace`, `--quota-split`, `--real-use`) writes one Markdown page for a day | Shipped; a saving is shown only after `ccx trial` measured one |
| `quota` | subscription quota by pace: `--probe`, `--refresh`, `--backfill` | Shipped |

### Between agents (open sessions call these)

| Command | What it is for | Label |
|---|---|---|
| `peek` | read-only look at another tool's open session in this project (`--session`, `--turns`, `--max-chars`, `--json`, `--cwd`) | Shipped |
| `board` | unread board messages: `--as`, `--thread`, `--all`, `--limit`, `--peek`, `--init`, `--sync`, `--force`, `--cwd` | Shipped |
| `say` | write to other open sessions: `--to`, `--thread`, `--from`, `--now`, `--codex-thread`, `--wait`, `--resume`, `--cwd` | Shipped |
| `reply` | answer one board message: `--from`, `--cwd` | Shipped |

### Advanced (hub, several projects, wiring)

| Command | What it is for | Label |
|---|---|---|
| `init` | create the shared hub: `--hub`, `--snapshot`, `--external-sync`, `--force` | Shipped |
| `projects` | the catalog of your projects: `scan` (`--root`), `show` | Shipped |
| `where` | which project a sentence is about: `--limit` | Shipped |
| `intake` | tasks you file as issues in a PRIVATE GitHub repository: `status`, `list`, `pull`, `ask`, `done` (`--pr`, `--branch`, `--cost`, `--unverified`, `--close`) | Shipped (needs `intake.github`) |
| `sync` | link skills, memory, hooks and MCP into both tools; dry run unless `--apply`; `--only skills,memory,hooks,mcp` | Shipped |
| `config` | `set`, `get`, `list` | Shipped |
| `uninstall` | remove ccx hooks, blocks and links; dry run unless `--apply` | Shipped |
| `repair` | re-count ledger rows written before a counting fix; dry run unless `--apply` | Shipped |
| `agents` | each agent CLI: vendor, abilities, tested version | Shipped |
| `ability` | task-specific model evidence and your preferences: `show`, `rebuild`, `set VENDOR.MODEL TASK prefer\|avoid\|clear`, `--json`; advisory only | Shipped (preferences do not steer routing yet) |
| `roles` | opt-in role assignments: `show`, `set`, `unset`, `--cwd`, `--project`, `--ability` | Shipped; empty by default |
| `relay` | quota handoff: `capture` and `continue` (`capture`: `--hook`, `--source`, `--session-id`, `--goal`, `--progress`, `--next-step`, `--check`; `continue`: `--to`, `--budget-seconds`, `--old-stopped`, `--launch`, `--force-unconfirmed`, `--check`, `--use-packet-check`, `--check-timeout-seconds`; both: `--cwd`, `--git-timeout-seconds`) | Experimental (opt-in, no transparent takeover; see [relay](relay.md)) |

### Maintenance (`ccx -h --all` lists names only)

| Command | What it is for | Label |
|---|---|---|
| `task` | `status`, `resume` (`--same`, `--from`) a checkpointed task | Shipped |
| `send` | push a message into a live Codex conversation: `--to codex`, `--thread`, `--list`, `--wait`, `--force` | Shipped |
| `plan` | task-split: `size`, `check`, `template`, `record`, `show` | Shipped |
| `batch` | run a plan file: `--lanes N`, `--merge`, `--no-merge`, `--force`, `--from` | Shipped; `--merge` Experimental, `--lanes` Measured, not recommended as a default |
| `route` | which agent, model and effort would take a task, and whether to delegate at all | Shipped |
| `propose` | the same, as an offer for the person to accept (`--no`, `--stats`, `--days`) | Shipped |
| `way` | one task, one or two builders: `--with`, `--check`, `--yes` (about twice the cost), `--dry-run`, `--stats`, `--days`, `--include-evals`, `--risk`, `--kind`, `--label`, `--brief-file`, `--cwd`, `--from`, `--force` | Shipped |
| `discuss` | a short multi-model discussion: `--with`, `--rounds`, `--tier`, `--dry-run`, `--confirmed`, `--bg`, `--show`, `--list`, `--context-file`, `--question-file`, `--cwd`, `--from` | Shipped |
| `turn` | the per-turn hook line: `--as`, `--threshold` | Shipped |
| `sum` | run a command and keep only a short summary: `--kind`, `--max-chars`, `--shell`, `--ask` | Shipped |
| `archive` | archive finished sessions: `--older-than`, `--apply`, `--restore` | Shipped |
| `autonomy` | project manager level: `set [L0\|L1\|L2] --project --auto-merge`, `merge RUN --apply` | Shipped (default L1) |
| `selftest` | test each installed agent: `--agents`, `--provider` | Shipped |

### Developer (measuring ccx itself; also `ccx dev <command>`)

| Command | What it is for | Label |
|---|---|---|
| `trial` | a week of half-self, half-delegated tasks: `start` (`--days`, `--rate`, `--note`), `stop`, `tag`, `report` (`--markdown`) | Shipped |
| `ab` | `done --ok 0\|1 AB_ID`: close an A/B self-run sample | Shipped |
| `bench` | public benchmark data for routing: `sources`, `refresh` | Shipped |
| `improve` | log a problem and its fix for a skill or tool: `add`, `list` | Shipped |
| `namecheck` | names no scope defines in changed Python functions: `--run`, `--base`, `--json`; exit 1 on a hit | Measured: [config note](../config/tiers.toml) (0 false positives on this repository and the standard library; one true hit in the r5 files) |

## `ccx run`: every option

Most runs need only the task, `--check` and sometimes `--mode`, `--worktree`, `--bg`. The rest is for control.

| Group | Options | Label |
|---|---|---|
| Task | `brief ...` (or `--brief-file`, stdin), `--user-task-file`, `--label`, `--cwd`, `--project`, `--rules-ok` | Shipped |
| What and where | `--mode read\|write`, `--worktree`, `--no-worktree`, `--base head\|upstream`, `--new`, `--fork`, `--seat NAME`, `--mcp` | Shipped |
| Acceptance | `--check CMD`, `--review auto\|on\|off`, `--namecheck warn\|fail\|off`, `--strict-brief` | `--strict-brief` Experimental; the rest Shipped |
| Background | `--bg`, `--wait SECONDS` | Shipped |
| Who | `--to`, `--from`, `--provider`, `--role`, `--model`, `--effort` (only with `--model` or `--provider`), `--tier T0..T4`, `--tradeoff save\|balanced\|fast\|cheapest`, `--no-escalate`, `--no-fallback` | `--tradeoff save` is the shipped default (no measurement compares it with the other tiers); the rest Shipped |
| Routing rubric | `--files`, `--independent-parts`, `--coupling`, `--clarity`, `--risk`, `--novelty`, `--b`, `--minutes`, `--kind` | Shipped |
| Limits | `--budget USD` (its own sub-agents), `--max-usd USD` (the whole delegation), `--allow-subagents`, `--no-subagents`, `--subagents auto\|off\|N`, `--parallel` | Shipped |
| Context | `--context auto\|on\|off`, `--user-words-file PATH` | `--context` Shipped; `--user-words-file` Experimental |
| Autonomy and queue | `--autonomy L0\|L1\|L2`, `--approved`, `--proposal`, `--task`, `--step`, `--quota AGENT=USED`, `--force`, `--no-ab` | Shipped |
| Look first | `--dry-run`: the rungs it would try; runs nothing | Shipped |

Other commands' options not in the tables above: `ccx q add` (`--brief --dep --parent --check --minutes --mode --kind --to
--budget --plan`), `q ls` (`--gate --long`), `q run` and `q resume` (`--max --once --lanes --gate --from --force --bg`), `q accept` (`--all-ready --check --dry-run
--into-protected`), `q done` (`--ok --note`), `verify` spot checks (`--sweep --after-h --sample --list --days --project
--state --include-evals --builtin --b --agent-id`), `route` and `propose` (`--lead --ctx-files --ctx-tokens --lead-ctx
--turns-left --requests --needs --quota`). All are **Shipped**; read `ccx <command> -h`.

## Config keys (`ccx config set <key> <value>`)

Defaults are the shipped values in `config/tiers.toml`.

### Routing and who does the work

| Key (default) | What it does | Label |
|---|---|---|
| `routing.mode` (`auto`) | `off`: ccx delegates no new work; review, `ask`, `discuss` and talk still work. `--force` bypasses | Shipped |
| `defaults.tradeoff` (`save`) | `save`, `balanced`, `fast`, `cheapest`, or a 0..1 knob | `save` is the shipped default (no measurement compares it with the other tiers) |
| `policy.picked` (empty) | the tier you pick for all work; pre-authorises what it delegates; empty offers first | Shipped |
| `routing.require_ready` (`true`) | prefer installed CLIs with local login evidence | Shipped |
| `routing.default` (`auto`) | `self_first`: self-first delegation gate ([self-first](self-first.md)) | Experimental (not measured) |
| `routing.small_self` (`false`) | `route` and `propose` advise doing a small task yourself ([small tasks](small-tasks.md)) | Experimental (until a measured round backs it) |
| `routing.small_self_by` (`files`), `routing.small_self_files` (1) | what "small" is sized by: files, or `cost` | `cost`: Experimental |
| `routing.small_self_overhead_usd` (0.035), `routing.small_self_quota` (0.9) | `cost` threshold and the quota share from which small tasks are delegated again | Experimental (0.035 is the pg1 ledger median) |
| `routing.small_self_run` (`false`) | refuse small-task `ccx run` for leads; `--force` bypasses | Experimental |
| `routing.strict_escalate` (`false`) | unchecked writes or strict interfaces skip the cheapest rung | Experimental |
| `routing.cold_start` (`false`) | with no learned outcome for the candidates, the first tier comes from `[cold_start]` | Experimental (bounds provisional) |
| `defaults.ab_self_rate` (0.1), env `CCX_AB_RATE` | share of routable tasks the lead does itself to measure savings; 0 = off | Shipped |
| `defaults.max_escalations` (1) | stronger rungs to try after a verified failure | Shipped |
| `defaults.capacity_fallback` (`true`) | skip models at capacity, at most two switches | Shipped |
| `defaults.focused_retry` (`false`) | a retry after a failed `--check` resumes the session with the failing output | Experimental (the r6a retries were slow; waits for a measured round) |
| `defaults.max_parallel` (3) | parallel sub-agents in `ccx batch` | Shipped |
| `dispatch.cheap_first` (`false`) | cheap first attempt, needs an independent `--check` ([dispatch](dispatch.md)) | Experimental |
| `lead.claude` (`opus`), `lead.codex` (`gpt-6.1-sol`) | the lead's model, for savings estimates | Shipped |
| `lead.model_by_task` (`false`) | choose a new lead conversation's model from difficulty (`[lead_by_task]`) | Measured, not recommended (Unknown: n=10 per arm, one round) |
| `lead.slim_small`, `lead.slim_context` (`false`) | slim lead-side flow ([lead-slim](lead-slim.md)) | Experimental |

### Review and acceptance

| Key (default) | What it does | Label |
|---|---|---|
| `review.mode` (`read`) | `tests`: independent task-derived tests; legacy `auto`, `on`, `off` still valid | `read`: Shipped; `tests`: Measured, not recommended (Fail: 0/15 confirmed catches; [test review](test-review.md)) |
| `review.tests_model`, `review.tests_effort` (empty) | model and effort of the test reviewer; only with `mode = "tests"` | Measured, not recommended (as `tests`) |
| `review.contract_diag` (`false`) | offline contract diagnostic; never changes verdicts ([diag](review-contract-diag.md)) | Experimental |
| `review.skip_when_clean` (`false`), `review.skip_max_files` (3), `review.skip_max_lines` (49) | skip an automatic review when the run is clean | Experimental (effect Unknown, [#427](features.md#experimental-skip-the-review-when-the-run-is-clean-review-skip_when_clean-off-until-measured)) |
| `escalate.on_self_checked` (`review`) | when `--check` passed only on tests the sub-agent wrote: `review`, `rung` or `off` | Shipped. `review` is the default because in pg1 the check passed in all 18 hidden-test failures; a later pg3b replay shows review did not catch them ([Measured](measured.md)), so it is not proof the default works |
| `check.baseline` (`off`), `check.sensitivity` (`off`) | rerun a failed check on the clean dispatch tree (`on_fail`); compare passing checks too (`warn`, `escalate`) ([check baseline](check-baseline.md)) | Experimental |
| `defaults.namecheck` (`warn`; file only) | `warn`, `fail`, `off` for `--namecheck` | `warn` default: Measured (0 false positives, see `namecheck` above); `fail`: not measured (waits for an r5 before/after) |
| `git.auto_stage_resolved` (`false`) | host stages marker-free resolved conflict paths; never commits ([git-pending](git-pending.md)) | Experimental |
| `security.credential_guard` (`false`), `security.credential_dirs` (`[]`) | deny credential directories to sub-agents ([credential guard](credential-guard.md)) | Experimental (Claude: tool denies, not OS isolation; Codex: beta) |

The file-only `[review]` keys are **Shipped** unless named: `min_lines` (50), `weak` (`true`), `weak_daily` (20),
`fix_rounds` (1), `max_diff_chars` (12000), `by`, `also`, `coverage_rubric` (`true`). Measured, not recommended or
Experimental, all off: `fix_rereview = "focus"` (Fail: [replay, 40 pairs](features.md#experimental-measured-not-recommended)),
`context = true` (replay: 11 of 28 known bugs caught, 19 without it), `must_needs_repro` (conclusion open),
`cache_ttl` (not A/B measured); their evidence is the comments in `config/tiers.toml`, not the Features table.

### Limits, time and sessions

| Key (default) | What it does | Label |
|---|---|---|
| `defaults.timeout_sec` (1800) | per-attempt timeout ([timeouts](timeouts.md)) | Shipped |
| `defaults.timeout_reminder` (`false`) | tell the worker the limit and ask for a partial result near it | Experimental |
| `run.stall_minutes` (0) | stop an attempt that printed no event for this long, marked `stalled` | Experimental |
| `run.max_usd` (0) | default `--max-usd`; 0 = no limit | Shipped |
| `sessions.archive` (`after_run`), `sessions.auto_archive_hours` (2) | when finished sub-sessions are archived (`after_run`, `hours`, `off`); env `CCX_NO_AUTO_ARCHIVE=1`, `CCX_NO_START_ARCHIVE=1` | Shipped |
| `worktree.location` (`sibling`), `worktree.fetch` (`true`), `worktree.fetch_timeout` (15), `worktree.base` (`head`) | where a worktree goes and what it starts from | Shipped |
| `lanes.default` (0), `lanes.max_tokens` (200000), `lanes.max_blocks` (5) | warm lanes for `batch` and `q run` | Measured, not recommended as a default (cost 40% below ten fresh runs, 4–5× one combined run; [report](research/2026-10-25-warm-lanes.md)) |
| `wake.enabled` (`true`), `wake.trust_socket` (`true`) | a `--bg` run tells the lead one line when it ends | Shipped |
| `output.lead` (`line`) | what the lead gets back: one JSON line or the full result | Shipped |
| `hooks.timeout_s` (2.0) | seconds a session hook may run | Shipped |

### Prompt, context and memory

| Key (default) | What it does | Label |
|---|---|---|
| `prompt.slim` (`true`) | leave out the answer-only sentence for `--mode write` runs without `--check` | Experimental (not tested on a real sub-agent) |
| `brief.slim` (`false`) | slim first message, rest in `guidance.md` ([features](features.md#experimental-slim-sub-agent-brief-brief-slim-off-effect-unknown-to-be-evaluated)) | Experimental (Unknown) |
| `delegate.user_words` (`false`), `delegate.user_words_max_chars` (8000) | attach the lead's latest real user message ([user words](user-words.md)) | Experimental |
| `shared_context.run` (`auto`), `.max_chars` (5000), `.turn` (`true`) | attach recent conversation context ([shared context](shared-context.md)) | Shipped (file only) |
| `shared_context.dedupe` (`false`) | drop repeated sentences in "settled" | Experimental (waits for M5) |
| `memory.by_kind` (`false`), `memory.start_scene` (`false`) | what a session start and a brief carry | Experimental (the H11 trial was voided; waits for a confirmation run) |
| `memory.suggest_expire_days` (14) | days before an unhandled suggestion expires; 0 = never | Shipped |
| `merge.*` (file only: `default`, `max_pieces`, `piece_minutes`, `total_minutes`) | `ccx batch --merge` settings | Experimental |

### Quota, billing, reports

| Key (default) | What it does | Label |
|---|---|---|
| `quota.routing` (`on`), `quota.avoid_above` (0.8), `quota.auto_refresh_min` (60), `quota.probe_timeout` (15) | prefer subscriptions with room; env `CCX_NO_QUOTA_PROBE=1` | Shipped |
| `billing.mode` (`api`) | `subscription` shows quota units first; routing and USD caps unchanged | Shipped |
| `report.publish_dir` (empty) | local clone of your private repository for `ccx report --publish` | Shipped |
| `ui.lang` (unset) | `zh` or `en` for `ccx ui` and the lines ccx writes into conversations | Shipped |
| env `CCX_NO_BENCH_REFRESH=1` | no weekly public-benchmark refresh at start-up | Shipped |

### Board, projects, autonomy

| Key (default) | What it does | Label |
|---|---|---|
| `board.github` (empty), `board.max_machine_turns` (6) | private-repository fallback between computers; machine messages in a row | Shipped |
| `intake.github`, `intake.label` | private repository and label for `ccx intake` | Shipped |
| `projects.roots` (empty) | where `ccx projects scan` looks | Shipped |
| `autonomy.level` (`L1`) | L0 advise only, L1 read-only alone, L2 may merge small branches (file: `max_lines` 80, `max_files` 5, `protected`) | Shipped |
| `relay.enabled` (`false`) | quota capture and explicit continuation | Experimental |
| env `CCX_HUB`, `CCX_CONFIG` | use another hub, or another personal config file | Shipped |

### Sub-agent switches (file only; none has a per-run flag)

| Key (default) | What it does | Label |
|---|---|---|
| `[subagent] codex_memories` (`true`) | `false`: Codex without memories | Measured, not recommended (**Unknown**: right 29/29 each side) |
| `[subagent] clean` (`false`) | `true`: clean HOME, no user skills or settings | Measured, not recommended (**Fail**: 27/30 vs 30/30) |
| `[subagent] codex_lean_tools` (`false`) | `true`: write runs without web search, image generation, goals | Measured, not recommended (**Fail** under the registered rule: 29/30 vs 30/30) |
| `[subagents] fork_turns` (`all`) | `none`: Codex children do not take the parent history | Experimental (waits for M3) |
| `[claude_subagent]` `tools_write`, `tools_read`, `exclude_dynamic`, `mcp`, `skills` | what a Claude sub-agent loads at start-up | Shipped (start-up cost measured 2026-10-23) |
| `[cold_start]`, `[lead_by_task]`, `[policy.*]` | tables for the keys above | as their keys |
| `[tiers.T0..T4]`, `[permissions.*]`, `[providers.*]`, `[pay_per_token.dsh]`, `[roles]` | models and efforts per tier, tool permissions, other model APIs (each pay-per-token one has a `daily_usd` cap), role table | Shipped; the Gemini CLI adapter is Experimental (not run for real) |

Source of the three measured switches: [report](research/2026-10-31-b3-lean-switches.md).

## One-off options worth knowing

| Option | What it does | Label |
|---|---|---|
| `ccx doctor --backfill-kinds` | put old learned outcomes under their kind of work (adds only; runs once) | Shipped |
| `ccx verify --sweep` | record "probably right" for finished runs whose checks and review passed; also runs quietly at session start | Shipped |

## Check that nothing was removed

Compare the command and option lists of the old and new tree: `python ccx.py -h --all` for the commands, and for each
command `python ccx.py <command> -h`. This page changes no code, so both lists are identical to the ones before it.
