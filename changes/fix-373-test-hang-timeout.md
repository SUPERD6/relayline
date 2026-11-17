- Fixed (#373): `scripts/eval/common.map_stopping` could leave the run hanging after Ctrl+C. Its wait loop polled with
  `concurrent.futures.wait`, which takes each future's lock; a Ctrl+C landing while the main thread held that lock left
  it held for good, the worker finishing that future blocked in `set_result`, and the executor's `shutdown(wait=True)`
  (the `with` block's exit, the interpreter's exit) never returned. The loop now sleeps in `time.sleep` and learns of
  finished futures from a done callback, holding no lock while it waits. This is what held
  `test_map_stopping_gets_ctrl_c_while_workers_run` for hours (once locally, and the Windows job of PR #372's first CI
  run). The test now bounds the executor's shutdown (a stuck worker fails it with every thread's stack), and a new
  test sends Ctrl+C at random moments of the wait loop (the old loop failed it in 3 of 8 runs on Windows; it is a probabilistic check).
- CI: the test job has `timeout-minutes: 90` (it had GitHub's 6-hour default) and runs pytest with
  `-o faulthandler_timeout=600`, so a test running over 10 minutes prints every thread's stack into the log.
