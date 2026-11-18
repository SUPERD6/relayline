# Tools for strength retests (experimental)

English · [中文](strength-tools.zh.md)

Evidence: **engineering check** for tools; current-version model results: **not run**.
Existing runtime defaults, commands, options, JSON meanings and verdicts are unchanged. Standard library only.

## Plans and budgets

```text
python scripts/eval/strength_retest.py plan context --dry-run --out context-plan.json
python scripts/eval/strength_retest.py plan memory --dry-run --out memory-plan.json
```

Use absolute script paths outside the checkout. Both commands only produce manifests and cannot invoke models.
They include HEAD, dirty-tree state, tasks, arms, repetitions, cost proxy, ceilings and interruption/metric rules.
`--unit-usd` replaces the historical per-unit estimate; an over-ceiling estimate returns 2.
Estimates are not runtime spend guarantees. Before real runs, the lead must preregister thresholds, a clean
independent clone/pin and final-set selection. An explicit serial runner is available below.

```text
python scripts/eval/strength_retest.py execute context --dry-run
python scripts/eval/strength_retest.py execute memory --dry-run
python scripts/eval/strength_retest.py execute context --run --budget 4 --out FRESH_CONTEXT_DIRECTORY --codex-home EVAL_CODEX_HOME
python scripts/eval/strength_retest.py execute memory --run --budget 3 --out FRESH_MEMORY_DIRECTORY --codex-home EVAL_CODEX_HOME
```

