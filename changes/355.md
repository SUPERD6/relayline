- p4 evaluation, round 2 (#346, experimental, nothing run): `--split r2b` / `r2c` read any number of tasks from a
  frozen `--tasks-file`, refused unless `--tasks-sha256` matches. New arm `ccxcheapfirst2` (hub: `dispatch.cheap_first`
  plus `check.sensitivity = "escalate"`; its lead writes a failing test first, commits it and passes it as `--check`,
  per the #326/#338 guidance) delegating to Claude by default (`--child-agent`). New options `--episode-size`
  (1 = each task its own lead session), `--self-lead-budget`, `--max-escalation-rate` (default 0.3, `none`),
  `--max-invalid-rows` (default 3 for r2b/r2c: invalid rows are kept, cost-unknown ones charged at their reservation),
  `--codex-web-search disabled` (default for r2b/r2c; adds `-c web_search="disabled"` to every Codex exec through
  `codex_tmp.py`), `--max-tasks`, `--max-operational-usd`. The dry run prints each arm's effective settings, the
  default first rung computed from ccx's tiers, reviewers, network settings and stop rules; v2 rows record the
  lead's `--check`, its sensitivity receipt, the ledger's first rung and cap hits. Old splits, arms and their dry-run
  output are unchanged.
