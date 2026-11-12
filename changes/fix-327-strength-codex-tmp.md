- `scripts/eval/strength_runner.py`: a Codex unit's `TMP`/`TEMP`/`TMPDIR` is an existing `tmp/` folder in the unit,
  and Codex runs through `codex_tmp.py`, so each workspace-write `codex exec` gets a private temp folder inside its
  working directory, as in `p4_long_session.py`. Under Windows' unelevated sandbox the system `%TEMP%` is not
  writable and PowerShell hung until the unit timed out (#327). The shared part is now
  `preflight.codex_workspace_tmp_env()`, also used by `prepare()`.
- Unified test preregistration: change log for 2026-11-12. G1 run 2 is Unknown (PowerShell hang, #327); G1 and G2
  move to `PIN3`, the main commit after this fix; G1 writes to `unified-g1r2`.
