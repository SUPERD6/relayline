# Optimization results: cost, review and evidence limits

English · [中文](2026-11-05-optimize-results.zh.md) · [Measured](../measured.md)

Snapshot: 2026-11-05. **No candidate in the accessible evidence justifies a default promotion.**
Short-task round B fails its cost gate. Historical long-session P4 fails cost and time gates.
Review diagnostic A is Unknown and heavily budget-limited. This report makes no new model calls,
changes no defaults, commands, options, JSON meanings or exit codes, and does not establish subscription savings.

## Scope and reproducibility

The authorized raw inputs are exactly the three files below. Raw logs remain local because they contain
machine paths and session metadata. The script prints only aggregates, basenames and content hashes.
Paths in this command are placeholders supplied by the reader; it can run from outside the checkout:

```text
python /path/to/relayline/scripts/eval/optimize_summary.py --long /data/p4final-results.jsonl --short /data/p3r2-results.jsonl --review /data/p2r3b-review-replay.jsonl
```

| Key | Local source relative to the experiment checkout | Rows | SHA256 |
|---|---|---:|---|
| L | `.ccx/eval/p4final-results.jsonl` | 16 | `06d17caf499b35e6c0c542dc41759da3ac38a7e5f0b5644984f60cb99a4a9af3` |
| S | `.ccx/eval/r5/p3r2-results.jsonl` | 60 | `ca3db8dc983d88479046abfe815a346968e608bd6ae0a00db1961fa8bcae4603` |
| R | `.ccx/eval/p2r3b-review-replay.jsonl` | 29 | `630f23e8c571f96fc5a5a905de2308dde8c56c062c72897d3b495455872f943b` |

All newly reported measurements below are recomputed from those raw rows. Gate constants and planned sample
sizes come from the preregistrations, not measured data. Earlier prose-only results are explicitly secondary
evidence: their raw files were outside this task's read scope, so their exact measurements are not republished.
**Unknown here does not overturn a recorded historical Fail.** It marks the limit of this independent audit.

Preregistration source: branch `prereg/optimize-20261104`, `docs/research/prereg/`:
`2026-11-04-p0.zh.md`, `2026-11-04-p2.zh.md`, `2026-11-04-p2-r2.zh.md`,
`2026-11-04-p3.zh.md`, `2026-11-04-p4.zh.md`, `2026-11-04-p5.zh.md`,
and `2026-11-05-round2.zh.md`. These files were read from the separate preregistration checkout;
they are not present in this branch. They should accompany any externally released report.

## Stage register

Sample sizes in rows without a raw key are **registered plans**, not independently verified completions.

