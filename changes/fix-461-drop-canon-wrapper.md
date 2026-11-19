- Internal: `scripts/eval/strength_runner.py` drops its `canon()` wrapper and `_DRIVE_MANGLED` (a workaround for the
  `D:/a/x` -> `d:a:/x` bug in `preflight.canon`, fixed in #460); call sites use `PF.canon` directly. No behaviour change
  (Fixes #461).
