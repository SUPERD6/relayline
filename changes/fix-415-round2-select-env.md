- Evaluation (#415): the round-2 task tools give upstream candidates the environment their suites need, so a parent
  baseline no longer fails only because of how `--ext-python` was filled. `round2_tasks.py prepare` (new optional
  `--pypi-meta`) installs a kept package that another repository needs, and pytest, at its highest final release
  first uploaded before the selection date limit (2026-07-01), with its kept dependencies pinned the same way, never
  at the latest release; it also downloads the requirements of each repository's `[dependency-groups]`
  test/tests/testing/dev at the clone's HEAD. Its output is now `{"rule", "repos", "pins"}`. `select` records on each
  task the install-time version files its parent's `pyproject.toml` declares (setuptools-scm `version_file` /
  `write_to`, hatch vcs hook `version-file`) and does not contain (`stubs`, written with `ext_repo.VERSION_STUB`) and
  `pythonutf8: true`; validation (`long_environment`) and the P4 run (`p4_long_session`: start repository, lead
  environment, hidden-test scoring) honor both. The selection rules themselves are unchanged.
