- Eval: `scripts/eval/receipt_fp.py` gets the receipt false-positive bar of decision 2 in
  `docs/research/2026-11-17-eval-rule-decisions.md` (#411, confirmed 2026-11-19). Each receipt type now carries a
  `verdict`: Pass when the point estimate is <= 2% and the one-sided 95% Clopper-Pearson upper bound is <= 5%, Fail
  when the point estimate is > 2%, otherwise Unknown (too few receipts, or n = 0), plus `bar`
  (`point_max`, `upper95_max`) next to the existing `failures` and `n`. `--text` adds a verdict column. The smallest
  passing samples 0/59, 1/93, 2/124 and 4/200 are test cases. `all_claims` stays descriptive, and the existing
  fields (`below_2pct`, `status`, `upper95`) keep their meaning. Fixes #478.
