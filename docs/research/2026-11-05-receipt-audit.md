# Eight P4 receipts: execution ok versus acceptance

[中文](2026-11-05-receipt-audit.zh.md)

This is a read-only audit of historical artifacts, not a new evaluation. Source: each
`.ccx/eval/p4final-results-artifacts/20261105-000145Z/*ccxlong-*/streams/lead.jsonl`.
All eight receipts contain `ok:true`, `status:partial`, `check.passed:false`, check exit 1,
and `outcome=check_failed` in the recap. The table records the final lead response, not a correctness verdict.
The explanations attributed to Codex were not independently checked in this audit.

| Unit | Run | Receipt / final-response line | What the lead finally said |
|---|---|---|---|
| 1-1-ccxlong-1 | 20261104-190247-3319 | 14 / 17 | Used `DONE:` for iterutils fixes and added regression tests, explicitly said the full-suite check failed and acceptance was not clean, and accepted because `ok=true`. |
| 1-1-ccxlong-2 | 20261104-190703-c776 | 15 / 17 | Used `DONE:` for file/path/named-container fixes, repeated the unverified claim of 52 targeted passes, and explicitly said the full-suite check failed and acceptance was not clean. |
| 1-1-ccxlong-3 | 20261104-191333-a50d | 11 / 13 | Used `DONE:` for GC/type/tracing fixes, repeated the unverified claim of 18 targeted passes and newline/sandbox problems, and explicitly said acceptance was not clean. |
| 1-1-ccxlong-4 | 20261104-191641-6116 | 15 / 17 | Used `DONE:` for set operations, repeated the unverified targeted-test counts and newline explanation, and explicitly said the full-suite check failed and acceptance was not clean. |
| 1-2-ccxlong-1 | 20261104-192309-6a4a | 11 / 14 | Started with `DONE:` for mapping fixes, said pytest still failed on a JSON test, attributed the LF/CRLF explanation to Codex, and accepted the partial receipt without inspecting or rerunning. |
| 1-2-ccxlong-2 | 20261104-192745-6853 | 15 / 17 | Started with `DONE:` for BarrelList compatibility, said full pytest still failed and the cause was unknown because the summary was truncated, and accepted as instructed. |
| 1-2-ccxlong-3 | 20261104-193237-772a | 10 / 12 | Started with `DONE:` for ellipsize and its new tests, accepted because `ok=true`, and reported full pytest failure plus Codex's unverified targeted-test/newline claims and truncated additional problem. |
| 1-2-ccxlong-4 | 20261104-193606-4929 | 11 / 13 | Started with `DONE:` for USTimeZone and its new tests, accepted because `ok=true`, and reported full pytest failure plus Codex's unverified 212 targeted passes and newline explanation. |

All eight used `DONE:` and all eight disclosed the failed check. This is an ambiguous completion/acceptance
signal, not evidence that the lead claimed eight clean test passes. No hidden scores, costs, prior verdicts or
published conclusions were changed.

## Why this happened

`ccx/delegate.py` stores the adapter's `oc.ok` in `record.ok`; a failed acceptance check sets `kind=check_failed`
without changing that execution flag. `exit_ok()` excludes several other failure kinds, but not `check_failed`.
`compact()` adds the existing blocked/failed-worker and environment exclusions. Thus execution success can
produce JSON `ok=true` and exit 0 even when acceptance fails. The worker's status is separate too.

`ccx/leadview.py` normally compacts only `clean()` results; `CCX_LEAD_VIEW=line` does not force failed checks
into one line. The P4-only `scripts/eval/p4_receipt.py::render` instead compacts every `ok=true` receipt via
`leadview.line`, hiding hints/full details while retaining the failed check and recap. The P4 prompt in
`scripts/eval/p4_long_session.py::prompt` explicitly says to accept and stop inspecting when `ok=true`,
permits diagnosis/repair only otherwise, and tells both arms to finish with `DONE:`. Those instructions
promote the execution flag to an acceptance gate and explain the observed response pattern. This audit
leaves that historical protocol and its results unchanged; a future protocol change needs its own preregistration.

## Presentation fix and evidence limits

Serialized compact JSON now begins with `headline`, for example
`{"headline":"CHECK_FAILED","run_id":"...","ok":true,"status":"partial",...}`.
A JSON field preserves existing parsers; a bare text prefix would break them. Failed/broken checks take
precedence over completion. Other cues include `REVIEW_ISSUES`, `PARTIAL`, `BLOCKED`, `FAILED`, `STOPPED`,
`RUNNING`, `SELF_CHECKED`, `UNVERIFIED`, and `DONE`. They summarize existing evidence; even `DONE` does not
prove hidden-test correctness. The label is added at serialization, so underlying records and existing fields
remain unchanged. Native full output and compaction eligibility remain unchanged. P4 execution-ok task receipts
also receive this first field. No flag, default, command, option, exit code or acceptance rule changes.

Evidence level: **engineering check** for the fix (targeted fake-CLI/unit tests); **not run** for any new paid
model evaluation. Whether this label changes real lead behavior, cost or correctness is **Unknown**.
Tests cover failing-check `ok=true` receipts through the actual wrapper from outside the repository, native
one-line output through `ccx.py`, and field/exit-code compatibility. Existing tests are retained unchanged.

Local checks: the initial regression run failed all 15 then-present cases on the old presentation. After the fix,
`tests/test_receipt_headline.py`, `tests/test_leadview.py`, `tests/test_p4_long_session.py` and
`tests/test_p4_budget_selection.py` passed together (74 tests, 12 subtests). After adding a stale-headline regression,
the headline and change-note tests passed together (30 tests, 15 subtests). Change-note format and `git diff --check`
also passed. No full suite, remote CI, Linux/macOS execution or real model call was run for this change.
