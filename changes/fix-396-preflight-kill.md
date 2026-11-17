- Eval clean room (#396): on Windows `preflight.kill()` no longer sleeps a fixed 0.5 s and then looks the pid up with
  `tasklist` (TerminateProcess is asynchronous and a pid can be reused, so a slow-exiting or reused-pid process was
  reported in `unkilled`). It opens a SYNCHRONIZE handle before `taskkill` and waits on it for up to 10 s, sharing the
  wait helper with `Job.close()` (#362); a process `OpenProcess` cannot open is checked by pid (only error 87 means
  gone), and all handles are closed in a `finally`. POSIX behaviour and the callers' use of `unkilled` are unchanged.
  All handles are opened before the first `taskkill`, so a child that dies with its parent cannot have its pid
  reused and hit by a later kill. Timing: normally faster than the old 0.5 s sleep; a process that really cannot be
  killed costs up to 10 s per call (about 20 s at worst in `after_unit`).
