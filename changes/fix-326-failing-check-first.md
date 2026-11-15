- Delegation guidance: before sending a write task, the lead writes at least one test (or checkable command) for the
  new requirement, sees it fail, passes it as `--check`, and puts concrete inputs and expected outputs in the brief
  (agent-delegate skill, its Chinese README and brief template; `ccx run -h --check` and the no-check tip say the
  check should fail before the change). The existing suite passes before the change and cannot see a new
  requirement; in the 2026-11 unified test (G3/G4) that let a cheap first rung's wrong work through. Text only: no
  default or option changed (#326).
