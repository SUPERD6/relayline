- Relay (#525): checked codex-cli 0.164.0 and the Codex hooks reference (2026-11-26): there is no usage-limit hook, so a
  Codex session the person starts themselves is not covered (said in docs/relay*.md). A Codex session ccx itself
  launches (`ccx run --to codex`) that ends on a confirmed usage-limit refusal, with no fallback, now saves a relay
  packet (`source: codex`) and a `relay` field in the result for `ccx relay continue --to claude`. Off with
  `relay.enabled` (default false). The refusal wording is captured from the CLI's own log; the `exec --json` envelope is
  still Unknown. Fake-CLI tests only.
