# Issue #283: separate execution from acceptance evidence

Keep all execution fields, gates, defaults and exit codes. Reuse the existing additive `headline`
display cue across run output, show and UI rather than redefining `ok` or introducing a new verdict.
An independent passing check or a passing review supports `DONE`; self-authored checks keep
`SELF_CHECKED`, and absent or weak check evidence alone is `UNVERIFIED`. These labels describe
recorded evidence, not hidden-test correctness. No new configurable behavior is enabled.

Regression evidence: fake-CLI command tests and synthetic UI records only (engineering check).
