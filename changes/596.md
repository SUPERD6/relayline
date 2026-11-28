- Add `scripts/eval/router_replay.py` (offline, no CLI, $0): replays router rules (always self, always delegate,
  threshold on a row feature tuned on one half of the tasks and scored on the other) over any rows file and prints
  the oracle upper bound (per task the better arm). Experimental measurement tool; no command or option changed.
  Kept: every `ccx` command and option. Checked by `tests/test_router_replay.py`. Refs #544.
