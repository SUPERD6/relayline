- When the check passed, the review passed or did not run, and nothing needs the lead, `ccx run`, `ccx resume`, `--bg --wait` and
  `ccx show <id> --wait` / `--any` hand the lead one JSON line (`"view": "line"`: summary, files, diffstat, check,
  recap) instead of the whole result (P0-11 item 3, `ccx/leadview.py`): the lead re-reads what it was handed on every
  later turn. On 129 passed runs of a real hub, 860 -> 509 bytes (median). Anything for the lead (a hint, needs_lead,
  a weak, unchanged-tree or unknown-coverage check, review issues or notes, edited tests, open questions, a next
  step, an L2 merge or project answer ...) keeps the whole result; the line drops route (and its routing tip) and
  tokens; `ccx show
  <id>` is always whole. Back to the whole result: `ccx config set output.lead full` (or `CCX_LEAD_VIEW=full`).
- `ccx run` / `ccx resume` write a delegation's start and end (and a review fix round's) to the project's board
  themselves (`board.post_run`, P2-12), so `ccx board` / `ccx ui` show it without the UI open; only where the project
  has a board already or ignores `.ccx/`. The reviewer's run is not posted.
