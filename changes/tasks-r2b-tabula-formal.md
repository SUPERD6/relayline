- Round 2 B: 10 final authored tasks on the tabula library (`r2b-tabula-1` … `r2b-tabula-10`, `source: "authored"`,
  author model Opus 5.5), each a reference change plus hidden tests under `scripts/eval/round2_bc/tabula/tasks/`:
  query `in` / `not in` / `between`; joins with differently named keys, `validate` and `indicator`; comment lines in
  the reader and writer; most-common-value and nearest-rank percentile aggregates, `dropna`, `top_n`; strict diff
  types, tolerances, ignored columns and a render limit; largest-remainder rounded shares (`stats.apportion`, used by
  `share` and `pivot(normalize=)`); a `date` column kind across schemas, inference and JSON Lines; flattened /
  nested records; backward fill, interpolation and a per-run limit; nonnumeric quoting as a typed round trip between
  writer and reader. Every task is 70–101 implementation lines; builds are byte-identical, `build.py check` and the
  native P4 check pass 10/10, and the leak check (including the 43 upstream B briefs) is clean (highest ratio
  0.34). Check outputs in `docs/research/data/round2-bc/b-formal-tabula-*.json`. The tabula starting tree and the
  development tasks are unchanged. Refs #375.
