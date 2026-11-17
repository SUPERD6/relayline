- `[review] skip_when_clean` (experimental, default `false`, effect Unknown, to be evaluated; #427): when on, a write
  run's automatic independent review is not started if the run is mechanically clean: `--check` passed, not weak, and
  sensitive (failed before the change; needs `[check] sensitivity` warn/escalate), at most `skip_max_files` (3) files
  and `skip_max_lines` (50) changed lines, no edited pre-existing tests, check basis not self-authored, no open
  questions, no sub-agent commit, not `--review on` / a fix round / `--risk critical`. The receipt says
  `review.verdict = "skipped"` with `review.skipped` (why); run.json keeps `review_skip.unmet`. Off: unchanged.
