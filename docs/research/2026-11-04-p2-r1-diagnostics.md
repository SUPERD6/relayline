# Phase 2 round one: diagnosis and repair

English · [中文](2026-11-04-p2-r1-diagnostics.zh.md)

2026-11-04. Historical replay at `dec375eeb4bb0c375d9085f9f2498daed1baab32`.
This task inspected existing evidence and ran fake-CLI checks only. No paid CLI,
benchmark rerun, commit or default/gate change was made.

## Evidence and classification

The main checkout's `.ccx/eval/p2-review-replay.jsonl` contains 29 rows: **4 pass,
25 Unknown, 0 issues**. Its SHA256 is
`e6427d6267e40c0bd40fac8cc1903b8b716e1a275d2d68af8122f1ad60abe688`.
Only that file and `.ccx/eval/p2-r1-evidence/` supplied evaluation evidence.
Within the latter, each `p2-N` contains the job, reviewer run prompts/records/events
under `hub/ccx/runs/`, and controller execution counts. No hidden-test sources,
exercise clones or other evaluation directories were read. No benchmark tests or
task-specific examples were added to prompts or regression code.

| Exclusive primary category | Units | Unit indices |
|---|---:|---|
| Manifest written inside checks/, but controller reads only root | 17 | 0, 1, 4, 6, 13–17, 19–21, 24–26, 28, 29 |
| All collected tests pass, but duplicate file entries cause Unknown | 3 | 11, 12, 27 |
| Quote remains outside the task after normalization | 1 | 10 |
| Failing tests do not produce a confirmed implementation issue | 4 | 5, 8, 9, 22 |
| Normal pass | 4 | 3, 7, 18, 23 |

Overlapping detail:

- **0/29** reviewers failed to write tests: 29 generation calls wrote 30 test files.
  Historical `tests_written=0` means no collected test cases, not no files written.
- 12 root manifests and 17 checks-local manifests were written. The latter are a
  discovery/prompt-contract defect, not a write-permission failure.
- The 14 historical filename/quote rejections across six units are 13 duplicate-file
  entries (8, 11, 12, 22, 27) and one non-task quote (10), with no invalid filenames.
  All manifests together contain 18 duplicate entries across nine units; five were
  inside unread checks-local manifests.
- Across 48 manifest entries, 45 quotes match exactly, two differ only in Markdown
  punctuation/whitespace (15, 29), and one is not task text (10). Duplicate quotes
  themselves are exact task text. The formatting cases overlap the missing manifests.
- All **33 prompts** (29 generation, four confirmation) contain the complete job task.
  However, all 29 `job.user_task` values are empty: pinned reconstructed `task_text`
  was passed, not recovered historical user wording.
- All 29 generation calls successfully wrote files but encountered 70 Bash approval
  refusals, including Python test attempts. Controller execution is separate and worked.
- The controller executed 125 tests across 11 units, with six failures in units 5, 8,
  9 and 22. Unit 10 had a manifest but no accepted test execution.

## Confirmation, actual models and cost

| Unit | Confirmation run | Result |
|---|---|---|
| 5 | `20261104-151218-1e89` | Native budget error; $0.0654567; no usable structured result |
| 8 | `20261104-151336-e51c` | Reviewer explicitly identifies a wrong test expectation |
| 9 | `20261104-151407-521f` | Native budget error; $0.0504009; no usable structured result |
| 22 | `20261104-151924-9c11` | Reviewer explicitly identifies a wrong test expectation |

Native `modelUsage` reports `claude-haiku-5-5` for all 29 generation calls, but
`claude-sonnet-5-5` for all four confirmation calls, despite recorded Haiku requests.
Those confirmations used replay's `--permission-mode plan`. This establishes model
drift associated with plan mode, not a measured causal explanation. Replay now uses
the project's existing `dontAsk` read-only mode with Read/Grep/Glob allowed. Fake CLIs
verify the new wiring; real runtime model fidelity remains unverified.

