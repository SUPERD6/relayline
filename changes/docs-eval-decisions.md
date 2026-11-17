- Docs: three evaluation-rule decisions, approved by the maintainer: lead-vendor spend is the primary cost metric of
  quota-scenario claims (total spend a guardrail; from the next quota-scenario preregistration, round 2 unchanged);
  the ordinary `ok` receipt false-positive bar is point ≤ 2% and one-sided 95% Clopper-Pearson upper bound ≤ 5%;
  "work does not stop when quota runs out" is judged on at least 5 naturally occurring limit events with ≥ 80%
  success (`docs/research/2026-11-17-eval-rule-decisions.md`). Plus a design note: automatic splitting stops at the
  piece, and inside a piece the tool decides (`docs/research/2026-11-17-split-to-pieces.md`). No code or default
  changes.
