- Experimental cold-start table for automatic model choice, off by default (`routing.cold_start = false`; with it off
  every pick is byte for byte as before, locked by a regression test). Switched on, it acts only on task-routing's pick
  and only when no candidate vendor has a learned outcome yet: the first rung's tier then comes from the new
  `[cold_start]` table in `config/tiers.toml` (per kind of work, difficulty b at most a bound -> tier; provisional,
  unmeasured bounds). The table names tiers, never a vendor; the vendor stays task-routing's pick. A choice the
  person fixed (`--to`, `--model`, `--effort`, `--tier`, `--provider`, or a role) is never changed, and `rung_why`
  gains a `user_fixed` line saying so; `route.cold_start` says whether the table applied and why. Dry run and real
  run start on the same rung (#426).
