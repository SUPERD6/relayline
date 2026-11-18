- `ccx ab done` now writes size signals into its `selfrun` ledger row (#433): `estimate_files`,
  `estimate_minutes`, `band`, `coupling`, `clarity` (the tier plan's and the rubric's values from the `ccx run` that
  drew the sample), plus `route.rubric.{coupling,clarity}`, laid out where `scripts/eval/routing_calibration.py`
  (`signals_of`) reads them, so the do-it-yourself arm is no longer empty on those signals. Fields are added only
  when given or measured; samples opened earlier and runs without signals close as before. No new option, no output
  change beyond the added fields; `ccx ab done <id> --ok 1|0` is as it was.
