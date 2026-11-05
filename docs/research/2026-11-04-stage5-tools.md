# Stage 5 offline evaluation tooling

English · [中文](2026-11-04-stage5-tools.zh.md)

**Superseded eligibility:** the eight-task table below is the historical hidden-only check. The later
[P5 contract audit](2026-11-05-p5-contract.md) adds whole-parent baselines: only two tasks qualify and no complete
episode is currently runnable. The current manifest records that exclusion, not the historical eight-task Pass.

Evidence: **engineering check**. Offline hidden-test validation only; no real model, paid canary, model evaluation, download or credential access.
No existing command/option was removed. P4's default split, fields, exit codes and gates remain unchanged;
new side fields and an explicit `--gates p5` report are additive.

## A: installed-only arm stopped at equivalence check

**Unknown, not run:** Claude Code 2.1.316 flags do not establish equivalence to the installer's native `@MEMORY.md` import and hooks; the lead stopped A, so no `ccx2inst` arm is added.

## B: new long-session split and side accounting

`p5_long_select.py --ext-cache CACHE` reads only existing local git caches. It reuses `long_candidates.py` and
`long_check.py`: implementation `.py` changes >=60 lines OR >=3 files; exclude tests/docs/`.pyi`, holdout commits,
and every P4 dev/final commit. Keep repository priority, timestamp descending, SHA ascending, and complete groups
of four from one repository. Validate parent hidden tests fail and reference hidden tests pass; retain rejections,
missing repositories, raw output hashes and shortfalls. Never download or relax eligibility to fill eight places.
Provisional briefs use commit subjects only, not patches or reference solutions; review their request completeness
before preregistration, without changing selection based on model outcomes.

The lead supplied a read-only cache and Python environment. Selection screened **81** candidates before accepting
**8/8**, using Python **3.11.9** and pytest **9.1.1**, with no model outcomes. The complete selection, exclusions,
rejections and parent/reference outcomes are in `scripts/eval/p5_long_selection.json`.

| Repository | Commit | Change | Implementation lines | Parent rc | Reference rc |
|---|---|---|---:|---:|---:|
| more-itertools | `6887a7bd5ac3` | running_median | 71 | 1 | 0 |
| more-itertools | `bbe6c8f7f3f5` | sample counts | 65 | 1 | 0 |
| more-itertools | `5252383356e6` | Fourier transform recipes | 67 | 1 | 0 |
| more-itertools | `02e753222ce2` | grouper recipe | 126 | 1 | 0 |
| boltons | `c669103ccbaf` | range2list / list2range | 115 | 1 | 0 |
| boltons | `294344b84fbd` | bidirectional daterange | 69 | 1 | 0 |
| boltons | `d14b5a793d18` | cachedmethod descriptor | 61 | 2 | 0 |
| boltons | `6cea9343927b` | BufferedSocket thread safety | 348 | 2 | 0 |

All eight references passed. The two parent collection failures are missing newly introduced `cachedmethod` and
`MessageTooLong` imports; these retain rc=2, as allowed by the unchanged selection checker. Other rejected old
references include conflict markers, timing-test failures and pytest 9's rejection of an old `pytest_ignore_collect`
hook signature. Tests/environment were not changed to admit them. Full normalized pytest logs and hashes were
retained under the worktree-local `.ccx/eval/p5-selection-raw/` (ignored; preserve with the review evidence).
`--run --split p5` still refuses fewer than eight tasks. Legacy `--split all` still means the original twelve P4 tasks.

Every new result line retains compact `side_ledger` evidence (including review rows). `p5_costs.py` adds:

| Field | Meaning |
|---|---|
| `claude_side_usd` | Native Claude lead, including native sub-agents, plus Anthropic-model ledger costs |
| `codex_side_usd` | OpenAI-model ledger costs |
| `unknown_side_usd` | Known child amounts without sufficient vendor/model attribution |
| `side_cost_status` | Pass only when monetary inputs and attribution are complete; otherwise Unknown |

Classify explicit vendor/model, or model names in ledger `rungs`; never guess from a CLI/provider name.
A multi-vendor ledger row without per-attempt costs is Unknown. Missing or mismatched ledgers keep the entire
known child amount in Unknown. Lead cost still uses the existing validated cumulative-difference accounting.
Both all-row and clean-row summaries show side totals. An interrupted attempt also retains these fields.

`--gates p5` adds a separate report, using all sixteen attempts for costs and correctness: eight per arm, paired
task identities, every four-turn conversation completed successfully, >=12 clean rows and >=6 per arm. Missing
cost/attribution/completion evidence is Unknown. With sufficient evidence, Pass requires Claude-side total
`ccxlong/self <= 0.5` and right count `ccxlong >= self`. Total-cost ratio and wall-median ratio are descriptive,
without a new wall threshold. The P4 `all` / `env_clean` verdicts remain present and unchanged.

## Commands (no model call unless explicitly using --run)

```bash
python scripts/eval/p5_long_select.py --ext-cache CACHE --ext-python PYTHON --raw-dir RAW --output scripts/eval/p5_long_selection.json
python scripts/eval/p5_long_select.py --ext-cache CACHE --ext-python PYTHON --raw-dir .ccx/eval/p5-recheck-raw --output .ccx/eval/p5-recheck.json
python scripts/eval/p4_long_session.py --dry-run --split p5 --gates p5 --rounds 1 --tag p5long --budget 9 --out RESULTS.jsonl
python scripts/eval/p4_long_session.py --run --split p5 --gates p5 --rounds 1 --tag p5long --budget 9 --pin-commit FULL_SHA --ext-cache CACHE --ext-python PYTHON --codex-home DEDICATED_HOME --wait-quiet 10 --out RESULTS.jsonl
python scripts/eval/p4_long_session.py --recompute P4FINAL.jsonl --tag p4final --gates p5
```

The second command reproduces selection/validation outside the sandbox without overwriting the frozen manifest;
replace CACHE and PYTHON with the lead-supplied existing paths. Machine-specific paths are not stored in this repo.
The real-run example requires committed preregistration/pin, explicit cache and the lead's authorized dedicated Codex
home; none was opened here. The eight-task / sixteen-attempt dry run estimates **$11.064** total: **$6.915 self**,
**$4.149 ccxlong**, from the existing historical size/context formula. This exceeds the example's $9 budget;
the lead must decide the execution budget before any real run. The estimate is not measured P5 spend or a billing
guarantee. No paid run was started and no budget was raised.

Read-only replay of **16 historical p4final rows** (pin `5acfa7d76479`) gave:

| Arm | Known Claude-side USD | Known Codex-side USD | Unknown-side USD | Attribution |
|---|---:|---:|---:|---|
| self | 1.015828 | 0 | 0 | Pass |
| ccxlong | 0.125456 | 0 | 1.958487 | Unknown |

The ccxlong Claude amount is a **known lower bound**, not its complete Claude-side total. Old rows do not retain
the child vendor/model ledger. This replay cannot establish a Stage 5 cost Pass. Both arms have 7/8 correct and
8/8 clean; total costs are $1.015828 and $2.083943. The source JSONL's SHA256 stayed unchanged.
