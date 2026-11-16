- Evaluation: `scripts/eval/round2_tasks.py` (#348) selects and checks round 2's new tasks before any run, following
  the round 2 pre-registration: a mechanical repository list from a top-pypi snapshot (GitHub source, permissive
  license, not used before), upstream commits on or after 2026-07-01 for B (first 60, at most 6 per repository) and
  C (next 24 of at least 150 lines or 5 files, at most 4 per repository) whose parent suite passes and whose hidden
  tests fail on the parent and pass on the commit, every exclusion with its reason; authored-task validation (hidden
  fails on start, passes on reference, existing suite passes); brief checks (hidden-assert literals found in the
  brief, trace table coverage); a leakage scan of ids, repository + commit and normalized briefs (ratio >= 0.6
  flagged, > 0.4 listed) against everything under `scripts/eval/` and `docs/research/data/`; an `--ext-python` check
  that no task's own package released at or after its commit is installed; dependency preparation that installs
  wheels except the package itself; and a SHA-256 manifest with LF-normalized text. Never calls a model.
  `long_candidates.history` and a `timeout` on `long_environment.baseline` are factored out for it; existing callers
  behave as before.
