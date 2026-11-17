- Eval: new read-only `scripts/eval/receipt_fp.py` (#377), standard library only. From result rows (a strength
  directory or a P4 JSONL, optionally with the hub's `ledger.jsonl` for rows that keep only run ids) it counts how
  often a receipt that claims success (`ok`, `ok_self_checked`, `done`, `UNVERIFIED` when a row carries a lead-view
  headline) still fails the hidden test, per receipt type, as failures / n with a one-sided 95% Clopper-Pearson
  upper bound (n = 0 is Unknown, bound 1.0). `--by FIELD` splits further; `--text` prints a table. No evaluation
  behaviour changes.
