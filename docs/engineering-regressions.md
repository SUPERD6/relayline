# Engineering regression coverage

[中文](engineering-regressions.zh.md)

Evidence level: **engineering check** (fake CLIs only). No real agent calls,
performance measurements or cross-platform execution are implied.

The four regression tests cover the paths below. The original-wording test
is now an ordinary passing regression test; its expected-failure marker was
removed after test review began receiving the saved wording.

`tests/test_engineering_regressions.py` adds:

- Both original-input files in one delegation: original task in test review and
  the repair's re-review, original wording and `source=file` in both builder
  runs, and explicit resume task replacement with the saved wording unchanged.
- A subprocess chain from a directory outside this repository:
  `run -> show -> verify -> resume -> stop -> undo -> ui --export`. Stopping an
  already completed run keeps its existing exit code 2; undo restores the
  beginning of the session chain. Live stopping is already exercised by
  `tests/test_preflight_e2e.py::TestPreflightSteps::test_stop_then_resume`.
- A real detached archive worker, triggered by `mem delta`: a socket handshake
  delays actual archival until after the hook exits. Before release there is
  no journal entry or archive CLI call; after release the journal contains the
  session and the fake archive command has completed. This checks latency by
  causal ordering, without a machine-speed threshold or sleep.

Existing subprocess coverage is retained rather than duplicated:
`tests/test_ccx.py::TestMemory::test_cli_delta_silent_when_empty_and_for_subagents`
and the adjacent memory CLI tests, `tests/test_board.py::TestBoard::test_to_all_and_reply`,
`tests/test_projects.py::test_where_command`, and the retry/resume/fallback
coverage in `tests/test_user_words.py`. All commands and options are preserved.

## Fixed regression: original wording reaches test review

Run the regression with:

```console
python -m pytest -q tests/test_engineering_regressions.py -k user_words_file_reaches
```

Previously, a test reviewer could receive only the rewritten brief when the
builder received `--user-words-file`. Test review now uses `ccx/review_task.py`
to supply the saved `user-words.md` with source metadata alongside the assigned
task. The regression checks that the independent reviewer receives the wording
and that the run retains `source=file`. This is fake-CLI wiring evidence.
