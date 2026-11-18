- Routing (#440): `ccx doctor --backfill-kinds` rebuilds `kind_counts` of the routing state from old run records
  (`runs/*/run.json`, read only, `route.kind` else the run's mode), so history learned before #437 counts per kind in the
  cold-start check. Adds only, never more per rung than the skill's `counts`, what cannot be placed stays "unknown
  kind", done once (marker `kind_backfill`) under the state lock. No pick changes without the option.
