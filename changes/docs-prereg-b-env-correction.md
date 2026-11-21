- Docs: add a 2026-11-21 correction to the round-2 preregistration change log
  (`docs/research/prereg/2026-11-16-round2.md` and `.zh.md`): the frozen `selection-env/pip-list-v3.json` is the pip
  list of the earlier prepare-v3 environment (no pytest, #442) and does not describe the B selection environment; the
  selection used the prepare-v4 environment, whose authority is the frozen `prepare-v4.json` (SHA-256 recorded by both
  selection runs; 905 distributions, pytest 9.1.1). B's development and formal runs use copies of that environment and
  cache, compared with `prepare-v4.json`'s pip list before every start. No frozen file or registered SHA-256 changes;
  written before any round-2 model result (#501).
