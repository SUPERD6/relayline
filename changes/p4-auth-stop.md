- Evaluation (#509): `scripts/eval/p4_long_session.py` now treats an auth or quota failure as an environment error
  instead of an unknown cost. When the lead's error result or stderr (`Failed to authenticate`, `OAuth session
  expired`, 401, usage limit / quota) or a sub-agent's ccx receipt (kind `auth` / `quota`) says the login or the
  allowance stopped the work, the row is `environment_error` with `env_stop` set, `usd` is the amount actually
  spent (usually 0, not the reservation), and the whole group stops at once with `stop_reason` `auth` (previously
  three failed rows were each charged the $1.5 reservation and the run ended as `budget`). A normal result is never
  scanned, so a model mentioning 401 in its text is not a stop. New opt-in `--check-login` refuses to start with
  `--run` unless `claude auth status` reports the lead's login (flags mode: the default Claude home) as valid; it
  reads no credential file. No command or option was removed; default behaviour without a failure is unchanged.
