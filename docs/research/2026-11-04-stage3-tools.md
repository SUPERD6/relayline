# Stage 3 tools: fresh exercises and candidate path

English · [中文](2026-11-04-stage3-tools.zh.md)

Evidence: **engineering check**, 2026-11-04. No real agent CLI, paid canary or model evaluation was run.
The offline grader passes **30/30**: every original stub fails and every official example passes.
The registered experiment remains 30 tasks × one round × two arms = 60 units. Its fixed thresholds remain
candidate right count ≥ self − 1 and candidate cost per success ≤ 1.2 × self. This delivery does not decide them;
the lead must commit the preregistration and code pin before a real run.

## Selection and isolation

Source: [official Exercism Python pin](https://github.com/exercism/python/tree/6105f6d9d3ef66ce3d5c8f529d2882af3d76b706).
The complete rules, ranked eligible pool and exclusions are in
[fresh_selection.json](../../scripts/eval/fresh_selection.json).
Practice exercises only, one implementation file, an example/exemplar and tests, no non-stdlib imports in the
stub/tests/reference (exercise-local modules allowed). Difficulty is the inclusive official rating range of pg1's
30 tasks, **2–9**. This defines “same band”; it does not match pg1's histogram or known model pass rates.
All **34** Python exercises in the pinned aider polyglot tree are excluded, checked against both that tree and
polyglot_selection.json (including its four dropped exercises).

The 74 eligible exercises sort by ascending SHA256 of UTF-8 `slug + "p3-2026-11-04"` (no separator), then slug.
Initial offline validation was **28/30**: `ledger` (11 tests) and `markdown` (17 tests) already had working stubs.
They were rejected solely on that prescribed grading condition; the next two in order, `yacht` and `minesweeper`,
replace them. Both initial and final raw checker output are preserved below. No model outcomes were available.
Reproduction uses `fresh_select.py --exercism-repo <bare-clone> --polyglot-repo <bare-clone>`; its two grading
rejections are fixed and documented, so regeneration keeps the validated set.

Each unit gets only the implementation stub in a new one-commit repository and the instruction texts in its brief.
Hidden tests and example/exemplar contents stay outside the unit. Existing material extraction, clone removal,
cache/web deny rules and fresh scoring directory are reused. Scoring copies only the declared implementation;
an agent's own tests and pytest configuration do not affect it. The selector inspects reference import names
mechanically for dependencies; only the offline checker executes the reference.

## Candidate arm and prompt change

`ccx2cand` is opt-in. It uses ccx2's lead model and CLI flags, and ccx2small's `state=small_self` fallback to doing
the task itself, without retrying `--force`. Its unit hub enables and reads back `delegate.user_words=true`,
`routing.small_self_run=true`, `routing.strict_escalate=true`; it asserts `review.mode=read` before the lead runs.
No configuration key or product default is added or changed.

Existing HOW_CCX2 does **not** supply `--files`. The candidate command guidance therefore adds
`--files <estimated number of implementation files>`. This changes the lead prompt; it is not a settings-only
comparison. All three switches and the prompt addition form one candidate bundle. The old ccx2 and ccx2small
wording stays unchanged.

Each candidate row carries `candidate.switches`, `small_self`, raw small-self decisions, `actual_mode`, every
builder attempt's `actual_tiers` (tier/rung/model/effort), and run-level `user_words` source/count metadata.
The source is read from actual run records, never inferred from the enabled switch. No builder on small-self
means empty tier/source lists; missing evidence means null/Unknown. The lead's model remains in existing fields.
`export` preserves the new candidate object.

`--codex-workspace-tmp` works with `--arms self,ccx2cand`. It changes Codex launch temps only: the self lead keeps
the ordinary unit temp. Fake CLI subprocess tests cover both small-self and actual delegation, automatic Claude
transcript source capture, unchanged self switches, and the wrapper's private temp and cleanup.

## Commands and dry-run

Run these from the checkout (the cache contains `exercism-python.git`):

```text
python scripts/eval/polyglot_check.py --taskset fresh --ext-cache <cache-directory>
python scripts/eval/r5.py run --taskset fresh --arms self,ccx2cand --rounds 1 --arm-order balanced --dry-run
python scripts/eval/r5.py summary --taskset fresh --results <results.jsonl>
```

The requested dry-run, also exercised from outside the checkout, exits 0: **60 units**, 30 per arm, 15 tasks
with self first and 15 with candidate first. Estimated API-equivalent spend is **$9.60**: self **$6.00**,
candidate **$3.60**. Default `--budget 3` is short by **$6.60**; a real run's budget must be preregistered by the lead.
Candidate has no measured price: its `?` estimate reuses historical ccx2 cost, not measured candidate or fresh data.
No actual success cost, wall-clock comparison or efficacy conclusion exists yet.

```text
[estimate] self                    30 units  ~$0.200/unit  ~$6.00 (lead ~$6.00, ccx ~$0.00)  modes self=30
[estimate] ccx2cand                30 units  ~$0.120/unit  ~$3.60 (lead ~$2.30, ccx ~$1.30)  modes ccx2cand?=30
[estimate] total ~$9.60 for 60 units; budget $3.0 with $0.00 of this tag spent leaves $3.00: short by ~$6.60
[estimate] lead prices: sonnet x1.0 of sonnet; token mix assumed (no measured lead token mix in this results file)
[estimate] from measured r5 means with a sonnet lead, split by the measured lead share; another lead model's part repriced at its list prices (PRICES); a ? mode has no measurement and uses ccx2's; tier arms by the mode the shipped tier plans for each task's reference size, so misbanding moves the real cost
```

## Summary and verification

The additive `fresh` summary contains `all` and `clean` scopes, each with per-arm right/started/unknown counts,
all-attempt spend (including failures and interruptions), cost per success, wall median and cumulative wall.
Missing cost or zero successes gives null cost per success. Missing wall has its own count. Median follows the
existing evaluator convention (upper middle). `all` and `clean` never pool their denominators.
Pairs match tag, round, task and lead suffix; the report gives candidate minus self for right count, cost per
success, wall median and total, with scored/unknown/unpaired counts. Unknown pairs are identified and are not
silently scored as wrong. Legacy summary fields keep their meaning; the fresh section is the all-attempt view.

Local tests use local fake upstreams and tests/fakes only. They cover deterministic selection, dependency/shape
filters, exemplar support, no hidden/reference leakage into a unit, all pre-launch assertions, the 60-unit CLI
dry-run, fake subprocess routing/temp/source telemetry and summary cost/pairing/Unknown behavior.
Related legacy evaluator tests also passed. Full repository tests, real CLI behavior, CI, and Windows/Linux/macOS
cross-platform validation are left to the lead. No commit, push, PR, release or product default change was made.

Final targeted run: **110 passed in 36.19s**, process exit 0:

```text
python -X utf8 -m pytest -q tests/test_eval_fresh.py tests/test_eval_polyglot.py tests/test_eval_small.py tests/test_eval_user_words.py tests/test_eval_sandbox_tmp.py tests/test_eval_r5.py
```

The fresh-only file contributes 15 tests. Selection regeneration from the pinned local clones, invoked from
outside the checkout, is byte-identical: SHA256 `57c65b6eac9b94a33f80621f8458dbd0b4787868c50e08d5dfdb22dad949c718`.
`scripts/collect_changes.py --check` and `git diff --check` also exit 0.

Limits: “fresh” here means excluded from the specified polyglot set, not guaranteed absent from training data or
every historical local experiment. Exercism's rating is a proxy for difficulty. A single run is a signal, not an
external claim. Most single-file tasks may return small-self; the telemetry must establish what really happened.
The candidate combines switches and a prompt change, so this comparison cannot attribute an effect to one switch.

## Final 30 exercises

| # | Slug | Official difficulty | Hidden tests |
|---|---|---|---|
| 1 | pythagorean-triplet | 3 | 7 |
| 2 | circular-buffer | 3 | 14 |
| 3 | simple-cipher | 3 | 12 |
| 4 | prime-factors | 2 | 12 |
| 5 | rational-numbers | 5 | 43 |
| 6 | high-scores | 3 | 12 |
| 7 | meetup | 4 | 103 |
| 8 | queen-attack | 2 | 14 |
| 9 | matrix | 3 | 8 |
| 10 | trinary | 4 | 7 |
| 11 | allergies | 3 | 50 |
| 12 | say | 2 | 20 |
| 13 | kindergarten-garden | 3 | 19 |
| 14 | roman-numerals | 2 | 27 |
| 15 | custom-set | 5 | 40 |
| 16 | matching-brackets | 2 | 20 |
| 17 | rail-fence-cipher | 4 | 6 |
| 18 | sublist | 2 | 22 |
| 19 | state-of-tic-tac-toe | 3 | 29 |
| 20 | game-of-life | 3 | 8 |
| 21 | flower-field | 4 | 16 |
| 22 | nucleotide-count | 2 | 7 |
| 23 | luhn | 2 | 23 |
| 24 | pascals-triangle | 4 | 10 |
| 25 | saddle-points | 3 | 10 |
| 26 | linked-list | 4 | 24 |
| 27 | hexadecimal | 3 | 10 |
| 28 | nth-prime | 2 | 6 |
| 29 | yacht | 2 | 29 |
| 30 | minesweeper | 4 | 15 |

## Raw offline grader result

[Initial 28/30 output](data/2026-11-04-fresh-check-initial.txt) · [Final 30/30 output](data/2026-11-04-fresh-check.txt).
Initial process exit 1; final process exit 0. Both graders were invoked as separate processes outside the checkout,
using the supplied pinned local clones; no real agent CLI was called.

```text
ok  fresh-pythagorean-triplet      stub: 7 failed in 0.15s                        example: 7 passed in 0.02s
ok  fresh-circular-buffer          stub: 14 failed in 0.17s                       example: 14 passed in 0.01s
ok  fresh-simple-cipher            stub: 12 failed in 0.16s                       example: 12 passed in 0.01s
ok  fresh-prime-factors            stub: 12 failed in 0.15s                       example: 12 passed in 0.05s
ok  fresh-rational-numbers         stub: 36 failed, 7 passed in 0.26s             example: 43 passed in 0.03s
ok  fresh-high-scores              stub: 12 failed in 0.16s                       example: 12 passed in 0.01s
ok  fresh-meetup                   stub: 103 failed in 0.62s                      example: 103 passed in 0.06s
ok  fresh-queen-attack             stub: 13 failed, 1 passed in 0.16s             example: 14 passed in 0.01s
ok  fresh-matrix                   stub: 8 failed in 0.14s                        example: 8 passed in 0.01s
ok  fresh-trinary                  stub: 7 failed in 0.14s                        example: 7 passed in 0.01s
ok  fresh-allergies                stub: 50 failed in 0.27s                       example: 50 passed in 0.03s
ok  fresh-say                      stub: 20 failed in 0.17s                       example: 20 passed in 0.02s
ok  fresh-kindergarten-garden      stub: 19 failed in 0.17s                       example: 19 passed in 0.02s
ok  fresh-roman-numerals           stub: 27 failed in 0.21s                       example: 27 passed in 0.02s
ok  fresh-custom-set               stub: 34 failed, 6 passed in 0.25s             example: 40 passed in 0.03s
ok  fresh-matching-brackets        stub: 20 failed in 0.17s                       example: 20 passed in 0.02s
ok  fresh-rail-fence-cipher        stub: 6 failed in 0.14s                        example: 6 passed in 0.01s
ok  fresh-sublist                  stub: 1 failed, 21 passed in 0.14s             example: 22 passed in 0.04s
ok  fresh-state-of-tic-tac-toe     stub: 29 failed in 0.21s                       example: 29 passed in 0.02s
ok  fresh-game-of-life             stub: 8 failed in 0.15s                        example: 8 passed in 0.01s
ok  fresh-flower-field             stub: 16 failed in 0.17s                       example: 16 passed in 0.01s
ok  fresh-nucleotide-count         stub: 7 failed in 0.14s                        example: 7 passed in 0.01s
ok  fresh-luhn                     stub: 23 failed in 0.18s                       example: 23 passed in 0.02s
ok  fresh-pascals-triangle         stub: 10 failed in 0.16s                       example: 10 passed in 0.07s
ok  fresh-saddle-points            stub: 10 failed in 0.16s                       example: 10 passed in 0.01s
ok  fresh-linked-list              stub: 24 failed in 0.21s                       example: 24 passed in 0.02s
ok  fresh-hexadecimal              stub: 10 failed in 0.15s                       example: 10 passed in 0.01s
ok  fresh-nth-prime                stub: 6 failed in 0.14s                        example: 6 passed in 0.03s
ok  fresh-yacht                    stub: 29 failed in 0.21s                       example: 29 passed in 0.02s
ok  fresh-minesweeper              stub: 15 failed in 0.17s                       example: 15 passed in 0.01s
30/30 exercises grade right
```
