- Round 2 B: 9 final authored tasks on the tabula library (`r2b-tabula-1` … `r2b-tabula-9`, `source: "authored"`,
  author model Opus 5.5), each a reference change plus hidden tests under `scripts/eval/round2_bc/tabula/tasks/`:
  query `in` / `not in` / `between`; joins with differently named keys, `validate` and `indicator`; comment lines in
  the reader and writer; most-common-value and percentile aggregates, `dropna`, `top_n`; strict diff types,
  tolerances, ignored columns and a render limit; window functions per group and `shift`; a `date` column kind
  across schemas, inference and JSON Lines; flattened / nested records; backward fill, interpolation and a per-run
  limit. Every task is 68–107 implementation lines; builds are byte-identical, `build.py check` and the native P4
  check pass 9/9, and the leak check is clean (highest brief ratio 0.33). Check outputs in
  `docs/research/data/round2-bc/b-formal-tabula-*.json`. The tabula starting tree and the development tasks are
  unchanged. Refs #375.
