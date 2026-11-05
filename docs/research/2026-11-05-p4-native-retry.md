# P4 native checkout, focused repair and repeated checks

[中文](2026-11-05-p4-native-retry.zh.md)

Evidence: **engineering check**; no new model calls. New flags default off. Existing
commands, options, JSON meanings, exit codes and acceptance rules are retained.
P5 retains its existing native checkout policy.

`p4_long_session.py --native-checkout` now applies the existing native Git checkout
policy to any split, including the frozen eight-task `final` split. Windows uses
CRLF where Git attributes permit it; explicit LF attributes are respected. This
policy is shared by the live repository, hidden scoring and the pre-model audit.
Before preflight/models, each untouched parent must pass the full acceptance command
(exit 0), its hidden tests must fail (exit 1 or 2), and the reference hidden tests
must pass (exit 0). Any exclusion stops execution. Nothing replaces a frozen task.

Offline audit, without models or a Codex home:

```text
python /path/to/repo/scripts/eval/p4_long_session.py --validate-native --split final --native-checkout --ext-cache CACHE --ext-python PYTHON --audit-output AUDIT.json
```

The audit records each baseline, hidden parent/reference result and checkout EOL
counts. Exit 0 means every selected task passed this contract; exit 1 records an
exclusion. The final-eight audit on the original Git cache is **not run / Unknown**:
the original cache location and external interpreter were not supplied to this
worktree. Tests with disposable repositories verify the gate and matching native
checkout, but do not establish eligibility of those eight real tasks.

`defaults.focused_retry` already exists and remains false in shipped defaults.
When a child says done/partial but ccx's check fails, it can resume the same provider
session on the next existing rung, carrying the failed command, exit and up to
about 2,000 output characters, with instructions to fix only the failure. It does
not add a rung or change escalation/acceptance. `--focused-retry` opts the isolated
episode hubs into that existing setting; it affects both delegated arms. The self
arm does not delegate. Plan/results record the requested flag. No configuration key
was added and no user configuration is changed.

Three-arm dry-run (24 scheduled attempts, no model calls):

```text
python /path/to/repo/scripts/eval/p4_long_session.py --dry-run --split final --native-checkout --focused-retry --arms self,ccxlong,ccxlongcheap --tag p4native --out RESULTS.jsonl
```

The outside-repository dry-run exited 0 with eight tasks and a **$9.603** historical
planning proxy (self $4.365, ccxlong $2.619, ccxlongcheap $2.619), not observed spend.
Cheap uses the ordinary workflow proxy; its actual cost remains Unknown.
The six related test files passed **72 tests**. The full repository suite was not run.

These flags change separate factors; freeze them in the preregistration rather
than attributing a combined result to either change alone. A real run still needs
the existing explicit `--run --budget`, source pin, external cache/interpreter and
dedicated model home. Dry-run does not establish baseline eligibility or arm quality.

## Repeated checks: defer reuse

`delegate.py` already reuses its own in-loop `early_check` for the same attempt at
final acceptance. It independently runs acceptance after the child's commands.
`check_baseline.Checks` also caches the original baseline per command; it does not
trust a child's reported test result.

[Historical P4 event replay](data/p4-check-overlap.json) covers eight ccxlong final
units (1,774.921 seconds of delegated wall time), source pin recorded in the data.
Seven candidate command/exit pairs match the final controller receipt; **all seven
failed**, so there is no observed passing candidate for a success-reuse path.
Their child pytest summaries report **5.46 seconds**
in total. This is test execution time reported by pytest, **not saved wall time**:
it omits Python/process startup. All eight controller
receipts omit check duration, and events do not bind checks to before/after file
trees. Actual avoidable seconds are **Unknown**; proven reusable seconds are zero.
This replay does not measure current code or a new optimization.

Decision: retain independent acceptance. The available evidence does not justify
a new cache that must bind exact command, exit status, environment and file tree.
No check-skipping behavior or default was introduced.

Reproduce from explicit retained result/artifact inputs, from any directory:

```text
python /path/to/repo/scripts/eval/p4_check_overlap.py --results P4FINAL.jsonl --artifacts-root ARTIFACT_RUN --out OVERLAP.json
```

The replay reads only the explicit lead and child event streams. It does not read
model homes, execute commands from logs, run tests or call models. Repeated receipts
are deduplicated by run id; candidate commands/exits are observations, not acceptance.
