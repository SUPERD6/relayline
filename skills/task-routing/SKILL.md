---
name: task-routing
description: Choose a model/effort or compare self versus delegation when the user requests that choice, or before an already-authorized delegation. A general request to save tokens does not trigger cost estimation or delegation.
---

# Task routing

Compare only models and tools actually available and allowed for this task. Routing is advice,
not permission to start another agent. Ordinary work stays with the current agent when no
model choice is needed. Method and assumptions: [references/method.md](references/method.md).

## When a comparison affects the decision

Use `scripts/task_routing.py` (Python 3.11+, stdlib). Describe what is known:

| Flag | Values |
|---|---|
| `--files` | expected files touched |
| `--coupling` | `one`, `cross`, `system` |
| `--clarity` | `spec`, `goal`, `unknown` |
| `--risk` | `low`, `visible`, `critical` |
| `--novelty` | `pattern`, `new` |

```text
python scripts/task_routing.py route --files 3 --coupling cross --clarity goal --risk low --novelty pattern
```

Use `--not-verifiable` if available checks cannot establish success; it disables cheap-first
escalation. A check made only of tests the sub-agent writes itself does not establish success: a passing own test
is not a done task (ccx labels such a run `ok_self_checked`). Give the task a check on existing tests, or accept by
holding the result against the task text; otherwise treat it as not verifiable. Add `--lead`, `--ctx-tokens`, `--lead-ctx` (your conversation's size: each of your turns re-reads it;
ccx reads it by itself) and `--remaining-turns` when comparing continuation with delegation; an unrequested
delegation offer is `ccx propose` (agent-delegate section 0). `--agents` restricts providers; `--explain` shows
alternatives. Judging the tier yourself (`ccx run --tier`): agent-delegate's `references/rubric.md`.
`--agents codex,claude,deepseek` adds DeepSeek, which costs real money per token. There is no quota threshold: its
money competes with the subscriptions' quota at a shadow price that rises as quota runs short (from 60% used), so
it wins more often then; its `daily_usd` cap still applies (agent-delegate's `references/three-way.md`).
Consult `--help` only for needed unfamiliar options.

The output's probabilities and dollar costs are estimates, not measured guarantees or
subscription quota predictions. Inspect `calibration`, `stale`, and `new_models_without_prior`;
unverified priors must stay labelled as such. Verify current official prices only when using
stale prices to make a cost decision, not for every ordinary task.

## Tiers (whole workflow)

`--tradeoff` is also the tier: who does each task, sized from your brief plus `--minutes` and `--files`
(`ccx propose`, or `scripts/task_routing.py tier`). Any one of files, minutes or brief length reaching a band is
enough; with neither `--minutes` nor `--files` the size counts as uncertain. Thresholds are provisional
(`config/tiers.toml [policy.*]` in ccx).

| Tier | Who does it |
|---|---|
| `save` | everything delegated through ccx (`ccx2`); you accept by check + review |
| `balanced` | small/medium yourself, large to `ccx2`; uncertain size and state-machine/resume-type tasks yourself |
| `fast` | everything yourself |
| `cheapest` | `direct`: ccx with no acceptance by you; tell the person the result may be wrong |

Only the person picks a tier, in their own settings: `ccx config set policy.picked <tier>` (`none` = off,
shipped). Then `ccx propose` (with no `--tradeoff`, or that same tier) pre-authorises what the tier delegates:
`authorized: true` with `worth_offering: true`; tell the person its `say` line and run its `next` (it picks the
delegated part's models like save), whose run skips the random A/B self-run. A project's autonomy level (L0/L1)
still stops before edits, and the answer is logged as the tier's, not as the person's yes. Never set
`policy.picked` yourself. A `--tradeoff` you pass authorises nothing: it is a model pick, the offer-first rule
stays (agent-delegate section 0), A/B and trials are unchanged, and the tier plan is only shown. If the person
names a tier in the conversation, that is their say for the pieces it delegates: run those with an ordinary
`ccx run` (an approved handoff). `cheapest` run through you still costs your own turns; only a script or CI calling
`ccx run` itself skips the lead. A `ccx run --tradeoff balanced|fast` you start yourself picks that tier's models;
`policy.picked` changes who does a task, not the models (a run without `--tradeoff` picks them as before). A
pre-authorised proposal covers one run of that task at the size you proposed: a second run with its id, or a
smaller one, is refused.
The default tier stays `save` until a confirmation run decides.

**Delegation off** (`[routing] mode = "off"`, `ccx config set routing.mode off`; `auto` as shipped): `ccx route` /
`ccx propose` answer `do-it-yourself` with `routing_mode: "off"` (the pick is still shown; a `choice` keeps its
`recommend_before`), over a picked tier and `small_self`; `ccx run` / `batch` / `q run` / `q resume` / `way`
refuse without `--force`. `ccx run --mode read` (a cross-vendor review or second opinion), `ccx ask`, `ccx discuss`,
memory, the board and `ccx resume` of a run already started are unchanged.

**Small tasks yourself** (`routing.small_self`, off as shipped; the person turns it on): with no tier picked,
`ccx route` / `ccx propose` advise `do-it-yourself` when doing the task yourself costs less than delegating's fixed
cost. By `small_self_by = "files"` (default): at most `small_self_files` (1) source files. By `"cost"`
(experimental): requests (`--requests`, else 2 + 1.5 per `--files`, else per file the
brief names) x what each re-reads (your conversation, `--lead-ctx` or read as `ccx lead` does, else 25k) at your
model's price, plus the files written into the cache, against `small_self_overhead_usd` ($0.035: the pg1 median of
the lead's own share of a delegation on a fresh Sonnet conversation, scaled to your model and plus what your longer
conversation adds to its ~3 requests); `small_self.self_cost` shows both. With the shipped constants it comes to
about one file on any model and context; `--requests` and big file reads move it. `--minutes` does not gate it. Not when the person picked a tier, `--needs` asks for what only ccx gives, your context reaches
`lead_ctx_large`, or your quota reaches `small_self_quota` (0.9) (a lead with no price is priced on Sonnet):
`small_self.why` says which. The rung, ladder and tier plan are shown as before; `ccx run` is unchanged. Basis:
pg1 put 82 % of a delegation's spend on the lead's side, so the question is whether doing it yourself is dear,
not how hard the task is (provisional until a measured round).

**Lead model by task** (off unless the person runs `ccx config set lead.model_by_task on`): a running
conversation keeps its model (switching drops its cache). From the same b, `ccx route` / `ccx propose` add
`new_lead` (a new conversation's model: `[lead_by_task]` easy model up to `easy_max_b`, else yours: start it on
the model you normally run) and, only when `choice` did not recommend a built-in sub-agent, `builtin_model` (a
fallback for your built-in sub-agent, easy band only); `ccx fresh` / `ccx handoff` take `--minutes` and use it.

## Act within the task's scope

Use the estimate alongside checkability, startup/handoff cost and actual availability.
A `split` recommendation does not automatically trigger multiple skills or agents. If a
verified failure justifies an authorized escalation, resume the same session where supported.
When authorization or available models prevent the suggested choice, explain the constraint
and use an allowed option.

Record only an actually checked outcome; ccx already records its own runs:

```text
python scripts/task_routing.py record --rung codex:gpt-6.1-sol:medium --b 4 --ok 1
```

No new model run is needed merely to calibrate the estimator. Optional `--cost-usd` records
measured cost; without real measurements, retain the uncertainty.
