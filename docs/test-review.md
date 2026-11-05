# Task-derived test review (experimental)

English · [中文](test-review.zh.md)

`ccx config set review.mode tests` opts into independent task-derived tests. The default
`read` keeps the existing read-review prompt and trigger rules. Legacy configuration values
`auto`, `on`, `off` remain accepted with their original meaning; `--review auto/on/off`
still controls when review runs. No commands, options or existing exit codes are removed.

The reviewer is selected by the existing cross-vendor selection logic. A same-vendor
candidate is explicitly marked `independent=false` and Unknown, without running it.
`review.tests_model` and `review.tests_effort` optionally override the selected candidate
for test review only; both default to empty (keep the existing candidate). Use a model
supported by that candidate's vendor. These keys do not enable test review or change read review.
`tests_model` also accepts `vendor:model[:effort]`, for example `claude:sonnet:medium`
or `codex:gpt-6.1-sol:medium`. A vendor pin still has to differ from the implementer's
vendor; it cannot bypass independence. An explicit `tests_effort` takes precedence.
Test review supplies the saved `user-words.md` block first, if present, followed by
the assigned `user_task` (or original brief fallback, including on a fix round).
Each has a separate source label; equal content is retained twice, without merging
or deduplication. The original-wording source and retained character count are labelled,
and its existing truncation notice is preserved. No extra task cap is introduced.
Both generation and failure confirmation use these sources, reusing the saved capture
on resume without rereading the external original-wording file. Quotes must match
within either source separately; labels and capture notices are not task requirements.
Shared context and the implementer's test results are not an oracle.
`ccx run --user-task-file original.txt` supplies UTF-8 original wording separately from
the worker brief. Otherwise the run entry captures the supplied task before role/project
wrapping. Test-mode runs save it as `run.json.user_task`; fix rounds and resumes retain it.
`ccx resume --user-task-file original.txt` can explicitly replace the saved task.
Programmatic callers pass `Request.user_task`; replay carries the receipt's original
through its clean-room job and Request instead of relying on the worker brief.

The reviewer gets a temporary source copy without Git history, `.ccx`, instructions or
the implementer's test files. It writes Python `unittest` files in `checks/` and a
root-level `manifest.json` containing filenames and task quotes. The legacy ambiguous
`checks/manifest.json` location is accepted only when the root manifest is absent.
Quotes must be task substrings after collapsing whitespace and removing punctuation
(including Markdown backticks); paraphrases, changed words/numbers and punctuation-only
quotes are rejected. Every quote is validated, including repeated entries for a file;
Rendered Markdown link labels may omit their URL destinations; the words still must
match the task, and paraphrases remain invalid.
each file runs once and may carry several valid quotes. ccx executes these tests
in a separate Python process. Assertion failures and exceptions raised inside test methods
are checked by the reviewer against the task and for errors in the test itself. Only
confirmed in-scope implementation failures produce issues and the existing fix/block path. Missing tests, collection/import
errors, skips, timeouts, unavailable reviewers and unconfirmed failures are Unknown.
Passing generated tests only establish those checks; they do not prove task correctness.
This first implementation supports Python unittest; other test environments are Unknown.

Test source and actual output are retained under the run's `review-tests/`, outside the
implementation's diff. The ledger does not contain test source. `run.json` adds
`review_test_mode="tests"`; `review` adds `review_mode`, `tests_written` (collected test
cases), `tests_run` (executed cases excluding skips), `tests_failed` (assertion failures and runtime exceptions),
`unknown_reasons`, `independent`, and evidence file/output paths. The **existing top-level
`review_mode` remains the auto/on/off trigger**, used by resume. Unknown is a new review
verdict with a `needs_lead` cue, not pass and not an additional blocking exit code.
Counts are `null` if execution timed out or the machine-readable result was lost.
Generated code is executed with the current user's Python permissions, as existing
acceptance commands are; the source copy is an evidence boundary, not an OS sandbox.
Its subprocess receives only the runtime environment allowlist (PATH, Windows system
and command lookup variables, temporary-directory and locale/timezone variables), plus
`PYTHONDONTWRITEBYTECODE=1`; parent API keys, tokens and arbitrary variables are not inherited.
The reviewer is told not to run tests itself: the controller owns execution. Evidence
also retains the manifest, rejection diagnostics, and confirmation-call errors. Additive
`reviewer_calls` records requested model/effort, permission mode, run ID and outcome;
`native_usd` sums CLI-reported costs, or is null when any call's cost is unavailable.
The existing `usd` field remains the configured API-equivalent estimate; it may differ
from native cost when the CLI actually uses a different model.

Test review now supplies the pre-change Python interface from the run's undo snapshot
(replay explicitly uses its committed original stubs). Signatures, annotations, bases,
decorators, literal defaults and docstrings are preserved, without function bodies or
tests. Changed files come first within a 24,000-character budget. Missing snapshots,
unparseable files and omitted interfaces are explicitly Unknown; current implementation
choices are not a substitute for a specification. No missing return contract is invented.
Before reading implementation code, the reviewer is asked to write `behaviors.json`
listing task quotes, interface assumptions, expected types/shapes/units, planned tests
and uncovered/Unknown requirements. `review-tests/interface.md` and any generated
`behaviors.json` are saved, with additive `interface_path` and `behaviors_path` fields.
The checklist is supporting evidence, not a new correctness score or pass criterion.

## pg3b replay

First check the saved material without calling model CLIs:

```console
python scripts/eval/p2_review_replay.py --dry-run --budget 3 --exercise-source /path/to/exercism-clone
```

