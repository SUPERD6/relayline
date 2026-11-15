- Evaluation scripts end the whole process tree on a timeout (#332): `strength_runner.run_tree()` (#329) moves to
  `scripts/eval/common.py`, and the 20 timed `subprocess.run` calls in 15 more scripts (`ccx run`/`resume`, the real
  CLIs, the review replay workers) use it. Results are as before (returncode/stdout/stderr; a TimeoutExpired carries
  the output read so far); the child's stdin is the `input` or DEVNULL. Its children no longer get the terminal's
  Ctrl+C, so the four threaded scripts (`shared_context_ab`, `r4`, `review_replay`, `rereview_replay`) map through
  `common.map_stopping()`, which on Ctrl+C drops the queue and ends the running trees (`common.stop_running()`).
  Evaluation logic, gates and outputs are unchanged.
