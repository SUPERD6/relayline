- Evaluation (#397): `scripts/eval/round2_tasks.py repos` no longer takes a funding link
  (`github.com/sponsors/<user>`, and other known GitHub paths that are not an owner) as a package's source
  repository; it uses the next real repository link. A repository shared by several packages is kept once, at its
  best rank (identity: `owner/name` case-folded, so same-named repositories of different owners stay separate);
  later rows are excluded with "same repository as rank N (project)". `select` also walks a repository only once
  if an older list names it twice, so the same commit can no longer be accepted twice. This changes the round-2
  B/C repository list and order: on the 2026-11-01 snapshot (top 300) 15 high-ranked packages (attrs, starlette,
  uvicorn, jsonschema, referencing, structlog, virtualenv, authlib, pydantic-settings, hatchling, watchfiles,
  griffe, ...) now point to their real repositories, 13 duplicate rows are dropped and one package whose only
  GitHub link was a sponsor page has no source any more (kept 264 -> 250). No task set
  had been frozen from the old list. The `--ext-cache` key is still the repository name only (#400).