Defaults are `.ccx/eval/r5/pg3b-results.jsonl` and `pg3b-results-artifacts/`.
The audit requires each selected row's last receipt kind, recorded implementer,
hidden outcome, full final diff, hidden pytest output, pinned original stubs and task
instructions. It reports every missing item and cannot infer a vendor from the lead.
It does not download a benchmark. Linked worktrees use the main checkout's saved data
when their own ignored result file is absent. For the documented 30-row pg3b dataset,
the public report establishes 29 self-checked receipts and one failed review. The row's
ccx telemetry identifies that exception: pg-bowling's final builder has an unresolved
issues review. Cohort membership is reconstructed from these two sources and recorded
as inferred (`receipt_basis`); the missing literal receipt bytes are not claimed recovered.
If no unique final failed review can be identified, missing receipt kinds stay Unknown.
A cohort other than 29 prevents paid replay rather than silently changing it.

The 2026-11-04 offline audit found 30 result rows and artifact directories. The selected
29 have all final diffs and hidden outputs, 14 hidden passes and 15 failures, and recorded
Codex implementers. 28 diffs contain cache blocks; replay filters those and builder tests
before applying solution hunks. No source clone was found at the named local cache
locations: dry-run reports 29 units, 0 ready, maximum reserved estimate $2.90.
Task instructions and original stubs still require a local pinned clone.
With the subsequently supplied `polyglot-benchmark.git` cache, the same audit resolves
the full pin `7e0611e77b54e2dea774cdc0aa00cf9f7ed6144f` and reports 29/29 ready, still
without model calls. A sandbox account may need a temporary, path-specific Git
`safe.directory` setting to read a clone owned by the lead account; no global setting is changed.
Supply `--exercise-source CLONE` or r5-compatible `--ext-cache DIR` (with `polyglot`
or `polyglot.git` beneath it; `polyglot-benchmark` and `polyglot-benchmark.git` are also accepted).
Missing material prints one `git clone --bare` command
for the lead to run; the script does not run it. These audit steps made no model calls;
the subsequent first replay is diagnosed below.

Paid execution requires `--run --pin-commit SHA --budget USD`; `--wait-quiet MINUTES`
uses r5's quiet-machine wait. Each unit reserves `--unit-cap` (default $0.10), including
lost responses, before starting. Each of its at most two Claude calls receives half
that amount through native `--max-budget-usd`; a CLI without native USD enforcement
is Unknown. This bounds launch reservations and sets the provider's native limit;
it cannot promise a stricter billing limit than the CLI itself enforces. Prices are API
equivalent, not subscription bills. Runtime budget/isolation behaviour of the repaired
configuration has not been measured.

Pin test reviewers with `--reviewer-model sonnet --reviewer-effort medium`. Both default
to empty. Keep numeric `--unit-cap 0.10`, or repeat model overrides, for example
`--unit-cap 0.10 --unit-cap sonnet=0.40`. Model-specific caps require `--reviewer-model`
so the reservation cannot silently use the wrong model's allowance. Each output row,
including a skipped or Unknown unit, records the requested overrides and effective unit cap;
`by` and `reviewer_calls` record the selected reviewer when it runs.
`--review-model` is an alias, accepting qualified pins too. For example, dry-run with
`--review-model claude:sonnet --unit-cap claude:sonnet=0.40` reserves at most $11.60
for 29 units. This is a chosen admission reservation, not a measured expected bill.
`--review-model codex:gpt-6.1-sol` parses and selects Codex, but the paid replay remains
Unknown without launching it: these receipts have Codex implementers (same vendor),
and this replay has no native Codex USD budget enforcement. Product test review can
use Codex on Claude work; only fake-CLI wiring has been checked here.
Replay confirmation uses `dontAsk` with Read/Grep/Glob rather than `plan`: round-one
native telemetry showed Sonnet execution despite a Haiku request in all four plan-mode
confirmation calls. The new flags are fake-CLI checked; runtime model fidelity still
requires a separately authorized round. See the [first-round diagnosis](research/2026-11-04-p2-r1-diagnostics.md).

Each replay tree is built from original solution stubs and **only solution-file diff
hunks**; neither builder tests nor hidden tests/output enter the reviewer job or tree.
Full source rows are retained in output JSONL, along with all failures and Unknowns.
An existing output is refused to preserve earlier evidence and prevent budget resets.
Evidence directories are retained for inspection. Catch rate is blocked wrong / all
wrong; false-block rate is blocked correct / all correct. Both print numerator and
denominator, Unknown separately, and worst-case rates (Unknown misses every wrong case
and blocks every correct case). Zero denominators remain Unknown.

r5 adds opt-in `--arms ccx2rt`: the same lead and prompt as `ccx2`, with the unit hub's
`review.mode="tests"` written and read back before launch. It is not a default arm.
The historical first replay produced four pass and 25 Unknown outcomes, with no issues;
see the diagnosis above. The repaired version has only fake-CLI engineering checks,
and the pg3b efficacy gate remains Unknown.

The historical second replay at `b7f9463` found 0 confirmed catches, 8 wrong passes,
7 wrong Unknowns, 9 correct passes and 5 correct Unknowns. The gate failed even under
the optimistic 7/15 catch interpretation. The [R2 diagnosis](research/2026-11-05-p2-r2-diagnostics.md)
inspects all misses/Unknowns; current changes are engineering checks only. The task set,
scores, thresholds (catch ≥50%, false block ≤20%), default `read` mode and existing
verdict/exit rules are unchanged. Two failed rounds do not authorize another paid run.
