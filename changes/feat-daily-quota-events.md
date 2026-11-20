- `ccx report --daily --quota-events` (off by default, the default page and JSON unchanged): adds decision 3 of the
  eval-rule decisions (#411) to the daily page. A `quota_events` object and a page section list quota events from 2026-11-19
  (sub-agent runs from `run.json` and the ledger, lead events from `.ccx/relay/` packets and continue records), give each a
  verdict (`success` / `failure` / `not_attempted` / `unknown`, with a reason and a machine or human source), and summarise
  combined and per role, whether there are at least 5 counted events with at least 80% success, the 95% Clopper-Pearson
  lower bound and the two-period rule (`--quota-split`). Human-only facts (waited for the reset, confirmation of an
  unconfirmed packet, nothing lost, marked done, lost work, excluded) are read from `<hub>/ccx/daily/quota-notes.jsonl`.
  New options `--quota-events`, `--quota-workspace`, `--quota-split`; new module `ccx/daily_quota.py`. (#480)
