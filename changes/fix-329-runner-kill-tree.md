- Eval: the strength runner (`scripts/eval/strength_runner.py`) now ends the whole process tree when a `ccx run`
  (or a setup `ccx` call) times out, not only the direct child: it starts the child with `ccx.runners.group_flags()`
  and stops it with `ccx.runners.kill_tree()`; on POSIX the descendants (ccx starts its CLI in a group of its own)
  are listed with `preflight.snapshot()`/`family()` first and killed with `preflight.kill()`. The row still says
  `error: "TimeoutExpired"` with Unknown cost, and the group still stops (#329).
- Unified preregistration: 2026-11-13 change-log entry (G1 run 3 valid on PIN3 `e69b892e…`; G2 run 1 Unknown at
  unit 51/72; G2 reruns on `PIN4`, output `unified-g2r`).
