- `ccx run --max-usd USD` / `ccx resume --max-usd USD` (P0-15; default `[run] max_usd`, 0 = no limit): the whole
  delegation (rungs, review, fix round) stops once it has spent USD, API-equivalent; the result says
  `max_usd: {..., note: "budget cap reached"}` and the recap `max_usd=reached`. Checked between steps: a running
  attempt finishes. `ccx config set run.max_usd 1` sets a default. `--budget` (the sub-agent's own sub-agents) is
  unchanged.
