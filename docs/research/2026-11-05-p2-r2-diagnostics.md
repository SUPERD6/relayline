# Test-review R2: missed errors and Unknown outcomes

English · [中文](2026-11-05-p2-r2-diagnostics.zh.md)

Historical pin: `b7f9463607f8d9d7ae5a31b4db5d97641ef87576`. The 29 pg3b self-checked
receipts contain 15 wrong and 14 correct implementations. Requested reviewer:
`claude:haiku:low`. This task inspected evidence, repaired code and used fake CLIs and
dry-runs only. No real models, task reruns, score changes or third paid round.

## Result and evidence

Confirmed catches remain **0/15**: eight wrong passes and seven wrong Unknowns.
Even treating all seven Unknowns as catches gives **7/15 = 46.7%**, below the unchanged
≥50% gate. Correct implementations have nine passes and five Unknowns: false blocks
are 0/9 on resolved cases, 0/14 across all correct cases, or 5/14 = 35.7% if every
Unknown is a false block. A resolved-only denominator cannot replace all attempts.
The historical Fail stands. Test review remains experimental and off by default.

Inspected `.ccx/eval/p2r2-review-replay.jsonl` and the specified
`.ccx/eval/p2-r2-evidence/p2-N/` jobs, implementation files, generated tests, manifests,
controller counts/output, reviewer prompts and run records. JSONL SHA256:
`633bac21c118633d4d468ffc5a0e2e685274e2b46e173507352c27d785d6593e`.
There were 281 collected/executed tests and 12 failures; 29 generation calls and ten
confirmation calls cost $0.116894 in total native-reported USD. All 39 prompts carried
the complete pinned job task. All 29 jobs lacked `user_task`: full transmission does
not recover the historical person's exact wording.

The observations below do not isolate weak-model causality. Hidden test examples,
assertions and benchmark-specific answers were not added to prompts or regressions.

## All eight wrong passes

| Unit / exercise | What generated tests covered | Miss and evidence limits |
|---|---|---|
| 1 / book-store | Ten tests comparing dollar-valued prices | Accepted the implementation's money representation; even single-book hidden checks failed. A unit/interface mismatch is plausible, but machine return units cannot be invented from this evidence |
| 6 / zipper | Ten tests using the implementation's tuple binary trees | Task describes rose trees; reviewer noted missing operations but omitted tests of the mismatch |
| 15 / dot-dsl | Eleven tests checking merely nonempty error messages; no-argument Graph expected to fail | Default construction and message contracts were not independently established; hidden failures include the empty graph and malformed inputs |
| 18 / grep | Twelve tests expecting a list of strings | Accepted the implementation's return container despite testing flags and multiple files |
| 19 / phone-number | Eleven normalization/validation tests on `.number` | Omitted other public operations; hidden failures explicitly name area-code and formatting operations. Reviewer acknowledged inferring the attribute from implementation |
| 22 / paasio | Twelve counters-on-real-stream tests | Followed current construction/wrapping choices, missing existing wrapper, context-manager and partial-IO contracts |
| 23 / beer-song | Nine tests expecting one string per verse in a list | Accepted implementation grouping/container choices; basic hidden verse checks failed. Pinned prose does not fully define Python return shape |
| 27 / react | Eleven tests with scalar/varargs computation lambdas | Callable input convention came from implementation rather than an independently established interface |

Test count alone was not the problem: tests repeatedly adopted implementation choices.
Neither a stronger model nor this new interface summary has measured efficacy here.

## All twelve Unknowns