| Stage | Pin | Sample / gate | Verdict and evidence limit |
|---|---|---|---|
| P0 attribution | `b9d1d54` | Planned self: 10 tasks × 3; clean ≥25. Paired wall ratio ≥1.5 or ≤1.2; cost ≥1.2 or ≤1.05; middle ranges Unknown | Secondary `p0-result.md`: wall Unknown, cost attribution Pass. Independent raw audit **Unknown**; no default decision |
| P1 engineering repairs | Unknown as one stage-wide pin | No outcome benchmark authorized here | **Unknown** for real-world benefit; implementation/tests are not a measured improvement |
| P2 review first round | `dec375e` | Planned 29 receipts: 15 wrong, 14 right; ≥25 replayed; caught ≥8/15, false blocks ≤2/14, Unknown bounded both ways | Secondary `p2-r1-result.md`: **Unknown**; raw audit Unknown |
| P2 review second round | `b7f9463` | Same cohort and gates | Secondary `p2-result.md`: **Fail**; raw audit Unknown. Reused, inspected material; tests mode stays experimental/off |
| P3 short tasks first round | `6fd1d1b` | Planned 30 per arm; clean ≥50 overall and ≥25 per arm; right ≥self−1; cost/success ≤1.2×self | Secondary `p3-result.md`: **Fail**; raw audit Unknown; several switches changed together |
| P4 development | `a00e507` | Planned four tasks per episode; workflow diagnosis only | **Unknown**; incomplete episodes and cumulative-accounting bug; no gate adjudication |
| P4 final (L) | `5acfa7d76479d55ab18dd8e8061ca0fd6a339f46` | Two episodes × four tasks × two arms; clean ≥12/16 and ≥6 per arm; all episodes complete; cost ≤0.8×self, right ≥self, median wall ≤2×self | **Fail** on recorded rows; historical LF check contamination prevents clean causal interpretation |
| P5 A installed but unused | Not filled in P5 preregistration | Planned new 30 per arm; right ≥self−1, cost/success ≤1.2×self; clean ≥24 per arm | **Unknown / not run in supplied evidence**; requires equivalent real installation injection |
| P5 B vendor quota | Not filled in P5 preregistration | Planned eight new tasks per arm; Claude-side cost ≤0.5×self; right ≥self; clean and complete episodes | **Unknown / no new rows supplied**; historical P4 child vendor attribution is missing |
| Round 2 A aborted diagnostic | `f46c993` | Same old receipts; no gate relaxation | Preregistration records an all-budget-error attempt; excluded from efficacy, retained in spend. Raw audit **Unknown** |
| Round 2 A retry (R) | `f46c99329ce8b57d30c4387e732b1f64ed020f92` | Same 29 receipts; sonnet medium; caught ≥8/15, false blocks ≤2/14; best/worst Unknown bounds | **Unknown**, engineering replay on known material; not an additional independent final set |
| Round 2 B (S) | `b5c72f026998` (full preregistered pin `b5c72f026998dd93ba7e4e1b56a399b3bc8319d2`) | New 30 tasks per arm; right ≥self−1; cost/success ≤1.2×self; clean ≥24 per arm | **Fail** numerically; recorded concurrency 2 conflicts with the one-evaluation-at-a-time protocol |
| Round 2 C | `b5c72f026998dd93ba7e4e1b56a399b3bc8319d2` registered | Reused P4 tasks, three arms; original cost/right/time gates, separate Claude gate | **Unknown / rows not supplied**; reused tasks can only diagnose |
| Round 2 D discuss | Unknown | Conditional on remaining budget | **Unknown / rows not supplied** |

Secondary reports are local files under `.ccx/reports/optimize-20261104/`. They disagree about first-round
P2 spend (`p2-r1-result.md` versus `p2-result.md`); no amount is adopted and no project-wide spend is inferred.
The later A preregistration also changes the budget after an aborted attempt: preserve that amendment and
do not represent the retry as having run under the original budget.

## Recomputed measured rows

USD means **API-equivalent USD**, including all recorded failed attempts, not a subscription invoice.
Cost/success = sum of all attempted costs / hidden-test successes. Wall is a true task median and a sum,
not the elapsed duration of a parallel experiment. Missing costs or zero successes yield Unknown.
No independent task-completion definition is stored here, so completion rate is Unknown; attempted rows
and hidden-test correctness are reported separately.

All and clean views coincide for L (16/16 clean) and S (60/60 clean). Those flags do not rule out LF or
protocol contamination. CLI fingerprint in L/S: Claude Code 2.1.316, codex-cli 0.164.0, Python 3.11.9,
Windows; Sonnet medium lead. The R reviewer field is `claude:sonnet:medium`.

| Source / arm | Hidden right / attempted | Total AE USD | AE USD / success | Median wall, s | Cumulative wall, s |
|---|---:|---:|---:|---:|---:|
| L self | 7/8 | 1.015828 | 0.145118 | 39.7575 | 371.093 |
| L ccxlong | 7/8 | 2.083943 | 0.297706 | 218.5935 | 1774.921 |
| S self | 29/30 | 0.611806 | 0.021097 | 9.35 | 321.2 |
| S ccx3cand | 29/30 | 0.775579 | 0.026744 | 11.3 | 359.0 |

L ratios ccxlong/self: total cost **2.051472**, median wall **5.498170**; right counts tie.
Cost and wall gates fail. S cost/success ratio **1.267688** fails the cost gate; right counts tie and pass
the correctness gate. S has **0/30 recorded delegations** in the candidate arm and zero child cost:
this measures candidate lead/prompt overhead, not the price or quality of a worker doing these tasks.
All S cost is on the lead side. These one-round samples are signals, not two independent replications
or a general claim that every delegation is more expensive.

