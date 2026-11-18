- Cold-start table (experimental, still off by default) now judges "no history" per kind of work (#437): every
  learned outcome also records its kind (`kind_counts` {kind: {rung: n}} in the routing state and `kind` on the
  outcome; only added, `counts` unchanged). A candidate vendor with only `code` runs is still cold for `read` work.
  A pick fixed with `--tier` / `--model` / `--provider` records its kind from the run's mode. Runs with no recorded kind (state written before #437) count as history for every kind, so an old state file
  behaves as before; an unknown kind of work falls back to the per-vendor check. `route.cold_start` gains `by_kind`
  and its `why` names the kind it was judged by. With the table off every pick is byte for byte unchanged.
