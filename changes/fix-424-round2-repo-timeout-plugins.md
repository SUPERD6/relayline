- Evaluation (#424): `scripts/eval/round2_tasks.py select` reads the 10-minute suite limit as a repository condition:
  the round-2 pre-registration lists it among the repository conditions but says "on the parent", so it is
  ambiguous; until now each candidate was judged on its own, now the repository's other candidates are excluded
  after its first candidate whose parent's full suite times out (tasks already taken from it stay). Side effect: a
  repository whose suite runs close to 10 minutes can lose its other candidates to one slow run. Each task also
  records `pytest_plugins`, the pytest plugin modules its parent declares (the `--ext-python` pytest11 entry points
  of distributions named in pyproject dependencies, test/tests/testing/dev extras and dependency groups, setup.cfg
  and requirements files, plus extras the project asks of itself such as `pkg[cov]` or `-e .[test]`; not the task's
  own distribution; never pytest-randomly, pytest-random-order, pytest-enabler, pytest-rerunfailures, pytest-retry,
  flaky or pytest-ignore-flaky), plus the project's own pytest11 entry points, and, when it has version stubs,
  `stub_version`, the leading version of the nearest parent tag that starts with one (else 0.0). Validation
  (`long_environment`), the P4 run (lead environment, reset per task) and scoring load those plugins through
  `PYTEST_PLUGINS` with autoload still off, and write stubs reporting that version (`ext_repo.version_stub`). The
  selection lists each selected task's plugins (`pytest_plugins_loaded`) and the repositories over the time limit;
  setup.py, poetry, hatch envs, pdm and tox are not read (written in the selection's rules).
