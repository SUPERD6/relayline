# Experimental cheap-first dispatch

[中文](dispatch.zh.md)

`ccx config set dispatch.cheap_first true` opts in; `[dispatch] cheap_first = false`
is shipped. Only engineering checks have run. Savings and task accuracy are **Unknown**.

A write task with a caller-supplied independent `--check` may start at its agent's
configured T1 rung, then return to the ordinary starting rung if acceptance identifies
a new failure. No task-size, interface-risk or task-wording filter is added. Without
`--check`, the existing path is unchanged. Explicit model pins, role model pins,
resumes and `--no-escalate` retain their existing choices. No command or option is removed.
Only recognized direct pytest/unittest commands qualify for cheap-first dispatch.
Opaque scripts, pipelines and commands whose exit status may mask the check keep
the ordinary route, even when their output resembles pytest.

The caller must supply an independent acceptance command, rather than asking the
worker to invent its own tests. A cheap attempt whose passing check covers tests
written, edited or extended by this run is self-checked and climbs once, including
mixed suites containing untouched tests. A failing self-written check retains the
existing retry policy. It does not
prove the independence or completeness of an arbitrary shell command.
Missing snapshots, namechecks, unavailable/partial coverage and inspection errors
also cannot establish independence: a passing cheap attempt climbs once in those
cases. The ordinary dispatch path retains its existing treatment of unknown bases.

The opt-in path uses [`check.baseline = "on_fail"`](check-baseline.md) for that run,
even when the hub keeps baseline checking off. A baseline-only failure never
escalates. A passing baseline permits the check's failure output; otherwise only
identified new failing cases are sent to the stronger attempt when comparison is known.
An unavailable or ambiguous baseline stays Unknown and permits the ordinary retry
with the current failure output; it is not relabeled as a confirmed new failure. Existing
check verdicts and exit codes retain their meanings. Environment failures do not
trigger task escalation; existing quota fallback and model substitution remain available.
Review selection and repair limits remain unchanged.
CLI execution errors and timeouts may advance to the next authorized rung, even
when no resumable session was produced. Authentication failures and stop/budget
conditions retain their existing behavior.

`run.json`, `ccx show` and the ledger gain a `dispatch` object. It records the actual
first rung and originally selected rung, `attempted`, `escalated`, `escalation_rate`,
`first_usd`, `escalation_usd` and `recovery_usd` (quota/model recovery). Rates aggregate
as sum(escalated) / sum(attempted), rather than averaging rounded rates. Costs are
API-equivalent USD for worker attempts; existing total costs additionally retain
review and repair expenses. Missing worker prices remain null, not zero.

## Six-task evaluation plan

From any directory, use the absolute path to `scripts/eval/p4_long_session.py`:

```text
python scripts/eval/p4_long_session.py --dry-run --split dispatch --arms self,ccxcheapfirst --budget 6.5 --lead-budget .25 --child-budget .5 --tag dispatch-r1
```

No model is called by dry-run. The dispatch split reuses the first six validated P4
tasks in frozen order (four dev and two final); these are previously used tasks,
not an unseen final set. Each task gets a fresh one-task lead session in each arm,
with alternating arm order. Only the candidate hub enables cheap-first dispatch.
The candidate uses the existing independent acceptance command and keeps review enabled.

The bounded plan allows one round, only `self,ccxcheapfirst`, and a budget of at most
$8. The example's operational envelope is $7.25: $6.50 step budget plus $0.25 lead and
$0.50 child allowances. `--run` refuses an envelope above $8. This is an operational
step bound, not an absolute provider billing guarantee; a running step is not cut off.
Unknown accounting stops the experiment. An observed dispatch escalation rate
strictly above 30% stops before the next task, even if only one candidate has run.
Missing dispatch evidence also stops it. Failures and interruptions remain in the ledger.

Summary adds `dispatch` with phase costs, numerator/denominator, and both all-row and
clean-row comparisons. Existing P4 summary fields are preserved. A complete six-pair
comparison requires no reduction in correct tasks, total cost at most 0.8 times self,
and median wall time at most twice self; incomplete evidence is Unknown. Exceeding
the early-stop threshold leaves an incomplete comparison, not a passing result.
Before any paid run, the lead must commit a preregistration and exact code pin under
the [engineering standards](engineering-standards.md). Nothing here authorizes that run.
