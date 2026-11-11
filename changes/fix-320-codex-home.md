- `scripts/eval/strength_retest.py execute` takes `--codex-home DIR`, a Codex home you logged in to yourself; Codex
  units use it as `CODEX_HOME` instead of a fresh empty folder (every Codex unit got 401). A run with Codex units and
  no usable `--codex-home` stops before the first unit; the folder is checked like `p4_long_session.py`'s (#320).
