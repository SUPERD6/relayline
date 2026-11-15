# Baseline-aware acceptance checks (experimental)

English · [中文](check-baseline.zh.md) · [Features](features.md)

Evidence level: **engineering check**, using fake agent CLIs and temporary local Git repositories.
Real-model evaluation and cost savings: **not run / Unknown**. No command or option is removed.

## Configuration

```toml
[check]
baseline = "off"  # default; optional: "on_fail"
sensitivity = "off"  # experimental; optional: "warn", "escalate"
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
| Complete failure lists; no new cases | `kind=check_baseline_failed`; no check repair or escalation (except the sensitivity opt-in below), no automatic task-failure learning; the lead fixes the baseline before accepting |
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
that run. Merged batch pieces also use the group's dispatch snapshot, including the original group's snapshot
after a review fix round. With sensitivity enabled, passing pieces also run a baseline; each distinct command
is cached once. With baseline failure comparison enabled,
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

## Check sensitivity (experimental, default off)

An existing suite can pass before and after a change without testing the new requirement. Enable
`ccx config set check.sensitivity warn` to compare acceptance with the same clean dispatch-time tree even when
the worker's check passes. `off` preserves the existing behavior: no extra baseline for a passing check.
Without a supplied acceptance check, sensitivity does not capture a tree or run another command.
This uses the snapshot, isolated clone and per-command cache above; retries do not rerun the same baseline.

| `check.sensitivity` | Behavior |
|---|---|
| `off` (default) | Existing baseline/check policy, no sensitivity work |
| `warn` | Record sensitivity and tell the lead when the check did not verify the requirement; no retry-policy change |
| `escalate` | Also treat an insensitive cheap-first result as unverified and advance once to the originally requested rung, within existing pin, budget, authentication and escalation limits |

`--no-escalate` keeps the original starting rung and returns the insensitive hint in `needs_lead`.
Outside cheap-first dispatch, `escalate` has the same behavior as `warn`. A sensitive or unknown result does not
create an extra escalation. Self-written failing checks retain the existing independence guard. With
`baseline = "on_fail"`, existing failed-check policy remains intact except that an insensitive cheap first
attempt may use the authorized sensitivity escalation. Restore with `ccx config set check.sensitivity off`.
`warn` alone (with `baseline = "off"`) retains parallel review/check startup; `on_fail` and `escalate` defer review
until the check finishes. Under `escalate`, a passing but unverified cheap attempt is recorded as
`check_unverified`; `check_failed` remains reserved for failed checks. Among attempts eligible for provisional
learning, each non-final attempt already counts as unsuccessful; changing this label does not change that rule. It records missing
verification, not proof that the implementation is wrong.

The run and compact receipt add `check.sensitivity`:

| Value | Evidence |
|---|---|
| `sensitive` | Baseline fails and acceptance passes; with complete parsed pytest failure sets, at least one baseline failure no longer fails (`fixed_cases`) |
| `insensitive` | Both baseline and acceptance pass, or complete before/after failure sets are identical |
| `unknown` | Missing/unavailable baseline, broken/timed-out check, incomparable failed output, pass-to-fail regression, or only additional failing cases without an identified improvement |

Complete failure lists use the existing pytest parser. If those lists cannot be parsed, a baseline test failure
(exit 1) followed by a pass establishes sensitivity; collection/environment errors with other exit codes remain
unknown. Two nonzero exits do not establish sensitivity. `fixed_cases` is omitted when case evidence
is unavailable. Current check records always include the exit code; legacy summary-only comparisons without
that field retain the overall fail-to-pass fallback. Disappearing failures do not prove coverage or independence:
skipped, deselected, removed or
rewritten tests need lead inspection, and the existing test-basis labels still apply. A sensitive check does not
prove the task is correct. Sensitivity also requires the baseline import probe for passing Python commands;
missing probe evidence or imports from the modified source make sensitivity unknown, without changing the
legacy baseline verdict. Non-Python commands or Python `-I`/`-S` can therefore remain unknown.
When the check imports pytest or dependencies from a project-local `.venv`, those imports resolve inside the
source repository and the import-origin guard always makes sensitivity `unknown`. Use an interpreter/dependencies
outside that repository for comparison.

For `insensitive`, `hint` and `needs_lead` explain whether the check already passed before the change or the
same cases still fail, and ask for a test of the new requirement. Check exit codes, `passed` and existing `kind`
meanings are preserved. A pass-to-fail regression retains the normal failure output and retry path. Both passing
insensitive results and authorized identical-failure retries ask the stronger worker to verify the task text.
For identical failures, the prompt explicitly says they existed before the change and lists only their case IDs;
it does not send the raw failure tail or use focused "fix only the failures" instructions. The lead's request
to add a requirement test stays in the lead receipt, not in the worker retry prompt.
`run.json.checks` retains sensitivity for every actual attempt, and the final
`run.json.check` / `ccx show` receipt exposes it. With this setting enabled, top-level `check_sensitivity`
defaults to `unknown` when no check ran, and `check_sensitivity_mode` records the mode.
`check.sensitivity_seconds` records the extra baseline wall time, including clone, execution and cleanup
(zero when a cached baseline is reused); `check_baseline_seconds` exposes the total in run and ledger, and in
the receipt only with sensitivity enabled. The one-line view includes only the sensitivity mode/value and total
baseline seconds; full baseline details and import origins remain in `ccx show` / `run.json`.
No model call is made by baseline comparison. This feature has engineering checks only; real-model accuracy,
cost and time effects remain **not run / Unknown**.
