- personal-data check (`tests/test_repo_hygiene.py`, run by `.github/workflows/hygiene.yml`, #493): a new pattern flags
  `pytest-of-<name>`, pytest's temp folder named after the OS login, which leaked through error lines and logs.
  Placeholders (`<USER>`, `USER`, `someone`, `runner`, `root`, ...) pass like in the other patterns; positive and negative
  cases are tested, and the whole tracked tree still scans clean. No option or command changed.
