- When the check and the review passed and nothing needs the lead, `ccx run`, `ccx resume`, `--bg --wait` and
  `ccx show <id> --wait` / `--any` hand the lead one JSON line (`"view": "line"`: summary, files, diffstat, check,
  recap) instead of the whole result (P0-11 item 3, `ccx/leadview.py`): the lead re-reads what it was handed on every
  later turn. On 129 passed runs of a real hub, 860 -> 509 bytes (median). Anything for the lead (a hint, needs_lead,
  a weak or unchanged-tree check, review issues, edited tests, open questions ...) keeps the whole result; `ccx show
  <id>` is always whole. Back to the whole result: `ccx config set output.lead full` (or `CCX_LEAD_VIEW=full`).
