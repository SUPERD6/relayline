- Eval: `scripts/eval/unified_summary.py` gains the round-2 statistics (#347), standard library only. `p4 --paired`
  adds a task-level block per subset: correctness difference with the one-sided 95% Tango (1998) score lower bound,
  per-task cost geometric-mean ratio with a one-sided 95% upper bound (paired t on log ratios), total-cost ratio,
  Claude's own spend (lead plus Claude-side ledger entries) with the same ratios, median-wall and per-task wall
  ratios, cap hits, observed first rungs checked against `--expected-first-rung`, strata by source and repository,
  and an all-rows secondary analysis charging unknown costs at `--reserve-usd`. New `holm` subcommand (Unknown
  counts as p = 1); strength pairs add `effect_rate = (b - c) / n_pairs`. Existing fields and outputs are unchanged
  (round-1 G1–G4 summaries recompute identically).
