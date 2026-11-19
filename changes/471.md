- strength_retest: an arm that must not get the answer has no answer-level file in its unit: the context off arm no
  longer gets the lead transcript (ccx never read it with `--context off`). Claude units' shared transcript folder
  (`<claude-home>/projects/ccx-strength-synthetic/`) is denied and audited for every unit; only an on unit's own
  transcript is not a hit. Every unit is kept from the rest of `--out` (the other `unit-*` folders, `manifest.json`,
  `results.jsonl`, `report.json`): any spelling of `--out` left after masking the unit's own folder is a path-audit
  hit, and Claude units get deny rules on the run files and the earlier units (a few `unit-NN*` globs). The dry run's
  `isolation` field lists each arm's answer-level files (`answer_files`) and the `--out` rules (`siblings`). (#467)