| Unit / exercise (hidden result) | Observation | Classification and treatment |
|---|---|---|
| 3 / bottle-song (wrong) | Expected-value helper pluralized one bottle; recite interface assumed | Wrong test plus interface gap; rejecting that failure was reasonable, actual bug still missed |
| 5 / two-bucket (correct) | Wrong expected leftover volume | Wrong test; retain Unknown |
| 7 / poker (correct) | Expected K-high ties to beat A-high | Wrong test; confirmation rejection was reasonable |
| 8 / scale-generator (wrong) | Flat test expected a sharp; tests and implementation also shared Unicode note choices | Wrong test plus representation gap; no confirmed implementation failure |
| 9 / dominoes (correct) | Expected a closed circuit despite odd degrees | Wrong test; confirmation rejection was reasonable |
| 10 / hangman (correct) | Quote omitted inline Markdown link URL but retained displayed words | Harness formatting rejection, repaired without allowing paraphrases |
| 11 / simple-linked-list (wrong) | Quote omitted reference-link label; slash removal joined raised/thrown; suite never executed | Harness formatting rejection plus interface coverage gap; repair is not evidence of a newly caught bug |
| 14 / rest-api (wrong) | Test reversed debt direction/balance and followed current return shape | Wrong test plus interface gap; rejecting that failure was reasonable |
| 20 / go-counting (wrong) | Inline-link quote rejected; three other failures came from incorrectly identified territory | Overlapping harness formatting error and wrong tests; only formatting repaired |
| 24 / tree-building (wrong) | Test demanded unspecified input-order children | Wrong expected ordering; actual hidden errors remain unconfirmed |
| 26 / forth (wrong) | Test required old-definition binding during builtin redefinition; confirmation judged it unstated | Scope/semantic ambiguity; retain Unknown and confirmation gate |
| 28 / sgf-parsing (correct) | Test merged two semicolon-separated nodes | Wrong test; confirmation rejection was reasonable |

Nine wrong test expectations, one scope/semantic dispute and three formatting rejections
overlap at unit 20, giving twelve units. R2 provides no evidence of manifest-location or
confirmation-budget failures. Offline matching now accepts the displayed wording in
all three rejected suites. This validates quotation wiring, not a revised historical
score or a predicted number of catches. Missing exact user wording affects all rows;
its independent contribution cannot be estimated from this material.

## Changes and retained boundaries

`ccx/review_contract.py` extracts pre-change Python interfaces from the undo snapshot;
replay explicitly uses its committed pristine stubs. It retains signatures, annotations,
literal defaults, bases, decorators and docstrings, removing function bodies and tests.
Missing/truncated material is Unknown. Existing original-task precedence is unchanged.
Before reading implementation, the reviewer is asked to write `behaviors.json` covering
task quotes, interface assumptions, expected types/shapes/units, planned tests and gaps.
The checklist and interfaces are retained as supporting evidence, not new pass criteria.

Quote normalization accepts inline/reference Markdown link labels without destinations
or reference IDs, and preserves word boundaries across slash alternatives. Changed
words/numbers, paraphrases and meaningless quotes remain invalid. Vendor-qualified
`review.tests_model` and `--review-model` (alias of retained `--reviewer-model`) support
explicit reviewer selection. Empty defaults, read review, cross-vendor independence,
actual execution, failure confirmation, verdicts and exit codes remain unchanged.

An interface summary cannot invent return units/shapes absent from original material,
or recover missing historical user messages. This is an engineering repair, not evidence
of passing efficacy gates. The same tasks and scoring remain development material.

## Dry-run reservations and limits

The actual script was run as a separate process outside the repository with explicit
pg3b result/artifact locations. It recognized 29 units; zero were ready because a readable
original exercise clone was unavailable. It downloaded nothing and called no model.

| Configuration | Admission reservation for 29 units | Expected actual spend and launchability |
|---|---:|---|
| Historical Haiku low | Historical $0.15/unit, $4.35 total | Actual historical native $0.116894, about $0.00403/unit; not a forecast for new prompts |
| `claude:sonnet`, medium, chosen $0.40/unit | $11.60 | New prompt/model spend Unknown; native per-call cap $0.20 is only an illustrative launch setting |
| `codex:gpt-6.1-sol`, chosen $0.20/unit | Arithmetic reservation $5.80 | Will not launch here: Codex also implemented these receipts, and replay lacks native Codex USD limits. Actual cost Unknown |

A reservation is not a quote or a stricter billing guarantee than the CLI provides.
$11.60 exceeds the historical stage's $2–5 allowance; this task adds no spending
authorization. Product test review can use Codex for Claude implementations, tested
through a fake CLI only. Changing same-vendor policy or increasing budget needs a
separate lead decision. Two failed rounds do not authorize a third paid round.

## Verification scope

Targeted existing test/read-review regressions, R1 diagnostics, new synthetic cases and
change-note formatting checks only. Existing test setup/assertions were preserved.
The fake Codex gained test-review responses to check the real CLI wiring for reviewing
Claude work. Final commands/counts are in the sub-task delivery. Full-suite checks,
CI, real-model efficacy and current real-model spend were not verified.
