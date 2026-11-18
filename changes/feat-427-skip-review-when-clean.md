- `[review] skip_when_clean` (experimental, default `false`, effect Unknown, to be evaluated; #427): when on, a write
  run's automatic independent review is not started if the run is mechanically clean: `--check` passed, not weak, and
  sensitive (failed before the change; needs `[check] sensitivity` warn/escalate), at most `skip_max_files` (3) files
  and `skip_max_lines` (49) changed lines with no binary or long new file, no edited, renamed, deleted or added-to
  pre-existing tests, no changed test configuration, check basis not self-authored, no open questions, reported files
  matching the diff, no sub-agent commit, not `--review on` / a fix round / `--risk critical`. The receipt says
  `review.verdict = "skipped"` with `review.skipped` (why); run.json keeps `review_skip.unmet`, the ledger row
  `review_skipped: true`; `ccx ui` shows "skipped (clean)" in a neutral colour. Off: unchanged.
