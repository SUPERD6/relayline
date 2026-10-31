- Eval arms for B3's "fewer runs" switches (`scripts/eval/b3_arms.py`): m4 runs the same plan (four small pieces of
  round 2's ten-module task and one TRAPS2 trap, each with `minutes`, `paths` and its own `--check`) through
  `ccx batch` and `ccx batch --merge`; m3 runs `ccx run --parallel` with `[subagents] fork_turns = "all"` and
  `"none"`; m5 runs the 2026-10-25 shared-context tasks plus a new reopened-question task with `[shared_context]
  dedupe` off and on. Each unit has the round-5 clean room and the eval Codex home; both arms' hubs differ only in the
  switch, read back before the unit, and a unit counts only when ccx's own record shows the switch took (batch
  `merged`, run.json `parallel_fork_turns` and the prompt line, `shared_context.deduped`). Rows carry ccx runs,
  reviews, requests, the `first_input` sum (m3: plus each child's first request, from its rollout), total prompt
  tokens, $, wall and right. The decision rule is registered in `docs/research/2026-10-30-b3-lean-switches-plan.md`
  ("Fewer runs") before any unit ran: right not below the baseline, fewer runs or a lower `first_input` sum, total
  prompt not higher (m5: reported only; m3: also no child-context loss); fewer than 80% of the planned pairs, a switch
  that did not take or (m3) most pairs spawning no child is Unknown; `summary` applies it. No measurement yet (one pre-run unit only).
