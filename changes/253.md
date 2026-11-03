- Prefer installed CLIs with local login evidence in rubric routing, keyword runs and role `other`, with cached boolean
  doctor results and `routing.require_ready = true` by default. All-unknown candidates retain the existing fallback
  order with an explanation; `false` restores earlier readiness ordering. Credential contents are never read.
  File-existence evidence is stat'ed on every call; only doctor results use the quota refresh interval cache.
  Ordinary routing retains the existing fallback without login evidence and says "no login evidence for X, trying anyway".
  Role `other` instead uses the existing same-vendor, different-model review fallback when the builder has login
  evidence but eligible reviewers do not, explaining "reviewer vendor X: no login evidence → same-vendor other model".
  All-unknown discovery keeps its existing order, preserving the original role resolver contract.
- Limit named-target run/route refresh to its candidate and keyword route refresh to configured tier candidates,
  consider builder/other candidates for role `other`,
  and skip candidates lacking login evidence when a ready candidate exists. Add `quota.probe_timeout = 15`,
  stderr refresh progress and failure warnings; preserve refresh cooldowns, quota ordering and fallback options.
- Show three copyable examples and the project-scope hint on stderr when `ccx roles` is empty; keep JSON and
  nonempty output unchanged. No command or option was removed; the frozen CLI-surface test checks this.
- `other` is a role assignment, not a `--to` value: both `ccx run --to other` and `ccx route --to other` are rejected
  by the existing CLI parser. DSH uses the adapter's API-key presence signal; no credential-file format or
  login-status command is assumed.
