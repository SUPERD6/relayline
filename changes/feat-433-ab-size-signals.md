- `ccx ab done` now writes the same size signals into its `selfrun` ledger row as a delegated run's row carries
  (#433): `estimate_files`, `estimate_minutes`, `band`, `coupling`, `clarity` (the tier plan's and the rubric's
  values from the `ccx run` that drew the sample, plus `route.rubric.{coupling,clarity}` where
  `scripts/eval/routing_calibration.py` reads them), so the do-it-yourself arm is no longer empty on those signals.
  Fields are added only when given or measured; samples opened earlier and runs without signals close as before.
  No new option, no output change; `ccx ab done <id> --ok 1|0` is as it was.
