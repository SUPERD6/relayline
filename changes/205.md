- CI: a pull request runs Windows 3.11 + Ubuntu 3.13 and the package check on Ubuntu; a push to main (beyond
  docs), a version tag or a run by hand runs the full matrix (3 OS × 3.11–3.13, package on 3 OS); pushes to other
  branches no longer run (their PR does). Job names no longer carry the matrix's `full` flag, and a new `ci-ok` job
  passes only when every job passed, so branch protection can require that one check. Each main commit keeps its
  own full run (one concurrency group per commit). Pushes to main that touch only `skills/**/SKILL.md` now run.
- CONTRIBUTING (both languages): a test rule (time comes in as a `now` parameter, no written-out dates measured
  against a window, concurrency tested with a fixed order of events, assert on what happened, not how long it
  took; examples #193, #190) and who checks main's full run after a merge.
