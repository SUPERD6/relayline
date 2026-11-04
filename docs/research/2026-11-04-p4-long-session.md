# P4: large tasks in a growing lead conversation (experimental)

[中文](2026-11-04-p4-long-session.zh.md)

Evidence: **engineering check** for the harness and offline task checks. Paid model evaluation: **not run**.
Cost, correctness and wall-clock decision: **Unknown**. No shipped product default, product JSON field,
command, option, exit code or verdict has changed. `r5.py` is unchanged.

## Budget and explicit execution

The lead's follow-up decision enables `--run` with an **explicit `--budget`**. Without an action flag, or with
`--dry-run`, the CLI only prints a plan; `--run` without an explicit budget refuses before any model call. Every resumed Claude
invocation gets `--max-budget-usd L` (default **$1.50**); delegation gets `--max-usd C` (default **$1.50**).
Before a task starts, known spend `S + L + C` must fit `--budget B` (`C=0` for self). Otherwise record the
not-started task and stop. Missing accounting also stops. Repairs share the remaining task child allowance:
the receipt wrapper clamps each resume/run cap after accounting for all child/review/fix spend in that task.

Summary and the plan report an operational overrun allowance **L+C=$3** and envelope **B+L+C**: with `--budget 12`,
**$15**; with `--budget 15`, **$18**. This is the agreed one-final-overrun-per-role allowance, **not an absolute
provider billing hard cap**. The CLI caps are checked at request/step boundaries (ccx: `ccx/delegate.py::_capped`);
an in-flight call can exceed its allowance. All observed overspend remains charged and stops further scheduling.
The envelope must not be reported as a guaranteed worst-case invoice. The original supplier-hard-cap blocker
is superseded by this explicit operational policy; no real models were invoked to implement it.

The lead must also commit a preregistration with the final code pin before paid execution. This uncommitted
implementation/report does not meet that prerequisite by itself.

## Fixed design

An episode is four tasks from one repository in one Claude conversation per arm. Both arms use Sonnet/medium;
each episode/arm gets a fresh UUID, workspace, hub and isolated Claude config directory. First call uses
`--session-id UUID`, later calls `--resume UUID`; there is no `--no-session-persistence`. Checked locally with
**Claude Code 2.1.316 `--help`, 2026-11-04**. Real resumed CLI execution and cost-counter scope remain unverified.

Both arms see the same task order. Calls alternate between arms, with first position alternating by task/episode;
only one lead process runs at a time. `self` implements/checks itself, with no Agent tool. `ccxlong` must delegate
to Codex with the shipped default tradeoff (no explicit `--tradeoff`), review and routing. Both use the same
ordinary existing tests; final scoring uses the reference commit's test files and is never passed to the lead,
`ccx verify`, shared memory or the live repository.

The existing `ccx/leadview.py` emits a one-line receipt only for clean results; attention-worthy successes can
expand into full output. The P4-only `p4_receipt.py` wrapper reuses `leadview.line`, captures that output, and
ensures successful receipts expose one compact line without diff/full review prose. Unsuccessful receipts can
show details and request repair. The prompt prohibits reading code/diff or rerunning checks after `ok=true`.
Real protocol adherence is not proven by this prompt or by fake CLI tests.

Before every task, rebuild the **same workspace path** from that task's reference parent in a fresh one-commit
repository, without upstream remotes/history. Keep the conversation and hub. This removes dependencies between
historical tasks, while retaining their conversation history. It measures accumulated conversational context,
not cumulative software development: earlier implementation changes disappear. The inverse `first_true` tasks
are deliberately retained under this reset rule; their conversational carry-over can make later work easier.

The engine reuses `preflight` isolation/audit/process cleanup/watch/fingerprint, r5 wait-quiet and artifact naming,
and `evidence_streams` redaction. Codex uses workspace-private temporary directories. Hidden scoring runs in a
separate throwaway tree. Grade/diff/streams go outside the agent workspace and are denied to agents. Rows record
per-task and cumulative episode dollars/wall time, review cost, raw lead cost, request context lengths, context
growth, cache reads, audit and `env_clean`. Missing accounting is Unknown and stops scheduling. Interrupted
attempts and already observed spend are retained. Session cleanup conservatively applies to all its rows.

## Revised frozen task selection and offline results

Selection is fixed before any model results: repository priority **more-itertools, boltons, pluggy, humanize, itsdangerous**; within each,
single-parent commits by commit timestamp descending, full SHA ascending to break ties. A candidate must change
test Python files and implementation Python, with **at least 60 changed implementation `.py` lines OR 3 implementation `.py` files**.
Tests/test/testing, test support files, docs/doc and `.pyi` stubs do not count. Exclude holdout commits (including
the recorded dropped holdout candidates conservatively). Scan **all locally available history, with no date cutoff**;
no network fetch. Keep the first candidates whose reference test files
fail on the parent and pass on the reference, with no model-based selection. Form full same-repository groups of
four in that order. The twelve scheduled tasks use more-itertools (MIT, development four) and boltons (BSD-3-Clause,
final eight), do not reuse `tasks_holdout.py` commits, and make three same-repository episodes. First four
are development; final eight are not to be used for tuning.

The old documentation/type-stub rule is **void** because it admitted small code changes. The manifest records
that reason, the new rule, code sizes, candidate counts and all 53 checked outcomes. The full metadata scan finds
44/61/32/19/7 eligible candidates in the five repositories respectively. Stop dynamic checks after obtaining the
first three complete episodes: 53 tested, 15 parent-fail/reference-pass, 12 scheduled. Three older qualified
more-itertools candidates do not form a complete fourth-task group and remain recorded, unscheduled. No threshold
was lowered or model result consulted. The 41-line GC/type/trace task qualifies through **three actual code files**.

