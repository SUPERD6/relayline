# P0-13: one-round discussion before implementation — preregistration

[中文](2026-11-03-p13-discuss-prereg.zh.md)

Status: script and protocol prepared; **no paid experiment authorized or run by this change**.
The lead may execute the commands below only after the person explicitly approves the real measurement.
Dry-run and fake checks establish wiring, not an effect on correctness.

## Hypothesis and fixed treatment

A short discussion among three vendors may improve correctness on design tasks enough to justify its cost.
The experimental unit is one task; the two arms form a pair from fresh copies of the same historical parent.
Six tasks × two arms × one round = 12 implementation units, serially executed. The first arm alternates
by the task order below (three pairs each way). There is no outcome-based task selection, retry or replacement.

| Arm | Protocol |
| --- | --- |
| `nodiscuss` | A fresh Claude `sonnet`, effort `medium`, Bash-only lead dispatches exactly one `ccx run`. |
| `discuss` | The script first runs `ccx discuss --with codex,claude,deepseek --rounds 1 --tier T1`; the judge's structured result is appended after the unchanged original brief. The same fresh lead then dispatches exactly the same `ccx run` configuration. |

Both arms use a Codex `gpt-6-luna`, effort `low`, write-mode worker. Reviews, escalation, fallback, worker
sub-agents, worktrees, shared conversation attachment and A/B sampling are explicitly disabled. The lead may
only dispatch the supplied command, wait and report; it cannot inspect, edit, retry or resume. Its input does
not receive the arm name or discussion separately; the worker receives the brief file. The discussion roles
are Codex proposer, Claude critic and DeepSeek judge (the `deepseek` provider through the Claude adapter).
This uses the existing provider configuration and a key supplied by the person; the script never reads or
copies credentials. Each arm gets fresh task, hub, temporary files and agent settings via shared preflight.
The participant order and the T1 tiers are fixed, not auto-selected from outcomes.

One discussion round means proposer, critic and judge; the existing command may make a format-repair request
in the same round. Such requests and their cost remain in the record. An unfinished/unparsed discussion,
missing recommendation or a lead that dispatches the wrong number of runs is a protocol failure, never a
successful control unit. Unresolved disagreement is retained in the attached result, not treated as failure.

## Registered tasks

All six are existing `scripts/eval/tasks_r5.py` tasks, also published in `bench/tasks/r5/`.
They were selected from their briefs, before this measurement, for interface, data-schema or cross-module
coordination work. No new benchmark question is added. The repository archive at each commit's parent is the
starting point; the commit's original acceptance-test files are supplied only during scoring, using r5's
existing preparation and scoring helpers. Git history containing these commits must be available locally.

| Order | Task | Reference commit | Design reason |
| --- | --- | --- | --- |
| 1 | `q-killed-spend` | `8887d6d` | Interrupted-run state, exactly-once ledger attribution and queue cost must agree. |
| 2 | `q-resume-session` | `6cdae1e` | Queue recovery reconnects existing run/session identities and distinguishes finished work. |
| 3 | `projects-refresh` | `2978690` | A refresh API, detached process and scan guard coordinate with session startup. |
| 4 | `dsh-archive` | `cae823e` | Atomic archive data updates coordinate archive, restore and resume interfaces. |
| 5 | `quota-stop-log` | `4b4eb2f` | An evidence schema connects quota detection, attempt recording and CLI reporting. |
| 6 | `mem-report` | `f223125` | A usage schema and report API connect memory producers, consumers and the CLI. |

The selection covers six tasks (shortfall: zero). Existing development-set tasks may already be familiar to
the models or maintainers. This is a small development-set comparison, not an unseen-benchmark claim.

## Outcomes, accounting and decision rule

Correctness is the original hidden acceptance command's exit status, scored outside the agents with r5's
isolated pytest environment. A normal hidden-test failure counts as wrong, not as a discarded trial.
Rows retain `ok`, `pytest`, failures, protocol evidence, timestamps, CLI/config/task fingerprint, `audit`,
`leftovers` and `env_clean`. Protocol/infrastructure failures are recorded; they make the registered decision
Unknown. No unit is silently repeated under the same tag. Reusing a tag or work directory is refused.