L lead costs are self **$1.0158279**, ccxlong **$0.125456**. The remaining ccxlong **$1.958487** is child
cost including review; vendor attribution is Unknown in these old rows. A lead-only ratio **0.123501**
cannot prove a Claude-side quota reduction. Do not add `ccx_review_usd` again to `ccx_usd`.
See the [vendor-attribution explanation](2026-11-04-stage5-tools.md).

## Review diagnostic and budget failures (R)

| Hidden label | Blocked (`issues`) | Passed | Unknown | Denominator |
|---|---:|---:|---:|---:|
| Wrong | 0 | 2 | 13 | 15 |
| Right | 0 | 5 | 9 | 14 |

Confirmed catch **0/15**; confirmed false block **0/14**. Neither treats Unknown as a pass.
Worst case: caught **0/15**, false blocks **9/14**. Best case: caught **13/15**, false blocks **0/14**.
These straddle the preregistered gates, hence **Unknown**. It is not a demonstration of effective review.
R spent **$1.865314**, with **74 tests written and 74 run**. **20/29 rows** contain a reviewer-call budget
error; **22/29** are Unknown. Unknown reasons: **19** could not write tests; **3** had assertion failures
not confirmed as correct, in-scope tests. These categories overlap budget errors and must not be summed.
Test count alone is not catch rate. R is a retry after A's budget failure, not the budget-failed first attempt.
That first attempt's spend is not included in $1.865314: total A/program spend is **Unknown** in this audit.
The old cohort has been inspected and reused; literal original user requests were not preserved, so it
cannot test the benefit of forwarding those requests. Stronger reviewer plus contract/prompt changes are not isolated.

## Contamination and boundaries

**P4 LF false check failures.** The experiment used archive-style LF worktrees on Windows. This task flags
false acceptance failures caused by that checkout policy; the later preregistration requires CRLF/native
checkout and a passing baseline. Historical `env_clean=true` is not proof of a clean acceptance command.
The allowed final rows do not independently identify the affected checks, their count or avoidable costs:
those are **Unknown** here. Do not rewrite hidden outcomes, remove rows or subtract guessed repair costs.
The recorded Fail remains; a clean rerun would be new evidence, not a retrospective Pass.
The [native checkout contract](2026-11-05-p5-contract.md) describes baseline checks; this audit does not rerun them.

**Cumulative-accounting bug.** In development, resumed Claude result totals were added as though they were
per-call costs, double-counting earlier turns. The final protocol uses differences between validated cumulative
totals per session/arm. L has no false `cost_cumulative_check` or `session_match` flags. This audit sums final
per-task `usd` and does not sum `episode_usd` or cumulative counters again. It does not reread the streams or
independently validate their token accounting. See [the correction](2026-11-04-p4-cost-accounting.md).

**Protocol and selection.** S fingerprints record concurrency **2** despite the single-evaluation requirement.
The arithmetic Fail holds; environmental equivalence and an uncontaminated final comparison remain Unknown.
Both L interventions (delegating and reading one receipt line) changed together. Reusing P4 in round 2 C
does not make it an unseen set. Different versions and task sets must not be pooled as repeated trials.

**Receipts and generalization.** These three inputs do not supply a cohort of ordinary `ok` receipts for a false-positive
rate: that rate and its bound are Unknown, not zero. No new statistical superiority/non-inferiority claim is made.
These are threshold checks on small, single-configuration samples. Windows evidence is not macOS/Linux runtime
validation. No fresh P5, round 2 C/D, live quota handoff, CI or product-wide improvement is established here.

## Practical conclusion

For these measured short and medium tasks, automatic delegation is not a demonstrated cost advantage.
Do small tasks directly by default. Delegation can still be useful for separate tool access, bounded independent
work or shifting work off a constrained provider, but those are use cases to validate, not measured benefits
established by this report. Independent acceptance, failure accounting and honest Unknowns are necessary before
promoting a cheap-first or review-dependent path. Keep unproven behavior opt-in and retain the negative results.
