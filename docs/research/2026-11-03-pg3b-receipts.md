# pg3b: receipt recheck on 30 polyglot exercises (2026-11-03)

English · [中文](2026-11-03-pg3b-receipts.zh.md) · [Research reports](README.md) · [hc2 follow-up](2026-11-04-hc2-holdout.md)

**Insufficient evidence under the preregistered rule:** there were zero ordinary `ok` receipts, below the minimum
of 10. This run cannot measure the 2% false-positive threshold. Of 29 `ok_self_checked` receipts, 15 failed hidden
tests; independent review passed all 29. Such a review pass is not evidence that the answer is right.

## Preregistered method and decision

Rules were fixed on 2026-11-03 before execution: 30 polyglot Python exercises, one round, ccx2 (Sonnet lead
delegating through ccx), hidden tests for scoring, candidate pin `b9d1d54`. The primary metric was hidden-test
failures among final ordinary `ok` receipts, excluding `ok_self_checked`; final receipts came from the lead's
event stream. Report self-checked failures, hidden-test successes, spend, environment contamination and Unknown.
With at least 10 ordinary `ok` receipts, zero false positives permits continuing release, any false positive stops
release; fewer than 10 means insufficient evidence. Even zero out of 30 cannot establish a rate below 2%.

The initial pg3 attempt stopped after two units ($0.148): refreshing the model cache changed its fingerprint.
Both rows were unclean and excluded. Restarting as pg3b used the refreshed baseline, the same pin and unchanged
metrics; the decision followed the environment guard, not outcome selection, but both initial `ok=True` results
had already been seen. A $1.85 restart cap kept combined spend, including the earlier attempt, below the original $2 cap.
All 30 pg3b rows were `env_clean=True`; pg3b cost $1.462.

| Final receipt | Hidden tests pass | Hidden tests fail | Total |
|---|---:|---:|---:|
| `ok_self_checked`, `ok=true`, review pass | 14 | 15 | 29 |
| `review_failed`, `ok=false` | 1 | 0 | 1 |
| Total | 15 | 15 | 30 |

## What this establishes and what remains Unknown

- #223's label worked: self-written checks were marked `ok_self_checked`, never ordinary `ok`. These tasks had
  no supplied tests, so every check was self-written. The design therefore missed the primary denominator.
- `ok_self_checked` still means `ok=true`, exit 0; consumers must read the kind or receipt text. Review gave pass
  to all 29, including 15 wrong answers; its sole issues verdict was actually right. Review did not run hidden tests.
- Hidden-test success was 15/30 versus historical pg1 ccx2 12/30. This small rerun does not establish improvement.
- The pre-#223 audit remains 8/209 = 3.8%; this run cannot remeasure that ordinary-receipt error class. These small
  tasks have a different composition from the audit, one lead configuration, and do not represent large tasks.
- The follow-up [hc2](2026-11-04-hc2-holdout.md) supplied ordinary receipts but only six with `status=done`;
  there is still no sufficient post-#223 done-receipt retest of the 2% threshold.

Spend is API-equivalent: pg3 $0.148 + pg3b $1.462 = $1.61; adding hc2 $2.411 gives **$4.02 rounded**.
