- Strength runs stop the group when a unit's ccx receipt has `status: "error"` (e.g. `kind: auth`), not only on a
  Python exception; `scripts/eval/unified_summary.py` counts such rows as invalid (Unknown) instead of a task failure,
  and says so in its valid definition. P4 rows have no top-level status and are judged as before (#321).