The generic Finish instruction also contradicted controller-owned execution by asking
the reviewer to run tests. The new Finish assigns execution to the controller. It does
not broaden shell permissions. Budget failures now retain their specific errors rather
than only a generic unconfirmed-failure reason.

| Historical native cost | Total | Mean |
|---|---:|---:|
| 29 Haiku generation calls | $0.13104282 | $0.004519 |
| Four actual Sonnet confirmations | $0.18666530 | $0.046666 |
| 29 complete units | **$0.31770812** | **$0.010955** |

Existing row `usd` totals $0.140696: it is the configured API-equivalent estimate
using the requested model, not the native total. Its meaning remains unchanged;
new `native_usd` records CLI-reported cost, or null if any call lacks that cost.
Native CLI limits can overshoot at stopping, as the historical $0.05 calls demonstrate.

## Repairs and limits

- Prefer root manifests; fall back to checks-local manifests only when root is absent.
  Preserve manifests and detailed diagnostics; malformed root cannot be hidden by fallback.
- Validate every task quote, then execute each file once. A file may carry multiple
  valid quotes; an invalid duplicate quote still prevents pass. Confirmation can use any
  of that file's validated quotes.
- Collapse whitespace and remove punctuation/Markdown backticks before substring checks.
  Paraphrases, changed words/numbers, and punctuation-only quotes remain rejected.
- Use an execution-free Finish; retain confirmation errors, requested call settings and
  native costs. Malformed confirmation objects stay Unknown rather than raising.
- Add empty-default `review.tests_model` and `review.tests_effort`, affecting test review
  only, with the candidate's vendor retained. Add replay `--reviewer-model` and
  `--reviewer-effort`; record requested overrides and effective cap in every output row.
- Preserve numeric `--unit-cap 0.10`; accept repeated `--unit-cap MODEL=USD` with a
  pinned `--reviewer-model`. Reserve the selected cap before launch and retain all 29
  rows, budget exclusions and Unknowns. `by`/`reviewer_calls` identify selected requests.

The harness defects dominate this result. The non-task quote and the two confirmed
wrong test expectations are model-output problems and stay Unknown. Test correctness
for units 5 and 9 and all previously unexecuted suites is still unknown. The evidence
cannot isolate model ability or establish that a stronger model catches more defects.
Default read review, cross-vendor independence, task grounding, failure confirmation,
existing commands/options/exit codes and efficacy thresholds are preserved.

## Round-two recommendation

First pin **haiku / low** to distinguish harness repair from model changes. Use
`--reviewer-model haiku --reviewer-effort low --unit-cap haiku=0.15 --budget 4.35`.
The $0.15 unit reservation splits into $0.075 per call. Record the change from the
historical $0.10 cap in the next preregistration, retain separate output, and pin the
final committed code before any paid run. This is a budget change, not a gate change.

Use the historical **about $0.011/unit** as a provisional central estimate, with a
**$0.15/unit reservation**, not a price guarantee. Confirmation frequency, token usage
and actual runtime model can change. Historical native spend plus all 29 new
reservations is about **$4.667708**, within the stated $5 stage allowance; the lead
must still account for the overall $60 budget and other spending. Switching to Sonnet
medium in the same round would confound model and harness effects, so defer that
comparison. The new options support it without claiming it is better or cheaper.
These 29 tasks have now been inspected for development and cannot count as unseen.

## Verification

`python -m pytest -q tests/test_review_tests.py tests/test_review_tests_diagnostics.py`:
**55 passed, 3 subtests passed**, exit 0. Includes existing read-prompt preservation,
task/resume transport, source isolation, environment/timeout counts and budget-denominator
checks, plus all repair regressions. Full local output is retained at
`.ccx/eval/p2-r1-diagnostics/related-tests.txt`. `git diff --check`: exit 0.
Evidence level: engineering check. Real model behavior, next-round cost, efficacy and
remote CI are not verified.
