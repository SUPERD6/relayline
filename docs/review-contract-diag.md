# Contract diagnostic (experimental)

English · [中文](review-contract-diag.zh.md)

`review.contract_diag = false` is the default. Opt in with
`python ccx.py config set review.contract_diag true`. A write run whose review is
enabled then adds a diagnostic before ordinary review. All commands, options,
existing JSON meanings, verdicts, exit codes and review defaults are retained.
This is an engineering check, not evidence of better review or task correctness.

## Process and evidence

The controller supplies only saved original words (when present), the assigned
task and pre-change Python interfaces. A fresh `python -I -S` process receives
those three strings over stdin in an empty temporary directory. Its fixed code
has no file-reading operations, model calls or tools; Python configuration,
credential variables, implementation, diffs, hidden tests, previous review and
shared context are not passed. It is trusted-code data isolation, not an OS
sandbox that could safely run an arbitrary model CLI or untrusted Python code.
The pre-change interface helper reads the saved Git base, not current source.

The supplied offline generator extracts paragraphs, preserving their words as
candidate expectations. Every extracted item is `unknown: true`: extraction
does not establish semantic expectations. A separate, explicit Claude semantic
adapter is available below. An independently authored frozen contract can
be provided to the offline script for later inspection. It cannot be generated
by simply pointing this process at an implementation.

Each behavior has `id`, `source`, `quote`, `expected`, `unknown`. The controller
validates references against each named source separately. Invalid references,
duplicate IDs, interface assumptions and missing inputs remain Unknown. Interface
context is not automatically a requirement. Input above 64,000 characters is
reported Unknown without silent truncation. Missing historical words cannot be
reconstructed. Semantic conflicts across different wording remain Unknown; the
extractive generator cannot settle them.

`review-contract.json` freezes sources, validated behaviors, gaps and generator
with a canonical SHA256 `contract_hash`; it is created exclusively, never
overwritten. Reuse verifies the hash and exact sources. The compact receipt adds
`contract_diagnostic`, `evidence_level`, `evidence_scope`, `covered_ids` and
`coverage_note` only when the diagnostic ran. Levels are:

| JSON value | Meaning |
|---|---|
| `independent_verified` | Passed unchanged external checks, or executed independent test review with a resolved verdict; scope is the reported test files |
| `self_checked` | A passed controller check marked entirely self-authored |
| `unverified` | Neither of the above has execution evidence |

A read-review pass does not upgrade self-checks. These labels describe executed
checks, not every behavior or the whole task. `covered_ids` stays empty until
behavior-to-executed-test mapping exists. A changed/partial/filtered/unknown test basis
does not establish independent verification. Existing verdict rules are unchanged.

## Historical offline diagnostic

Run from any directory, with explicit local archive and fresh output locations:

```text
python /path/to/relayline/scripts/eval/review_contract_diag.py --evidence /path/to/p2-r2-evidence --dry-run
python /path/to/relayline/scripts/eval/review_contract_diag.py --evidence /path/to/p2-r2-evidence --generate --out /path/to/new-output
```

The 15 known-wrong unit IDs are the historical development cohort in the
[R2 diagnostic](research/2026-11-05-p2-r2-diagnostics.md). They are not fresh samples.
The script reads each archived job and committed pristine stub (`HEAD` of the
reconstructed replay tree), never current implementation. Missing material keeps
the row and denominator. No clone, download, model invocation or hidden-test
execution occurs. `--dry-run` (also the default) creates nothing. `--generate`
freezes contracts before the controller reads the hidden-test oracle. Missing
task/interface/oracle evidence remains Unknown.

Default reservation is 15 × $0.50 = $7.50, against an absolute $8 maximum.
`--budget` and `--unit-reservation` validate finite positive numbers and refuse
reservations above the budget. This is reservation arithmetic, not a model price
quote: expected real-model spend is Unknown. Offline modes make zero model calls.

## Explicit semantic generation and defect mapping

