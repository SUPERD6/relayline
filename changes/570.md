- Relay: `ccx relay capture --check CMD` / `ccx relay continue --check CMD [--check-timeout-seconds N]` (#522). The
  packet gains a `check` field (`cmd`, `source`, `sha256`) that only an explicit `--check` can fill; after the new lead's
  process ends, ccx runs it in the same workspace with the ordinary check runner and writes `verification`
  `pass` / `fail` / `broken` plus `check_result` into the launch record and a `relay_check` row into the ledger. A
  `check` of unknown source, a hash that does not match, or a malformed value is refused and never run. Default off
  (no `--check` = unchanged, `verification` stays `not-run`); no command or option removed. `docs/relay.md` and
  `.zh.md` updated.
