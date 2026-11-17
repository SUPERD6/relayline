- Evaluation (#424): `scripts/eval/round2_tasks.py select` applies the 10-minute suite limit as the repository
  condition the round-2 pre-registration states: after the first candidate whose parent's full suite times out, the
  repository's other candidates are excluded without running pytest again (tasks already taken from it stay). Each
  task now also records `pytest_plugins`, the pytest plugin modules its parent declares (the `--ext-python` pytest11
  entry points of distributions named in pyproject dependencies, test/tests/testing/dev extras and dependency groups,
  setup.cfg and requirements files, not the task's own distribution, plus the project's own pytest11 entry points),
  and, when it has version stubs, `stub_version`, the first `digits.digits...` of `git describe --tags --abbrev=0` on
  the parent (else 0.0). Validation (`long_environment`), the P4 run (lead environment, reset per task) and scoring
  load those plugins through `PYTEST_PLUGINS` with autoload still off, and write stubs reporting that version
  (`ext_repo.version_stub`).
