- Eval: new `scripts/eval/handover_overhead.py` (#378), read-only, standard library only, no CLI or model calls. It splits
  one delegation's cost and wall time into four items (brief, CLI startup, sub-agent work, check and review) from result
  rows, the lead stream (`--artifacts`) and optionally ledger rows (`--ledger`), and prints each item's median and
  share per arm. Items the data cannot give (startup; a separate check/review wall; the first delegation message's
  duration) are `Unknown` with the missing field named, and are left out of the shares. Lead cost per item is
  allocated from the measured `lead_usd` by usage weight and labelled as such. No existing behavior changed.
