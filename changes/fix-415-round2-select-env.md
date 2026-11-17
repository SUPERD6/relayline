- Evaluation (#415): the round-2 task tools give upstream candidates the environment their suites need, so a parent
  baseline no longer fails only because of how `--ext-python` was filled. `round2_tasks.py prepare` (new
  `--pypi-meta`, required when kept packages are needed as dependencies) installs a kept package that another
  repository needs, and pytest, at its highest final release first uploaded before the selection date limit
  (2026-07-01), with its kept dependencies pinned the same way, never at the latest release; it also downloads the
  requirements of each repository's `[dependency-groups]` test/tests/testing/dev at the clone's HEAD, retries a
  failed install file by file, and writes the final `pip list` into its output (now `{"rule", "repos", "pins",
  "pip_list"}`; the command fails when `pip list` cannot be read). Because release dates alone do not prove a release
  lacks a change, `select` compares each commit with the installed copy of the task's own package: lines it adds to
  code files (30+ characters stripped, not comments, found nowhere in the parent's code files) that appear in the
  installed files exclude it at 2 hits or when all of them hit; an installed package that cannot be compared is
  excluded as unknown (the rule is in the selection's `rule.installed_overlap`, exclusions carry the installed version
  and examples). `select --prepare-json` records prepare's SHA-256 and the `--ext-python` version. `select` records on each task the install-time version files its parent's `pyproject.toml` declares
  (setuptools-scm `version_file` / `write_to`, hatch vcs hook `version-file`; relative paths inside the tree only)
  and does not contain (`stubs`, written with `ext_repo.VERSION_STUB`) and `pythonutf8: true`; `authored` checks
  also run with `PYTHONUTF8=1`. Validation (`long_environment`) and the P4 run (`p4_long_session`: start repository,
  the lead's per-task environment, hidden-test scoring) honor both; a task without `pythonutf8` gets the episode's
  inherited value back, so nothing carries over to the next task. The selection rules themselves are unchanged.
