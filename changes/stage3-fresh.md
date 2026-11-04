- Add the opt-in `fresh` evaluation task set: 30 pinned Exercism Python exercises selected by a fixed salted hash,
  excluding all 34 polyglot Python exercises and two stubs already passing their hidden tests.
- Add the experimental `ccx2cand` evaluation arm with unit-local user wording and small-task/strict-escalation
  switches, pre-launch assertions, required `--files` guidance, routing/source telemetry and fresh-specific summaries.
  Keep existing commands, options, defaults, result fields and exit codes; extend the offline grader for fresh/exemplar.
