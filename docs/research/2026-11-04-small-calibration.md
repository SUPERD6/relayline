# Small-task calibration, 2026-11-04

[中文](2026-11-04-small-calibration.zh.md)

Evidence: **engineering check** (offline descriptive reanalysis of historical development data).
Threshold validation: **Unknown**. No new model calls, final-set validation or effect proof.
All six named results files were parsed using Python; no other eval files were read.
The [machine-readable table](2026-11-04-small-calibration.json) records file counts, diffstat line bands,
source, unique tasks, version pins, all/clean subsets, total cost and cost per success.

| Historical run / pin | Arm | Right / attempts (unique tasks) | Total API-equivalent USD | USD / success | Clean right / attempts; USD / success |
| --- | --- | --- | --- | --- | --- |
| pg1 / 5d4bd01 | self | 25/30 (30) | 0.914983 | 0.03660 | 24/29; 0.03631 |
| pg1 / 5d4bd01 | ccx2 | 12/30 (30) | 1.380978 | 0.11508 | 12/29; 0.11176 |
| pg3 / b9d1d5431982 | ccx2 | 2/2 (2) | 0.147941 | 0.07397 | 0/0; Unknown |
| pg3b / b9d1d5431982 | ccx2 | 15/30 (30) | 1.462103 | 0.09747 | 15/30; 0.09747 |
| hc1 (holdout file) / b473976 | self | 29/30 (10) | 2.621804 | 0.09041 | 29/30; 0.09041 |
| hc1 (holdout file) / b473976 | ccx2 | 29/30 (10) | 1.826339 | 0.06298 | 29/30; 0.06298 |
| hc2 / b9d1d5431982 | ccx2 | 28/30 (10) | 2.411267 | 0.08612 | 25/27; 0.08769 |
| p0self / b9d1d54 | self | 30/30 (10) | 2.966083 | 0.09887 | 30/30; 0.09887 |

Source is the strongest descriptive signal: on pg1's small strict-interface Exercism tasks, self is cheaper
per success; on historical repository holdout hc1, ccx2 is cheaper. These are historical versions, not current
controls. hc2/p0self have different tags and condition histories and are not a fresh matched experiment.

Actual file count cannot calibrate the routing estimate: pg1 self changes <=1 files on 7 attempts (5 right,
$0.03826/success) and 2–3 files on 23 (20 right, $0.03618/success), whereas **every pg1 ccx2 row changes >3 files**.
These counts include workflow artifacts and are post-outcome. In hc1, <=1-file self is 15/15 at $0.03552/success
and ccx2 is 3/3 at $0.02730/success: different tasks enter the bins. They are not paired comparisons.
Diffstat likewise counts all reported insertions/deletions, including artifacts and tests. Its <=50/>50 bands
are recorded in JSON, but cannot identify a pre-run boundary. No threshold has independent validation.

Recommendation: retain **small_self_files=1**, **small_self_overhead_usd=0.035**, with both new switches **off**.
The pg1 ccx2 lead-only median is $0.034553 (clean $0.034993), supporting $0.035 as an overhead proxy, not an
optimal decision threshold; hc2's median is $0.050744. Do not increase the file threshold based on the 2–3-file
signal. Ten repository tasks repeated three times are ten independent task units, not thirty distinct tasks.
All used data, including the old holdout, is development data now. Future validation must preregister pre-run
size features, pin versions/conditions, retain failures, and separate these two interventions if attributing effects.

Reproduce with `python scripts/eval/calibrate_small.py <r5-results-directory> --out <report.json>`.
The script reads only `pg1-*results.jsonl`, `pg3*results.jsonl`, `hc2-*results.jsonl`,
`p0self-*results.jsonl`, `holdout-*results.jsonl` directly under that directory.