`execute` defaults to an offline estimate. Paid execution requires both `--run`
and an explicit finite `--budget`, capped at $4 for context and $3 for memory,
plus a fresh output directory. Dry-run reports the chosen budget separately from
the task ceiling and exits 2 when its estimate exceeds that budget. The frozen
manifest records both the runtime cap and per-call reservation before execution.
It reuses `seven_func`'s ccx command and isolated
hub mechanism, with a fresh repo, client homes and config for every unit. No
client-home discovery or credential copying occurs. Codex units need
`--codex-home EVAL_CODEX_HOME`: a dedicated folder you logged in to yourself once
(`CODEX_HOME=<dir> codex login`), checked as `p4_long_session.py` checks its own
(preflight's `check_codex_home`: absolute, apart from your own homes, a login
present by existence only, no AGENTS.md/rules/plugins). Without it, a run with Codex
units stops before the first unit (a fresh empty home has no login: issue #320).
A home that passes is prepared as p4 prepares its own: a missing `config.toml` is
written (on Windows with the unelevated sandbox) and a synced `plugins/` folder is
removed. Only the path is passed on; every Codex unit uses it as `CODEX_HOME` and
`CODEX_SQLITE_HOME`, so their Codex sessions collect there, not in the unit folder,
and the home keeps them between runs (a later run's check may ask you to clean it).
Supply DeepSeek authentication through the CLI's environment before a real run. Every invocation receives `--budget`
and a serial reservation (`--unit-budget`, default $0.05), with no escalation,
fallback, child agents or review. Provider settings/rates in isolated homes
must be preregistered before treating this as a controlled model comparison.

**What a unit's agents must not open (#454).** Every unit is denied the person's homes, hub and config (the
`p4_long_session.py` list, preflight's `forbidden()`), the checkout the run starts from and its git worktrees, that
checkout's `scripts/eval/` (task generators and hidden tests, e.g. `round2_a/`) and `docs/research/data/` (frozen task
files, e.g. `round2-tasks/`), the `--tasks` file, and every `--hide PATH` (repeatable: e.g. your everyday checkout when
the run uses an independent clone; made absolute against the start folder, de-duplicated, a git checkout brings its
other git worktrees along, a missing path or one holding the Python that runs the units is refused). This is on by
default, also without `--tasks`: before #454 a unit could read all of these. Each path is listed in every spelling
known: as given (a junction or symbolic link kept), resolved, and on Windows its 8.3 short name. **Where the eval
folder goes:** `--out` must lie outside the clone, outside your everyday checkout (any `--hide` path) and outside your
own homes, hub and config, or it is refused; and neither `--out` nor `--claude-home`/`--codex-home` may contain a
content pattern word (below), or it is refused too. Claude units get Read/Edit deny
rules on each (Claude Code 2.1.316 docs: Read rules also apply to Grep and Glob, best effort; Edit rules to every
file-editing tool). Codex units cannot be confined: `workspace-write` limits writes only and `codex exec` (codex-cli
0.164.0 `--help`) has no read deny, so their reads are audited, not blocked. After each unit every tool call in its ccx
logs is audited (`path_audit` in the row). The unit's own folder, its logged-in homes and the interpreter's folders
are masked first, so working on its own files or running Python (or this checkout's `ccx.py`) is never a hit. A hit
is: a forbidden path anywhere in the call, in any spelling preflight's `path_hits` knows (also after an absolute
path's `..` parts are resolved); a path-independent content pattern (`round2_a`, `round2_bc`, `round2-tasks`,
`round2~N`, `l5_memory`, `shared_context_ab`, catching relative reads such as
`cd ../.. && cat scripts/eval/round2_a/x.py`) in the call's navigation fields (a command, a file path, a Grep/Glob
path or pattern; not the body a Write/Edit writes); a `cd`, or a recursive search's (`rg`, `grep -r`,
`Get-ChildItem -Recurse`, ...) relative path, that lands outside the unit's folder, judged from the run's working
folder (run.json's `cwd`: the repo, or the ccx worktree `<unit>/.ccx-worktrees/repo/<run id>`, from which `cd ../../..`
is still inside); or a recursive search or Grep/Glob call on a parent folder of a forbidden path. A `cd` whose target
cannot be resolved (a variable or subshell) and contains `..` is counted as leaving. A hit makes the row invalid
(`--on-invalid continue`) or stops the group (the default). The dry run prints an `isolation` field (with `--tasks`
or `--hide`) with the `--hide` paths, every path the first unit is denied and the content patterns. Limits: a path
mixing 8.3 short and long parts, a search from the file-system root, a `cd` in one tool call followed by relative
reads in later ones (each call is judged from the run's working folder), code written by Write/Edit that reads a
forbidden folder when run (only the command that runs it is checked), and DSH logs in a format preflight's
`tool_inputs` does not parse are not caught; a Codex read is found only afterwards.

Results, hidden-test failures and interruptions are retained in `results.jsonl`;
unknown cost keeps the full reservation and stops the batch, rather than charging
zero. A spent cap, per-call overspend, interruption or a ccx receipt with
`status: "error"` (e.g. `kind: auth`) stops subsequent units; `unified_summary.py`
counts such a row as invalid (Unknown), not as a task failure.
In-flight requests can overshoot token-monitoring caps; this is not a billing
guarantee. Reports retain the planned denominator, attempted count and Unknown
gate. No automatic rework is run; report this separately from historical trials
that allowed one repair. A fresh directory is required to avoid resetting costs.
The current checks use fake CLIs only; real model results and CI are not run.

| Plan | Tasks and repetitions | Arms | Units | Ceiling (API-equivalent USD) |
|---|---|---|---|---|
| context | original 6 favourable + 1 neutral, 3 repetitions, Codex + dsh | off/on | 84 | $4 |
| memory | original 3 conventions + dates, paths, JSON from L5; 3 repetitions, Codex | nomem/mem/hubmem/hubstart | 72 | $3 |

Sources: [original context design](2026-10-25-shared-context-ab.md), `scripts/eval/seven_ab.py` memory arms
and `scripts/eval/l5_memory.py` cases. All six memory tasks were used before: development/retest, not unseen holdout.
The first three arms form 6 × 3 × 3 = 54 units; hubstart adds 18 units separately, not a new primary comparison.

```text
python scripts/eval/strength_retest.py probe-hook --hub SYNTHETIC_HUB --cwd SCRATCH_PROJECT --as codex
```

This separately launches the actual startup command `ccx mem delta --as codex --peek` with isolated config and
no quota probe. Supply a synthetic hub only: the CLI may initialize state there. No model invocation, hook
installation or client-home access. It checks payload delivery, not task correctness or native desktop
SessionStart execution (still **Unknown**). The `execute memory` hubstart arm feeds
this exact payload into the delegated task; mem uses a project-context file,
hubmem uses the shared journal, and nomem has distractors only. All four arms
share identical distractors. Native desktop hook execution remains Unknown.

## Cross-vendor ledger reconciliation

```text
python scripts/eval/ledger_reconcile.py --run run-a.json --run run-b.json --ledger ledger.jsonl --cli-reports observed.jsonl --out reconciliation.json
```

Only named files are read. Normalized CLI observations have `run_id`, zero-based `attempt`, `vendor`, `model`,
`usage` (fresh `input_tokens`, `cache_write_tokens`, `cached_input_tokens`, `output_tokens`) and optional `cost_usd`.
Missing evidence stays Unknown. Duplicate rows/observations fail rather than silently overwriting each other.
Every attempt uses its own agent/model, never `record.to` to infer a fallback vendor. Optional `--providers`
accepts an archived, secret-free JSON providers table; custom provider provenance missing from it stays Unknown.
Actual native identity is shown separately; Claude aliases versus native model IDs may remain Unknown.

Alternatively replace `--cli-reports` with `--streams stream-manifest.json`:

```json
[{"run_id":"example","attempt":0,"cli":"codex","path":"events.0.log","usage_scope":"attempt"}]
```

Paths are relative to the manifest. The offline event reader supports Codex, Claude and dsh without production
adapter parsers. Set `usage_scope: attempt` only for isolated attempt totals; Codex resume may report cumulative
usage, otherwise usage remains Unknown. No automatic home/session discovery. Claude modelUsage supplies native
model IDs; Codex/dsh often omit them. `observed_vendor` may come from independently archived provenance;
the CLI wrapper alone cannot prove the model vendor. CLI self-reported money is compared only to attempt
`cost_usd`; ledger `ae_usd` and `cost_usd` are each compared to the corresponding attempt sum, following
`ccx/ledger.py`. This is arithmetic/provenance checking, not proof of billing accuracy.
Exit 1 means a definite mismatch, duplicate or orphan observation; exit 0 can still contain Unknowns.

## First model fit board

```text
python scripts/eval/model_fit_board.py --results docs/research/data/2026-10-25-l5-memory.json --out board.json
```

Repeat `--results` for more JSON/JSONL scored files (`rows`/`results` exports supported). Groups are task type ×
model, separately by source, code pin and arm. Built-in types cover these context/memory tasks;
`--task-types types.json` maps other task IDs to types. Missing types stay Unknown.
`--outcome ok|ok_first|ok_final` explicitly selects the hidden-test field; self-report/status is not success.
Groups report n, successes, pass rate, known spend, unknown outcomes/costs and cost per success.
Failures count in both denominator and spend. Unknown outcome makes rate null; unknown cost or no successes
makes cost per success null. Lead/sub/review components must be complete; whole-workflow `usd` must already
include repairs. Fallback models are grouped as a composite, not credited only to the final model.
With any `env_clean=false`, report both all rows and explicitly clean rows with their own denominators.
Every n < 10 group says **样本少**. This is historical description, not a current controlled ranking.
