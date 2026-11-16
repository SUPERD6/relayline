- Pre-register the round 2 evaluation (design only, not run; running needs the user's budget approval and a new
  cumulative cap): new, harder, frozen tasks with leakage checks; one run per task with the task as the unit of
  analysis; 48 / 48 / 60 / 24 tasks from a power analysis and budget. Each group's CLI follows the question it answers:
  A shared context and memory on a same-vendor (Claude Haiku) sub-agent plus a Codex replication (two Holm families),
  B cheap-first v2 within one vendor (`--child-agent claude`, `sensitivity = escalate` + #326 prompt) vs self as
  correctness non-inferiority plus cost and wall bounds that must also hold on all rows and on a
  repository-cluster bootstrap, C long tasks to a cross-vendor (Codex) sub-agent, diagnostic.
  Lead-vendor spend is a secondary metric; conclusions are for a Claude lead only; the default first rung must come
  from the dry-run and match the ledgers.
  Remaining script work is tracked in #345, #347 and #367 (`docs/research/prereg/2026-11-16-round2.md`).
