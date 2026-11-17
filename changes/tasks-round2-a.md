- Evaluation (#375, A part): round 2's A1/A2 task set, frozen for `strength_retest.py --tasks`:
  `docs/research/data/round2-tasks/a1.json` (48 settled + 8 neutral), `a2.json` (48 memory tasks) and the
  development files `a1-dev.json` / `a2-dev.json` (4 each, written and committed first). Every task carries its
  reference and a "naive" implementation (repository default or the dropped option). `scripts/eval/round2_a_tasks.py`
  builds the files from `scripts/eval/round2_a/` and checks them offline (hidden tests fail on start, pass on the
  reference, the naive version fails a test of every convention, trace table complete, the A1 settle text reaches
  the `--context on` attachment whole), runs the leak/similarity rule and writes the SHA-256 manifest. No model was
  called. `.gitattributes` keeps these JSON files LF, because `--tasks-sha256` hashes the raw bytes.
