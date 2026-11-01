- `ccx run --max-usd USD` / `ccx resume --max-usd USD` (P0-15; default `[run] max_usd`, 0 = no limit): the whole
  delegation (rungs, review, fix round) stops once it has spent USD, API-equivalent; the result says
  `max_usd: {..., note: "budget cap reached"}` with a `needs_lead` (no automatic soft verdict, no L2-merge evidence).
  Checked between steps: a running step finishes. `ccx config set run.max_usd 1` sets a default (only run / resume
  read it). `--budget` (the sub-agent's own sub-agents) is unchanged.
