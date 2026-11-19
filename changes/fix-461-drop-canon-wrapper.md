- Internal: `scripts/eval/strength_runner.py` drops its `canon()` wrapper and `_DRIVE_MANGLED` (a workaround for the
  `D:/a/x` -> `d:a:/x` bug in `preflight.canon`, fixed in #460); call sites use `PF.canon` directly. The one
  difference: the literal text `d:a:/x` is no longer rewritten to `d:/a/x` (not a real Windows/Git Bash spelling);
  a test pins it (Fixes #461).
