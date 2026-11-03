- Receipts attribute `agent` / `model` / `effort` to the final executor and retain the initial pick as
  `requested_agent` / `requested_model`; compact results and recaps name quota reassignments, budget stops and
  reviews that could not run, without reporting plain ok or changing command exit codes or `ok_self_checked`.
- Role runs retain auto-effort difficulty scores and rubric/keyword reasons in their receipts, route records and
  compact `ccx show`; old records remain readable. No commands, options or existing fields were removed
  (`tests/test_cli_surface.py` checks the command/option surface).
