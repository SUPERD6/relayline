- `[review] skip_when_clean` (experimental, default `false`, effect Unknown, to be evaluated; #427): when on, a write
  run's automatic independent review is not started if the run is mechanically clean: `--check` passed, not weak, and
  sensitive (failed before the change; needs `[check] sensitivity` warn/escalate), at most `skip_max_files` (3) files
  and `skip_max_lines` (49) changed lines with no binary or long new file, every changed file on a whitelist (source
  files changed or added, test files only new; no delete, rename, config / data / lock / snapshot file, conftest.py,
  testdata/ or __snapshots__/), no edited or added-to pre-existing tests, check basis not self-authored, no open
  questions, reported files matching the diff, no sub-agent commit, not `--review on` / a fix round / `--risk visible`
  or `critical`. Inline tests in source files and adversarial source or new-test changes cannot be judged. The
  receipt says `review.verdict = "skipped"` with `review.skipped` (why); run.json keeps `review_skip.unmet`, the
  ledger row `review_skipped: true`; `ccx ui` shows "skipped (clean)" in a neutral colour. Off: unchanged.
