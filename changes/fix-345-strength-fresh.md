- Evaluation: `scripts/eval/strength_retest.py` can run round 2's group A on frozen new tasks (#345). `plan` / `execute
  context|memory` take `--tasks FILE --tasks-sha256 HEX` (a JSON task file, refused when its SHA-256 differs from the
  preregistered value; checked again right before `--run`), `--agents codex,dsh,claude` (Claude: `haiku` low),
  `--claude-home DIR` (a dedicated logged-in Claude home, checked by existence of `.credentials.json` only; Claude units
  use it as `CLAUDE_CONFIG_DIR` and get a unique synthetic lead session there) and `--on-invalid stop|continue`
  (default `continue` with `--tasks`: errored, receipt-error and unknown-cost units are recorded as `invalid` and the
  group goes on; a sub-agent's own timeout/cap with a known cost is a valid row with `ok` false and `hidden_ok` kept;
  it stops on the budget, a unit over its reservation, Ctrl-C, the 4th unknown-cost unit or a receipt of kind
  auth/quota). `--claude-home` must not overlap your own homes, hub or checkout, nor hold CLAUDE.md / agents / skills /
  commands. Claude units deny WebFetch/WebSearch (merged into any given settings); `--tasks` Codex units run with
  `[subagent] codex_lean_tools` in the unit hub (`-c web_search="disabled"`, also no image generation / goals; listed
  in the plan's `subagent_tools`). With `--tasks` the unit budget is at most $0.15 and the
  total cap is min($10, units × $0.15). `unified_summary.py strength --subset neutral` added; a row's own `neutral`
  flag decides its subset. Without the new flags plans and runs are unchanged (fingerprint test).