Report per arm: hidden-test successes / trials, total API-equivalent USD, USD per success (all included units'
cost divided by successes, including costs of wrong implementations), wall-clock seconds, lead-side tokens
(Sonnet input + cache read + cache creation + output, summed over unique messages), and lead USD. Discussion
USD and discussion wall time are shown separately and are also included in total USD / total wall time.
Worker spend is retained separately. A missing price/usage is `null`, never silently imputed as zero.
Unit wall time includes preparation and hidden scoring; discussion wall time covers the discussion command.
The shared preflight canaries are outside the arm units; their $0.04 planning allowance is separate and counted
against the run's soft budget, not attributed to one arm's cost per success. This allowance is not a measured
canary bill. Raw preflight evidence remains in `preflight.json`.

The formal rule uses exactly one tag containing all six complete clean pairs from round 1, with no duplicate,
missing, protocol-failed or unclean unit. Discussion is **Useful** only when both conditions hold:

1. `discuss` solves at least two more tasks than `nodiscuss` (success-rate difference at least 2/6).
2. `discuss` USD per success is at most 1.5 × `nodiscuss` USD per success.

If the full eligible comparison is available and either condition fails, record **Negative**. If coverage,
protocol, environment or accounting is insufficient, record **Unknown**. If either arm has zero successes,
its cost per success is undefined and the joint rule is Unknown; do not divide by zero or invent a baseline.
`summary --include-unclean` provides descriptive totals only; it cannot turn unclean evidence into a positive
decision. Summaries spanning multiple tags are Unknown; use `--tag` for the preregistered run. These are
practical screening thresholds, not a significance test or proof of a general causal effect.

## Planning cost, execution and artifacts

The fixed planning allowances are $0.025 per lead, $0.06 per implementation worker, $0.15 per discussion and
$0.04 for preflight: 12 × ($0.025 + $0.06) + 6 × $0.15 + $0.04 = **$1.96**. These are explicit rough allowances,
not empirical estimates or current price quotes. Format repairs, long implementations and overhead may exceed
them. `--budget 2` checks cumulative known cost between units; an in-flight request may exceed it. If the budget
stops before twelve units, report Unknown and retain all rows. Each lead has a separate $0.10 CLI budget.

From the checkout root (the dry-run itself also works from another directory using an absolute script path):

```powershell
python scripts/eval/p13_discuss.py --dry-run
```

**After approval only**, with `CCX_EVAL_CODEX_HOME` already naming the dedicated logged-in evaluation home
and the DeepSeek provider key supplied in the environment, the lead can copy this command:

```powershell
python scripts/eval/p13_discuss.py run --execute --tag p13-r1 --wait-quiet 30 --budget 2
python scripts/eval/p13_discuss.py summary --tag p13-r1
```

Alternatively pass `--codex-home <eval-home>` explicitly. Record the exact approved command, checkout commit,
CLI versions and environment before starting. This change does not execute or approve these commands.
`--wait-quiet` reuses r5's pre-start and between-unit quiet checks: it never authorizes running on a busy
machine. Shared `run_checks` enables both Claude isolation and Codex shell canaries. `--force-unclean` may
continue past a failed preflight but every row stays unclean and cannot satisfy the rule. Interference seen
during a unit remains recorded even if the machine becomes quiet later. Environment and version drift are
checked between units. `--tasks` exists only for smoke subsets; fewer than six pairs cannot satisfy the rule.

Default results: `<main-checkout>/.ccx/eval/p13/p13-results.jsonl`, with an append-only `p13-run.log` ending in
`exit=<code>`. Worktree invocations resolve the main checkout from Git metadata. Work files default to the
system temporary directory under `p13-<tag>`; streams, discussion JSON and both arms' hub evidence are retained
there, separately by task/arm; fresh task copies are removed after each unit. Use `--workdir` and `--out` for
explicit locations. There is no background launcher. Script execution is serial (`jobs=1`).

## Limits and work not done

One round, six paired tasks, one lead/worker configuration, one participant order and a shared evaluation /
development machine limit interpretation. Quiet checks and audits record isolation and contention; they do
not create a dedicated machine or eliminate model stochasticity, cache effects or training-data familiarity.
The discussion arm adds calls, context and elapsed time together, so a difference cannot isolate which of
those mechanisms helped. No statistical significance, cross-project generality or scientific improvement is
claimed. Approval, real canaries, paid implementation units, measured spend and the final decision remain
not-run. Fake checks exercise the transport and accounting only, with an intentionally unclean environment.
