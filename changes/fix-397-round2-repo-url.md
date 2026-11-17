- Evaluation (#397): `scripts/eval/round2_tasks.py repos` no longer takes a funding link
  (`github.com/sponsors/<user>`, and other GitHub paths that are not an owner) as a package's source repository; it
  uses the next real repository link (attrs, starlette, uvicorn, jsonschema, structlog and others were mapped to
  sponsor pages and then dropped as "not in --ext-cache"). A repository shared by several packages is kept once, at
  its best rank; later rows are excluded with "same repository as rank N (project)". `select` also walks a repository
  only once if an older list names it twice, so the same commit can no longer be accepted twice.
