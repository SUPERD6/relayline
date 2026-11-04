# Hook and report timing (stage 1-E)

English · [中文](hook-report-speed.zh.md)

Evidence: **engineering check**, 2026-11-04, Windows, Python 3.11+, synthetic files only.
Baseline source: `1cf7d897aac62bf4c78643b2f8cb80a345ce3074`. This is not a live-client measurement or
a claim about research quality. No configuration default, command, option, exit code or JSON field was removed.

## Fixture and observations

`python scripts/benchmark_hook_report.py` creates a temporary hub with 50,000 old verdict rows, 200 conversation
files of 2,501 lines each, and a 5,000,012-byte JSON file. Three repetitions run sequentially. Old verdicts exercise
all-time trust and exclusion without making a savings bootstrap dominate the I/O measurement. The report excludes
lead usage. No real ledger, credentials, user homes or model CLIs are read. Archival uses `tests/fakes/fake_codex.py`.

| Path | Before, ms (three runs) | After, ms (three runs) | Median before → after, ms |
|---|---|---|---|
| Report, no lead | 397.681, 336.414, 336.007 | 114.597, 97.134, 95.121 | 336.414 → 97.134 |
| Session discovery | 1172.622, 85.253, 88.622 | 1212.970, 76.792, 75.849 | 88.622 → 76.792 |
| JSON read, same Reader | 10.021, 0.097, 0.052 | 9.931, 0.114, 0.056 | 0.097 → 0.114 |
| Archival on hook path, 14 fake CLI calls | 1010.290, 913.609, 897.876 | 5.846, 4.773, 4.801 | 913.609 → 4.801 |

The initial report/discovery/JSON baseline ran before edits. The archival baseline was reconstructed afterward by
calling the unchanged original `archive.auto(p)` synchronously (`--archive-mode sync`). Its comparison measures
scheduling latency, not faster archival: all 14 records were archived in each of three repetitions, with completion
waits outside the timed path. Cold discovery still takes about 1.2 seconds here. JSON already had stat caching and
was left unchanged; its small timing difference is not evidence of improvement. Times vary with filesystem caching
and host load. An intermediate run overlapping the related tests was discarded from this table.

The final script defaults to `--archive-mode auto`: it imports the new worker only if available, otherwise uses
the old synchronous call. The identical script was copied into a temporary `git archive HEAD` checkout without
`archive_worker.py` and successfully ran the full fixture (one replay: report 420.379 ms, discovery 1236.704 ms,
JSON 8.908 ms, synchronous archival 1058.422 ms; all 14 archives completed). This checks baseline compatibility;
that single replay does not replace the three-run observations above.

## Implementation and checks

The report uses a process-local, call-scoped ledger snapshot, including nested accuracy and trial statistics; it
expires at the end of the call, including on error. Lead usage is read only when the existing report requests it;
an active trial still reads the lead costs needed for its published trial section. Discovery caches only the first
Codex metadata line, bounded to 256 entries and invalidated by mtime, size, inode and ctime. Directory discovery is
still performed each time so new or removed sessions are visible.

The hook uses its existing timeout as an injectable cooperative budget. After each completed hint section it saves
the complete text envelope. Expiry skips later steps; a blocked read still hits the existing hard watchdog, which
flushes the saved text before attempting to write the timeout log. No ready section means empty output. Normal
output remains byte-for-byte unchanged. Cooperative exits are not counted as hard timeouts.

Archival runs in a separate process with null stdin/stdout/stderr, closed inherited descriptors and the existing
windowless background flags. A daemon waiter reaps the worker while its parent remains alive. Workers reuse the
ability module's OS lock implementation under a separate `archive.lock`; a busy worker skips, and process death
releases the lock. Existing archive selection and accounting rules stay intact. A failed launch does not fail the hook.

Targeted tests cover exact JSON and HTML/text equality, fixed baseline SHA-256 snapshots with lead usage both on
and off, one ledger read, all-time exclusion/trust, snapshot expiry, fake-clock budget expiry, watchdog checkpoint
output, cache invalidation, existing JSON caching, busy archive locks and launch flags/reaping. Subprocess tests run
`ccx mem delta` from outside the repository: one advances a fake clock; another waits for real background effects
using the fake CLI and checks idempotency. Existing report tests exercise the report CLI from an outside directory.