Offline runtime: supplied external Python **3.11.9**, pytest **9.1.1**, plugin autoload disabled, no package
installation, no model invocation. Run whole changed test files, with no deselection or edited assertions.
Reference test files are overlaid on the parent; reference itself must pass. Full SHAs/test paths and results
are in the selection manifest and [full captured validation output](data/2026-11-04-p4-validation.json).
The latter includes all scheduled parents' and references' untruncated stdout+stderr, with tree/private paths and
addresses normalized and SHA256 recorded. Excluded-candidate streams are retained locally at the manifest's
`raw_directory`; the separate frozen-list recheck also passed all twelve.

| Set | Task | SHA prefix | Code lines/files | Parent exit | Reference exit |
|---|---|---|---:|---:|---:|
| dev | running statistics | 18c57c72 | 179 / 2 | 1 | 0 |
| dev | multidimensional reshape | 21d3d883 | 68 / 1 | 1 | 0 |
| dev | windowed median | 5c8336c5 | 106 / 1 | 1 | 0 |
| dev | is_prime | a7236314 | 69 / 1 | 1 | 0 |
| final | iterutils fixes/filter | 6270b5e3 | 73 / 1 | 1 | 0 |
| final | file/path/names | 922e7b2b | 66 / 3 | 1 | 0 |
| final | GC/types/tracing | f898d8f8 | 41 / 3 | 1 | 0 |
| final | indexed/complement sets | 40fffc5b | 62 / 1 | 1 | 0 |
| final | mapping updates | bbadc7ae | 62 / 2 | 1 | 0 |
| final | BarrelList compatibility | 3fe7b949 | 128 / 1 | 1 | 0 |
| final | ellipsize | 673e010d | 64 / 1 | 1 | 0 |
| final | US timezone fold | 99dec84c | 67 / 1 | 1 | 0 |

## Free commands and estimate

```text
python scripts/eval/p4_long_session.py --dry-run --budget 12 --pin-commit FULL_SHA
python scripts/eval/p4_long_session.py --dry-run --split dev --budget 12
python scripts/eval/p4_long_session.py --summary --out RESULTS.jsonl --tag TAG
python scripts/eval/long_check.py --ext-cache CACHE --ext-python PYTHON --output VALIDATION.json
python scripts/eval/p4_long_session.py --run --budget 12 --pin-commit FULL_SHA --ext-cache CACHE --ext-python PYTHON --codex-home DEDICATED_HOME --wait-quiet 10
```

Without an action flag the CLI only prints a plan. `--dry-run` never invokes preflight canaries or model CLIs.
Only explicit `--run --budget` enables model execution; no paid invocation was made in this delivery. `--wait-quiet`, pin checks, reservations and
fresh-session failure handling are implemented in the engine. Reusing an attempted tag is refused, so a lost
conversation is not silently replaced. A shared results ledger counts earlier tags against its total budget.

The estimate uses historical r5 means already recorded in `r5.py::UNIT_USD`: self **$0.20/task**, ccx2 **$0.12/task**,
times the per-task size factor **max(1, code_lines/40, code_files/2)** and **1.5** for resumed context. The 40-line
reference is the approximate historical r5 task scale; the file factor covers changes spread across modules.
The new set has **985 code lines** across its twelve reference changes. Per-task factors and estimates appear
in dry-run output. For 12 tasks × 2 arms × 1 sweep: self **$7.530**, ccxlong **$4.518**, total **$12.048 API-equivalent
USD**. Dev four: **$5.064**; final eight: **$6.984**. Coefficients remain planning assumptions, not measured P4 growth,
a confidence bound, a spending guarantee or a claimed 0.6 ratio. With `--budget 12`, reservations may stop the run
before all tasks complete; do not silently omit those missing pairs. Two sweeps estimate **$24.096**, outside the $10–15 budget.
One sweep is exploratory only; the engineering standard requires at least two rounds for public claims.

## Decision/reporting rules and limits

Unchanged gates: total ccxlong cost **≤ 0.8 × self**; ccxlong correct count **≥ self**; task wall-clock median
**≤ 2 × self**. Summaries print numerator, denominator and ratio, plus attempted/correct denominators, complete
episode totals and both all-row and `env_clean` populations. Missing/unpaired/incomplete accounting, zero cost or
wall denominator, or scoring environment failures keep the decision Unknown; interrupted pairs cannot yield Pass.

Delegation and one-line acceptance change together: **their effects are not separated**. Other limits: one
development repository and a different final repository (repository effects are confounded with the split), few tasks, historical public commits may
be memorized, context reset differs from daily development, and real CLI compliance/resume cost semantics are not
verified. The budget envelope is operational, not an invoice guarantee. No scientific or product-performance conclusion is made.

The existing `test_source_task_rule_and_split` still asserts the void **80 non-test lines OR 3 non-test files**
rule. It now fails on the valid 68-code-line reshape task. Per the assignment, its setup/assertions were left
untouched; the lead must reconcile that old assertion with the approved 60-code-line rule. New regressions test
the revised filter and budget behavior. No full-suite/CI or real-model result is claimed.
Targeted run: **64 passed, 12 subtests passed, 1 existing old-rule assertion failed (exit 1)**.
The follow-up regression file separately passed all **11** checks.