```text
python /path/to/relayline/scripts/eval/review_contract_diag.py --evidence /path/to/p2-r2-evidence --generator claude --dry-run --budget 8
python /path/to/relayline/scripts/eval/review_contract_diag.py --evidence /path/to/p2-r2-evidence --generator claude --run --budget 8 --out /path/to/new-semantic-output
python /path/to/relayline/scripts/eval/review_contract_diag.py --evidence /path/to/p2-r2-evidence --generate --map-defects --hidden-root /path/to/pg3b-results-artifacts --out /path/to/new-mapping
```

Only `--run --generator claude --budget USD` permits model calls. The runtime
diagnostic remains offline by default; no new config keys or verdicts are added.
The semantic adapter uses an empty cwd, `--bare`, empty `--tools`, no MCP,
no slash commands, no setting sources and no session persistence. Flags were
checked against Claude Code **2.1.316 --help** on 2026-11-05. Only the three text
fields cross stdin; no implementation, hidden failures or oracle is supplied.
On Windows, a `.cmd`/`.bat` entry is resolved to a sibling native executable or
the standard npm `node_modules/@anthropic-ai/claude-code/cli.js` entry with Node.
Unknown shim layouts return Unknown without launching. This avoids `cmd.exe`
forwarding empty isolation arguments and quoted JSON; direct native/Node argv
retains the empty `--tools`/`--setting-sources` values. Fake-CLI checks cover
resolution and fail-closed behavior; an installed npm shim has not been run.
`--bare` requires explicit API authentication in the environment; the adapter
does not discover/copy client credentials or homes. This restricts model tools,
not the OS privileges of the trusted CLI. Other CLI versions remain unverified.

Each call gets `--max-budget-usd` equal to its reservation. Calls are serial;
an unknown cost retains the full reservation and stops later calls. Known
overspend also stops. Costs include failed calls; unknown amounts are null,
with `known_spent_usd` and `charged_usd` reported separately. Provider enforcement
can overshoot a single in-flight request; these reservations are not a billing
guarantee. This path has fake-CLI engineering checks only, no model-quality result.

`--map-defects` reads only `hidden-pytest.txt` files under the explicit hidden
root, after contracts are frozen. It joins pytest node IDs to assertion lines
and writes `oracle-template.json` plus `human-review.md`. All rows start with
`confirmed: false`, empty requirements, SHA256 provenance and Unknown coverage.
The human must fill source quotes and expected fragments before using the
template as `--oracle`; extraction never auto-confirms a defect or asks the
generator to judge its own coverage. Missing/unparseable failures stay Unknown.

For deterministic coverage inspection, pass `--contracts DIR --oracle table.json
--hidden-root DIR` alongside `--generate`. Contracts must already have a valid
hash and identical sources. A controller-only, human-reviewed oracle maps each
unit key to rules like this synthetic example:

```json
{"p2-1": [{"hidden_test": "test_integer", "hidden_artifact": "failure.txt",
  "sha256": "<SHA256 of the hidden-test artifact>", "confirmed": true,
  "requirements": [{"source": "task", "quote": "Return 2.",
                    "expected_contains": ["integer", "2"]}]}]}
```

The human must establish the hidden-test defect and required behavior before
using the table; the script only checks the artifact hash and literal mapping.
Every rule must match a valid, non-Unknown behavior with the same source/quote
and all expected fragments. It does not use a second model as judge. Missing or
unconfirmed evidence, unresolved expectations and zero rules produce Unknown.
This is literal checklist coverage, not a claim that an actual reviewer caught a
defect. The report retains all 15 rows, coverage counts, Unknown counts and an
Unknown efficacy gate. It cannot enable this feature or revise historical scores.

## Verification boundary

Synthetic regression tests and fake CLI wiring cover process inputs, citation
validation, immutable hashing, evidence grading, deterministic oracle matching,
budget validation and invocation from outside the repository. Real-model quality,
cross-platform runtime and CI require separate verification. The historical
archive does not contain a confirmed human table in this task; no new catch rate
is reported.
