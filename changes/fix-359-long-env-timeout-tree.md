- Evaluation: `long_environment.py` `baseline()` and `hidden()` run pytest through `common.run_tree` (#359): a
  timeout now ends pytest and everything it started, not only the shell (baseline no longer goes through a shell;
  same `PYTHON -m pytest -q -o addopts=` command and recorded fields). `hidden()` takes `timeout` (default 180, as
  before).