Validation: the related report/archive/transcript/ability/hook run passed 164 tests. A further hook/UI/trial run
passed 112 tests and skipped 13 browser or platform-dependent cases. The final stage-specific run passed 10 tests,
including the external-process OS-lock check. `scripts/collect_changes.py --check` and `git diff --check` passed.
The full suite is reserved for the lead and was not run here.

Review follow-up: session-start scheduling now ignores `CCX_NO_AUTO_ARCHIVE`, matching the original `archive.auto`
semantics (the variable still controls after-run archival). The lead authorized updating only
`tests/test_sessions.py::TestOneShotAndArchive::test_auto_archive_at_session_start`: after the hook returns, poll
for a complete archive journal row with a 60-second safety deadline, then run the unchanged original assertions.
The test keeps its existing environment and fake CLI. No other pre-existing test was modified. A new subprocess
regression gates fake archival on a socket signal: it observes the hook returning while archival is still blocked,
then explicitly releases the worker and checks completion. There is no elapsed-time speed assertion. Both tests
passed; output is in `.ccx/reports/hook-report-speed/async-contract-tests.txt`.

These are experimental engineering checks. Real desktop hook delivery, visible-window behavior, orphan adoption
on each supported OS, Linux/macOS execution, remote CI and timing against real user data remain **not run / Unknown**.

## PR #268 safety review

All three reported P2 issues were confirmed in the source and fixed:

| Issue | Change | Regression evidence |
|---|---|---|
| Resume could miss an archive that had not written its journal yet, or be archived just after restoration | Archive/restore operations and publication of a resumed running record now share the same reentrant OS lock; archival skips any session named by a running record, including when an older ledger row names it | Signals pause a fake archive before journaling. Resume waits, unarchives and publishes its running record; another worker skips it. An external `ccx resume` also verifies archive → unarchive → exec ordering |
| A hung external archive command held the worker lock forever | External archive commands have a 30-second timeout. Commands use the existing process-group flags and tree cleanup before direct-child termination/reaping. The timeout branch never waits for inherited output pipes again. Timed-out archival is not journaled as completed, so a later worker can retry | A fake CLI signals readiness and blocks. Injected `TimeoutExpired` avoids waiting 30 seconds. A further wrapper regression covers inherited output handles; see the review note below |
| A relative hub was resolved again after changing the worker cwd | Resolve the hub to an absolute path before choosing the worker cwd and argv | An external hook with a relative `CCX_HUB` archives the correct synthetic hub |

Five new safety regressions passed. Logs: `.ccx/reports/hook-report-speed/p2-safety-tests.txt`.
The related archive/session/hook run passed 49 tests; the final timeout regression also passed separately.
Logs: `.ccx/reports/hook-report-speed/p2-related-tests.txt` and `p2-timeout-final.txt` in the same folder.
No existing test setup or assertion was changed for these fixes. The prior timing table has not been rerun for this
safety patch and must not be treated as a fresh performance measurement of it.

Further timeout review confirmed that `subprocess.run` only killed the wrapper: Windows could then wait forever
on a Node descendant's inherited pipes. `_run` now uses `runners.group_flags()` and `kill_tree()` while the wrapper
is still alive, then terminates and waits for the direct child, without a second `communicate()` call. The new
`tests/test_archive_tree_timeout.py` regression runs an actual `.cmd` → Python wrapper → leaf tree on Windows.
It injects timeout and simulates the OS tree termination with a release signal, verifies ordering, descendant exit
and lock release. It passed. Actual `taskkill /T /F` returned failure in this restricted environment, so real OS tree
termination remains unverified here.

The existing timeout test initially failed because its global Popen fake also intercepted the new `taskkill`
helper and expected that helper to print `archive-ready`. The lead authorized restricting this fake to the archive
command. Its cleanup and retry assertions are unchanged, and it now passes.

The lead also required lock-budget exhaustion to preserve the original best-effort resume behavior. When startup
cannot acquire `archive.lock`, it attempts the original unsynchronized restore, publishes the running record and
continues. That record adds `archive_restore_lock_timeout: true`; existing fields and success rules are unchanged.
The thread-local bypass is confined to this fallback and restored on exit. Serialization is therefore best effort
when the lock budget is exhausted. A new external `ccx resume` test holds the real OS lock and injects exhaustion
without waiting for the timeout, verifies the restore attempt, successful fake-CLI resume and persisted field.

The three direct checks passed; both normal archive/resume interleaving checks also passed. Logs:
`.ccx/reports/hook-report-speed/final-two-fixes-tests.txt` and `final-resume-normal-tests.txt` in the same folder.
