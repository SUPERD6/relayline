# P5 reselection contract

[中文](2026-11-05-p5-reselection.zh.md)

> Checkout correction declared before rerunning: same 117 candidates, order,
> exclusions and qualification rules. Windows pins `core.autocrlf=true`, exports
> into an empty directory and overlays converted bytes, respecting attributes.
> Linux/macOS receive no new setting. Policy `native-git-checkout-v2` records actual
> Git EOL counts per row. The v1 zero-task result below is historical: a regression
> test proves its stat-clean archive files remained LF despite the setting.
> Offline validation only; no model outcomes or relaxed rules.

## Corrected CRLF validation

Verified the identical 117-candidate pool and complete ordering: 36 more-itertools,
49 boltons, 32 pluggy. Python 3.11.9 / pytest 9.1.1. Both Windows units and selection
pin `autocrlf=true`; `checkout_evidence` records actual Git EOL counts per row.
Linux/macOS receive no new configuration.

| Qualified candidate | Implementation | Parent full | Parent hidden | Reference hidden | Reference full |
|---|---|---|---|---|---|
| boltons `1216b467c10b852d08aa6895c80b6b9ec8f990d8`, September PR sweep | 44 lines, 4 files | 512 passed / exit 0 | 11 failed, 189 passed / exit 1 | 200 passed / exit 0 | 519 passed / exit 0 |

Implementation files: `cacheutils.py`, `jsonutils.py`, `strutils.py`, `urlutils.py`.
This meets the unchanged >=60 lines OR >=3 files rule. **Qualified 1/8, shortfall 7;
no complete four-task episode, runnable set 0/8, overall Unknown.**

Exclusions: 105 parent full failures, 9 parents not failing hidden checks, 2
reference hidden failures, 0 reference full failures. The one qualified candidate
is separately withheld for an incomplete episode. Baseline failure classification,
in priority order: 19 old timing assertions, 13 obsolete collections imports,
7 missing nose, 35 incompatible pytest hooks, 31 other baseline failures (no
common cause inferred). See the [manifest](../../scripts/eval/p5_long_selection.json)
and [CRLF summary](data/p5-crlf-reselection-summary.json). Raw logs are retained in
`.ccx/eval/p5-crlf-reselection-raw/`; previous logs remain intact. No models,
whole-project test suite or commits.

Reproduce with the same `p5_reselect.py` arguments and a separate output path;
`--previous` must retain the original exclusions. Repetition does not authorize
changing ordering, interpreter, dependencies or eligibility thresholds.

Frozen before offline validation: use only existing more-itertools, boltons and
pluggy caches, in that repository order; all locally cached single-parent history,
descending commit timestamp then full SHA ascending. Keep implementation Python
changes >=60 lines OR >=3 files, excluding docs, tests and stubs. Exclude P4
dev/final and all eight previously audited P5 commits. No model results are used.
Take the first passing full groups of four, stopping at eight accepted tasks.

The only added eligibility requirement is environment compatibility: with the unit's
native Git checkout and explicit external Python, the untouched parent full
`PYTHON -m pytest -q -o addopts=` must exit 0. Hidden parent checks must fail;
reference hidden checks and reference full suite must pass. Failures remain in the
selection record; do not patch old tests or relax rules. Task briefs derive from
commit requests, without test or patch content. No models run in this selection.

Run `scripts/eval/p5_reselect.py --help` for cache-only reproduction arguments.
Real model evaluation still requires the lead's pinned preregistration.

## Offline results (2026-11-05)

Windows native checkout, Python 3.11.9, pytest 9.1.1. Exhausted all 117 eligible-size
cached candidates after exclusions: **0/8 qualified, shortfall 8, Unknown**.
The new task list is empty and cannot form two episodes. No models ran.

| Repository | Candidates checked | Parent full exit 0 | Qualified |
|---|---:|---:|---:|
| more-itertools | 36 | 5 | 0 |
| boltons | 49 | 2 | 0 |
| pluggy | 32 | 4 | 0 |

106 failed original parent full checks. Of the remaining eleven, nine also passed
hidden tests on the parent, and two failed reference hidden collection; none
advanced to reference full checks. Failures include old timing assertions, missing
nose, obsolete pytest hooks and collections imports. No retries for favorable
outcomes, dependency installs or old-test edits. Full commit IDs, code line counts
and errors are in the [manifest](../../scripts/eval/p5_long_selection.json), with
[summary data](data/p5-reselection-summary.json) and local raw logs under
`.ccx/eval/p5-reselection-raw/`.

Three-arm dry-run: `--split p5 --gates p5 --arms self,ccxlong,ccxlongcheap --dry-run`.
There are zero runnable units and each arm estimates $0; this is not a complete
experiment price. Projecting the historical eight-task P4final actual costs onto
eight future tasks per arm gives self $1.015828 ($0.1269785/task), ccxlong $2.083943
($0.260492875/task), subtotal $3.099771. Cheap-arm and three-arm total costs remain
**Unknown**. This historical projection cannot establish savings or predict changed
task/context costs. The previous $15.213 size proxy used the rejected old eight
tasks and does not apply to the current empty set.
