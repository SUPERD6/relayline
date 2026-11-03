- Add a Today line to `ccx ui`: recorded delegation spend in API-equivalent dollars and subscription quota units,
  vendor quota use, and runs waiting for the person, with links to details; keep the weekly aggregate.
- Show budget stops, review errors and quota substitutions in run lists and receipts. Add read-only `/api/quota`
  with reading timestamps, freshness, stale/Unknown states and probe failures; never probe from the page.
  Model-unavailable substitutions on the same agent do not receive a quota label; explicit reasons take priority.
- Send role-button tasks as structured JSON, preserving multiline text as one argv argument. Show and switch
  read/write mode in a fresh preview, reuse edit-verb inference for unconfigured roles, and retain I1 safeguards.
  Editing a role-button draft clears its role selection so subsequent command text uses command preview again.
  No command, option or existing endpoint was removed; HTTP regressions cover the existing and structured paths.
