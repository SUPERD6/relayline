- Fix test-review manifest discovery, repeated-file task citations and whitespace/Markdown punctuation matching;
  keep literal task grounding, independent execution, Unknown handling and default read review unchanged.
- Give test reviewers an execution-free finish instruction; retain manifest diagnostics, confirmation errors,
  per-call reviewer settings and native CLI costs alongside the existing API-equivalent estimate.
- Add opt-in `review.tests_model` / `review.tests_effort`, replay reviewer flags and repeated `--unit-cap MODEL=USD`;
  replace replay confirmation's plan mode with the existing read-only dontAsk/tool allowlist.
- Record the first-round 29-unit diagnosis without hidden-test text; all new validation uses fake CLIs.
