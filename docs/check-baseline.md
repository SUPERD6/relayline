# Baseline-aware acceptance checks (experimental)

English · [中文](check-baseline.zh.md) · [Features](features.md)

Evidence level: **engineering check**, using fake agent CLIs and temporary local Git repositories.
Real-model evaluation and cost savings: **not run / Unknown**. No command or option is removed.

## Configuration

```toml
[check]
baseline = "off"  # default; optional: "on_fail"
```

Enable with `ccx config set check.baseline on_fail`; restore with `ccx config set check.baseline off`.
The default keeps the existing check verdicts, retry ladder and exit codes. Check logging adds fields in both modes.
The added default behavior writes stdout/stderr logs (at most 2 × 256 KiB per check) and adds `stdout_path`,
`stderr_path`, `stdout_truncated`, `stderr_truncated`, and `failed_cases`; compact receipts also add `headline`
by default. These are additive fields and output retention, including when `baseline = "off"`.

With `on_fail`, ccx records the clean Git HEAD and working subdirectory, and saves tracked files' actual bytes in
`check-baseline-start.zip` before starting the worker. A clean Git status alone does not distinguish normalized
LF/CRLF variants. This snapshot adds local disk/I/O overhead only when the feature is enabled. After the first
failed acceptance command it runs that same command once on an independent local clone of this pinned HEAD.
The source index, files, branch and worktree registry remain untouched. Effective `core.autocrlf`, `core.eol` and
`core.symlinks` settings carry into the clone. Its HEAD/index are set to the pinned commit and saved bytes are
restored without checkout hooks or smudge filters. The temporary clone is
removed in `finally`, including when checkout or execution fails. For a per-run acceptance command, review starts
only after a passing check in this mode, avoiding a review while baseline diagnosis runs.

## Outcomes

| Baseline / comparison | Result |
|---|---|
| Baseline passes | Existing failure/retry behavior |
| Complete failure lists; no new cases | `kind=check_baseline_failed`; no check repair or escalation, no automatic task-failure learning; the lead fixes the baseline before accepting |
| Complete failure lists; new cases | Existing retry ladder; retry prompts list only new case names; raw output remains in logs |
| Cannot compare | `baseline_comparison=Unknown`; retain exit codes and existing failure/retry behavior |

`check_baseline_failed`, like `check_failed`, reports `ok=true` and CLI exit code **0**: execution completed,
but acceptance failed. Scripts must inspect `kind`, `check.passed` and `check.baseline_comparison` rather than
accepting from the process exit code or `ok` alone.

Case comparison currently accepts complete pytest short-summary `FAILED` / `ERROR` node IDs, including parametrized
IDs. Counts must match the terminal failure/error totals. Interrupted output, collection failures, opaque output
and mismatched counts remain Unknown; equal nonzero exit codes alone never establish baseline-only failure.
Bracket pairs delimit parameter IDs, preserving embedded ` - `; unbalanced brackets remain Unknown.
Dirty/non-Git dispatch trees, submodules, symlinks, unavailable commits, checkout errors and cleanup errors also remain
Unknown. A command containing an absolute reference into the source tree is not rerun there as a baseline.
Baseline checks remove source-tree entries from `PYTHONPATH`. A startup probe records actual Python module
paths in `check_baseline.import_origins` (also in each `check_baselines` entry), including editable imports.
If a failing check imports from the source tree, or import evidence cannot be collected (for example a
non-Python command, `-I`/`-S`, or abrupt exit), the baseline is Unknown and cannot establish `baseline_only`.
Ignored dependencies and other external state are not copied; this is a clean Git baseline, not a reproduced
machine environment. Each explicit delegation/resume pins its own dispatch tree; a baseline is reused only within
that run. Merged batch pieces also use the group's dispatch snapshot, caching one baseline per distinct command;
baseline-only pieces get no check follow-up or spun-off run. A failing baseline does not prove the work is correct.

## Records and logs

`run.json.checks` retains every actual acceptance check; `run.json.check` still describes the final check.
Each check adds `stdout_path`, `stderr_path`, `stdout_truncated`, `stderr_truncated` and `failed_cases` (`null`
means Unknown). Each retained stdout/stderr file is capped at 256 KiB, keeping its beginning; the existing `tail`
field retains its previous meaning. Only complete parsed case lists are used for comparison, independent of log
truncation. Logs contain command output and should be treated like the existing run event/stderr logs.

`check_baseline_start` records the pinned start or the reason it is unavailable. `check_baselines` lists distinct
commands' baselines; `check_baseline` is the first baseline and contains
`status` (`Pass`, `Fail`, `Unknown`), the baseline check when available, and `seconds` including checkout, check
and cleanup. `check_baseline_seconds` records their total time in the run and ledger (the merge event for merged
pieces), separately
from existing `seconds` (agent attempt time). There is no model call or extra model charge. Queue items with
baseline-only failures become blocked, awaiting baseline repair rather than counting as completed tasks.
Failed cleanup records `cleanup_path`, marks the
baseline Unknown and leaves that isolated path for the lead to inspect; the source worktree is never removed.
The receipt exposes final log paths and the baseline record, and the one-line recap explains baseline-only stops.
