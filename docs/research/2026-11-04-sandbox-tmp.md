# Windows sandbox temporary directories: Stage 1-A

[中文](2026-11-04-sandbox-tmp.zh.md)

## Measured on 2026-11-04

Commands ran inside the assigned Codex shell, on `Windows-10-10.0.26200-SP0`, Python 3.11.9 (AMD64),
PowerShell 5.1. The session declared `workspace-write` with approval disabled. The delegation described the
Windows backend as `unelevated`; the backend/account/ACL was not independently inspected. No tool home or
credential directory was inspected. The native default Temp was writable in this session, including after the
follow-up's declared writable-root list contained only the workspace. Writable roots are a session condition,
not a general promise about every Codex sandbox.

A disposable test file contained two tests: one used pytest's `tmp_path` to write/read a file; the other directly
created a UUID-named directory under `os.environ['TMP']`, wrote/read a file, then removed it in `finally`.
Three fresh Python processes ran `python -m pytest -q -s -p no:cacheprovider <test_tiny.py>`, with third-party
plugin autoload disabled. Only the outside/inside cases overrode all three of TMP/TEMP/TMPDIR. Default TMP and
TEMP pointed at the native system Temp; TMPDIR was set there in the first run and absent after the follow-up.
Paths below are redacted. The disposable test and its created directories were removed.

| TMP setting | pytest exit | Result |
|---|---:|---|
| Inherited system Temp | 0 | 2 passed; both fixtures and explicit file operations succeeded |
| Existing workspace parent, outside allowed workspace | 1 | 1 passed, 1 failed; pytest fell back to system Temp, direct mkdir was denied |
| A directory inside the assigned workspace | 0 | 2 passed; both kinds of temporary files were inside that directory |

The outside case's actual failure (only the personal path/UUID substituted):

```text
>       d.mkdir()
E       PermissionError: [WinError 5] Access is denied: '<workspace-parent>\\phase1a-<uuid>'
FAILED .phase1a-measure/test_tiny.py::test_explicit_tmp - PermissionError: [W...
1 failed, 1 passed in 0.17s
```

An earlier variant using `tempfile.TemporaryDirectory(dir=TMP)` instead of direct mkdir timed out after 30 s in
the outside case; pytest's `tmp_path` had already passed using its system-Temp fallback. The initial run with
plugin autoload enabled was interrupted after it produced no result. Neither is counted as a passing test.
These observations demonstrate a denied outside path, and why a fallback can mask it. They do **not** attribute
the historical hc2 WinError 5 events, whose exact failing operations/paths are unavailable.

## Candidate implementation: engineering check

`preflight.py`, `r5.py run`, and `batch.py run` accept `--codex-workspace-tmp` (experimental, **off by default**).
The evaluation replaces only its `CCX_CODEX_BIN` with an eval-only launcher. For an explicit `workspace-write`
invocation, the launcher creates a distinct `.ccx-eval-tmp-*` under that invocation's actual cwd and passes the
same absolute directory as TMP/TEMP/TMPDIR to the original CLI. First exec and resume use the same mechanism;
linked worktrees get their own directories. Read-only and non-exec calls retain their inherited environment.
No sandbox permission or user config is changed. Other agent CLIs keep the existing per-unit `x-*/tmp`.

The unit's local Git `info/exclude` ignores these directories (also in its linked worktrees); no tracked
ignore file is modified. The launcher removes its directory on normal exit; postflight removes a directory
left by interruption, and existing worktree cleanup handles linked worktrees. The report and row fingerprint
add `tmp_policy` (`unit-x` / `codex-workspace-private`; null for older reports). The existing
`fingerprint.codex_windows_sandbox` and daily sandbox fields are reused.

The Codex canary now runs a small Python file, requiring both its existing arithmetic result and a command's
successful temporary-directory create/write/read/remove marker. It rejects a fallback to a different Temp root,
mismatched variables, missing marker, or a nonzero command exit. Failure makes preflight fail before units start;
the existing explicit `--force-unclean` override and `--no-canary` behavior are retained.

Default user Temp passed the real probe, so `ccx/agents/codex.py`, `ccx/delegate.py`, and `ccx doctor` are unchanged.
This is an eval-only candidate, not a measured end-to-end repair of hc2 and not a product default change.

## Evidence retention

Every r5 unit keeps available lead JSONL and ccx child `events.<attempt>.log` / `stderr.<attempt>.log` before
hub cleanup, including success, hidden-test failure, and exception paths. Normal runs store them under
`<results-stem>-artifacts/<invocation>/<tag>-<unit>/streams/`; additive `row.streams` records relative file
names, byte lengths, SHA-256, invocation, and `redacted=true`. Library calls without an artifacts directory
use the legacy streams root as a fallback. The retained streams preserve event order and structure without
the diff-artifact size cap; they are redacted and are not byte-identical originals.

Only those explicit stream filenames are copied. Credential/config/session files and symlinks are not copied.
Known credential environment values, credential-shaped fields/assignments, common token formats, and known
machine paths are masked. Error text such as WinError 5 and its event/run/attempt association remain available.
This does not recover missing historical streams or copy native grandchildren's separate session files.

## Validation boundary

Fake CLI regressions cover equal variables, containment in each child cwd, independent invocation directories,
first exec/resume with and without a linked worktree, clean Git status, read-only preservation, and canary
success/missing/denied probes. Stream tests cover all result paths, retries, redaction, ordering, and hashes.
A subprocess starts the preflight script outside this checkout to verify flag-to-report wiring.

Final relevant-file run: **165 passed, 1 skipped, 2 deselected** across `test_eval_preflight.py`,
`test_eval_sandbox_tmp.py`, `test_eval_streams.py`, `test_eval_r5.py`, and `test_eval_batch.py`, with plugin
autoload disabled. The two exclusions are the process-observation tests described below. A final targeted
run also passed 25 tests. AST comparison confirmed all 71 pre-existing preflight test functions/classes
remain unchanged. The full repository suite was not run, as assigned to the lead.
After the final review, the stream-retention error path was made diagnostic-only to retain existing audit and
scoring meanings; all 67 stream/r5 tests passed, including cleanup after an artifact-write error. The sanitized
measurement data is kept locally at `.ccx/reports/optimize-20261104/phase1a-measured.json` (not committed).

In this sandbox, two pre-existing process tests could not observe their own detached child with process
enumeration / `alive()`. Running the original HEAD implementation reproduced both observations: the process
snapshot missed the child, and a child reported by the Job Object had `alive=false`. Their assertions remain
unchanged; the lead must rerun these outside the sandbox. Linux/macOS and a fresh paid native Codex evaluation
were not run. No result here establishes accuracy/cost improvement, CI success, or release readiness.
