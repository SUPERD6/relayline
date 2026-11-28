# relayline technical report: working draft

English · [中文](tech-report-draft.zh.md) · back to [research reports](README.md) · tracker: [#563](https://github.com/SUPERD6/relayline/issues/563)

**Status: draft (2026-11-28). Not for citation.** Sections marked `TODO` are not written because the evidence does not
exist yet (group B, the router, the baseline comparison). **Every number in this draft is copied from a report in this
folder and links to it; the draft computes nothing of its own.** Literature facts come from the search in
[#563's comments](https://github.com/SUPERD6/relayline/issues/563) (arXiv / Crossref metadata and abstracts; **no paper was
read in full**), so each related-work claim below is "as far as the abstract says" until it is checked against the full
text (see the TODO list at the end).

## 1. Abstract (placeholder)

TODO: write last. One paragraph: the problem (section 2), the system (section 4), the pre-registered evaluation
(section 5), what is shown (section 6) and what is not (section 8).

## 2. Problem

Coding agents now hand work to each other: a lead agent (Claude Code or Codex) sends a piece of a task to a cheaper or
different sub-agent, and the question is whether that is better than the lead doing the work itself. Four things make
this hard to answer, and each is a section of this report:

1. **The sub-agent does not know what the lead knows.** A decision made earlier in the lead's conversation, or a note
   in memory, is invisible to a fresh sub-agent. Without it a cheap sub-agent is simply wrong, whatever its price.
2. **Work must be accepted by something other than the sub-agent's own report.** A "done" from the worker, or a test
   run the worker chose, can be wrong.
3. **The comparison itself is easy to get wrong.** Delegation is usually compared with a "do it yourself" baseline, and
   the cost and quality of that baseline depend on how it is run. The working hypothesis behind this project is that a
   baseline run as a *fresh, short session* understates what doing it yourself costs inside a *real, long session*, so
   delegation looks worse (or better) than it is. **This hypothesis is not yet tested here**: group B (section 7.1) is
   the first measurement that bears on it, and it is still pending.
4. **Sessions end.** A quota limit stops the lead mid-task; the work should be continued by another tool without
   starting over (relay, section 4.3).

## 3. Related work and where we draw the line

All entries below are from [#563's literature search](https://github.com/SUPERD6/relayline/issues/563); descriptions are
from abstracts or search snippets, not full texts.

### 3.1 The nearest paper: arXiv 2611.33893

*When Are Parallel Subagents Effective for Coding?* (Lyu, Yin, Zhang; [arXiv:2611.33893](https://arxiv.org/abs/2611.33893),
2026-11). As far as the abstract says, it compares a single agent with a main agent plus sub-agents on NL2Repo and
ProgramBench, under equal time and equal cost; reports that sub-agents add only a little over the single agent at a
higher cost; reports that a single agent which periodically opens a fresh empty session makes early progress faster than
one that keeps one session; and reports that one prompt sentence ("probe the reference program first") recovers most of
the gain. It is the closest paper and overlaps half of our mainline.

| | 2611.33893 (from the abstract) | This work |
|---|---|---|
| Question | When are parallel sub-agents worth it for repository building? | Does delegating to a cheaper sub-agent beat doing the work yourself, and what makes it fail? |
| What varies | Single agent vs main + sub-agents; session length and fresh context as a factor on the single-agent baseline | What the sub-agent is given (shared context, memory); who does the work first (cheap first vs self); how work is accepted |
| Outcome | Progress on repository construction, under equal time and cost | Hidden-test correctness per task, paired, plus cost per success and wall time |
| Sessions | Observes that fresh vs continued sessions change a single agent's progress | Plans to measure the *baseline's* cost inside a real long session against a fresh short one (section 7.1, pending) |
| Accounting | Equal-cost comparison | A ledger of the lead's and the sub-agents' spend, normalized to API-equivalent USD |
| Method | Not read in full | Pre-registered, one group at a time, exact paired test with Holm correction (section 5) |

The boundary, stated carefully: that paper shows that session freshness affects a single agent's progress. It does not,
from what we have read, treat "the do-it-yourself control in a delegation experiment is a fresh short session" as a bias
in its own right, and it does not cost a real long session. That claim is **ours to show, and we have not shown it yet**
(group B and the baseline comparison are TODO). What we can already say is narrower: our A groups test a different
question (does the sub-agent get the lead's knowledge), which that paper does not address. **TODO: read the full text
and replace "from the abstract" with what the experiments actually did; the table above may need to change.**

### 3.2 Other work

| Topic | Work | How we use it |
|---|---|---|
| Baselines and cost in agent evaluation | *AI Agents That Matter* ([2407.01502](https://arxiv.org/abs/2407.01502)) | The general point that a weak baseline or accuracy-only reporting misleads. We apply it to one specific baseline choice (session length). |
| Long vs short conversations | *LLMs Get Lost In Multi-Turn Conversation* ([2505.06120](https://arxiv.org/abs/2505.06120)) | A mechanism hint that multi-turn behaviour differs from single-turn. It measures accuracy, not cost, and not coding agents. |
| Multi-agent scaling | *Towards a Science of Scaling Agent Systems* ([2512.08296](https://arxiv.org/abs/2512.08296)) | Gain depends on task structure; a precedent for a per-task-type trade-off map. Same-session controlled configurations. |
| Multi-agent failure | *Why Do Multi-Agent LLM Systems Fail?* ([2503.13657](https://arxiv.org/abs/2503.13657)) | Motivation for verification (section 4.2). |
| Is a passing test correct? | *Are "Solved Issues" in SWE-bench Really Solved Correctly?* ([2503.15223](https://arxiv.org/abs/2503.15223)); *SWE-ABS* ([2603.00520](https://arxiv.org/abs/2603.00520)) | Prior work that "tests pass" overstates correctness; our own receipt audit asks the same question for delegation (section 6.3). |
| Cheap verifiers | *Cheap Verifiers, Large Blind Spots* ([2609.01345](https://arxiv.org/abs/2609.01345)) | A caution against trusting the system's own internal metrics; we score with hidden tests the system never sees. |
| Routing and cascades | *FrugalGPT* ([2305.05176](https://arxiv.org/abs/2305.05176)); *RouteLLM* ([2406.18665](https://arxiv.org/abs/2406.18665)) | Single-request routing; background for the router (section 7.2, TODO). They route one request, not a long coding session. |

Not claimed: that no one has done our mainline (the search covered a few keyword queries only; "not found" is not "does
not exist"), and anything about papers marked unverified in the issue.

## 4. System

relayline (command `ccx`) lets Claude Code, Codex and DeepSeek be each other's lead or sub-agent. Python 3.11+, standard
library only. Details are in [DESIGN](../DESIGN.md); this section gives only the parts the evaluation tests.

### 4.1 Delegation with shared context and memory

- **Delegation.** `ccx` runs another tool headless and reads a compact JSON result; the full log stays on disk. A
  failed or blocked run moves one rung up; a quota failure falls back to the other agent
  ([DESIGN](../DESIGN.md), "Parts" 1).
- **Shared context** (`--context on`): the lead's recent conversation that the sub-agent needs is attached to the brief
  ([shared-context](../shared-context.md)). This is what A1 / A1x test.
- **Shared memory**: an incremental, append-only note store; a sub-agent's brief carries only the notes that share words
  with its task ([DESIGN](../DESIGN.md), "Parts" 5). This is what A2 / A2x test.
- **Cheap first** (`dispatch.cheap_first`): start at the cheapest rung and escalate on failure
  ([dispatch](../dispatch.md)). This is what B tests.

### 4.2 Reliability layer (receipts)

A delegation returns a *receipt*: the worker's status, ccx's own check (`--check`), an optional independent review, and
the execution outcome kept separate from acceptance. Our own audits show where this is weak, and we report them here
rather than hide them:

- A passing check that never tested the requested behaviour let wrong work through; the audit measured the rate
  ([verdict audit](2026-10-31-verdict-audit.md)).
- Execution success and acceptance are different flags and were once conflated in the evaluation prompt
  ([receipt audit](2026-11-05-receipt-audit.md)).
- When the lead's `--check` was the whole existing suite, it could not see a new requirement
  ([unified report, "Why G3/G4 did badly"](2026-11-14-unified.md)); a sensitivity check (off by default) was added.

### 4.3 Relay across tools

When a tool stops on a usage limit, a hook saves a handoff packet; the user stops the old session and runs one command to
continue the same task in the other tool ([relay](../relay.md)). Relay is **off by default and experimental**.
TODO: the preregistered relay scenario ([eval rule decisions](2026-11-17-eval-rule-decisions.md): lead-vendor spend primary,
at least 5 natural limit events) has no result yet; this section describes the mechanism only.

## 5. Evaluation design

The rules are fixed in a pre-registration before each round. The pieces that matter for reading the results:

- **Pre-registration first.** Tasks, arms, thresholds and verdict rules are committed before any run
  ([round 1](prereg/2026-11-07-unified.md), [round 2](prereg/2026-11-16-round2.md)). A deviation is recorded as a change
  log entry, not edited away.
- **Unit and test.** One run per task per arm; the task is the unit. Paired arms are compared with an exact two-sided
  McNemar test on hidden-test outcomes, with Holm correction inside each family of claims
  ([round 2, "What was tested, and how"](2026-11-27-round2.md)).
- **Hidden tests.** Correctness is scored by tests the lead and sub-agent never see.
- **Pass rule (A groups).** Valid pairs ≥ 43 of 48, more tasks better with the feature than without, adjusted p < 0.05 and
  an effect of at least 0.15 ([round 2](2026-11-27-round2.md)); the shared-context group also has a cost-per-success
  bound.
- **One group at a time, on an idle machine.** A read-only monitor checks that no outside pytest runs during a group;
  an interrupted group is never resumed, it is rerun from the start under a new tag
  ([round 2](2026-11-27-round2.md), [round 1 "Attempts judged Unknown"](2026-11-14-unified.md)).
- **Leak audits.** A read-only audit after round 1 found one arm contaminated; the result was withdrawn and published as
  Unknown ([round 1, "Correction"](2026-11-14-unified.md)).
- **One accounting unit.** API-equivalent USD, headline metric cost per success
  ([token-cost quantification](2026-10-23-token-cost-quantification.md)).
- **Interpretation rule.** One round is a signal; quoting a number needs a second round
  ([round 2](2026-11-27-round2.md), "How to read the numbers").

## 6. Results so far

Everything in this section is from [round 1](2026-11-14-unified.md) and [round 2](2026-11-27-round2.md). All tasks in
round 1 had been used before; round 2's tasks are new and synthetic.

### 6.1 Shared context and memory make a cheap sub-agent much less wrong (A groups)

The tasks are built so that the needed agreement or note exists only in the lead's transcript or in memory; the baseline
is near zero **by design**.

| Group | Sub-agent | Valid pairs | b / c | Holm-adjusted p | Verdict | Source |
|---|---|---|---|---|---|---|
| A1 shared context | Claude haiku low | 47 | 43 / 0 | 4.547×10⁻¹³ | Pass | [round 2](2026-11-27-round2.md) |
| A2 memory | Claude haiku low | 48 | 42 / 0 | 4.547×10⁻¹³ | Pass | [round 2](2026-11-27-round2.md) |
| A1x shared context | Codex gpt-6-luna low | 48 | 44 / 0 | 2.274×10⁻¹³ | Pass | [round 2](2026-11-27-round2.md) |
| A2x memory | Codex gpt-6-luna low | 48 | 41 / 0 | 9.095×10⁻¹³ | Pass | [round 2](2026-11-27-round2.md) |
| G1 shared context (round 1) | Codex gpt-6-luna low | 42 | 16 / 0 | 3.1×10⁻⁵ (unadjusted) | Pass | [round 1](2026-11-14-unified.md) |
| G2 memory (round 1) | Codex gpt-6-luna low | 18 | 14 / 0 | 1.2×10⁻⁴ (unadjusted) | Pass | [round 1](2026-11-14-unified.md) |

b = tasks right with the feature and wrong without; c = the reverse. In round 2 no task went from right to wrong
(c = 0 in all four groups). The baseline arms were right on very few tasks: A1 4 of 47, A2 4 of 48, A1x 2 of 48, A2x 4
of 48 ([round 2](2026-11-27-round2.md)). The Codex claims have two rounds (round 1 and A1x / A2x); the Claude-sub-agent
claims have one (A1 / A2), which by our own interpretation rule is a signal, not a number to quote
([round 2](2026-11-27-round2.md)). In round 1, the dsh (DeepSeek) arm of G1 was found contaminated and is Unknown; the
G1 Pass comes from the Codex arm only ([round 1, "Correction"](2026-11-14-unified.md)).

### 6.2 What is not a win

- **Cost.** Total spend per arm is similar: with context it is lower in A1 and higher in A1x. Cost per success falls
  mostly because the baseline almost never succeeds, so no saving is claimed
  ([round 2, "Limits"](2026-11-27-round2.md)).
- **Cheap first and long tasks failed in round 1.** G3 (cheap first, 6 tasks) and the G4 long-task diagnostics failed
  their rules: right 3/6 for self vs 2/6 for cheap first, wall time 2.72× ([round 1](2026-11-14-unified.md)). The
  investigation traced much of it to a check that could not see the new requirement and to hand-over overhead on tasks
  that self finishes in about 40 seconds ([round 1, "Why G3/G4 did badly"](2026-11-14-unified.md)).
- **Small outside exercises: delegating lost.** On 30 polyglot Python exercises a delegating lead was right 12/30 against
  25/30 for self, and dearer per success ([pg1](2026-10-31-polyglot-pg1.md)). On a repository hold-out the delegating arm
  was not seen to be less right and was cheaper per success but about 3× slower ([hc1](2026-10-29-hc1-holdout.md)). These
  two ran under earlier rules and code, not under the round-2 pre-registration, and are not paired.

### 6.3 Receipts: how reliable is "done"?

After fix #158, 8 of 209 receipts that said "right" failed the hidden tests (3.8%, above the 2% bar
set beforehand), and 47 of 51 receipts that said "wrong" were in fact right; ccx erred more by being too strict than too
lenient ([verdict audit](2026-10-31-verdict-audit.md)). A later recheck of the receipts gave insufficient evidence on the
2% bar ([pg3b](2026-11-03-pg3b-receipts.md)). This audit predates the round-1 and round-2 evaluations and has not been
repeated under them; TODO: rerun it on a later round's data.

### 6.4 Failed or stopped attempts

Round 1 reran four attempts after infrastructure faults, each recorded and none changing a threshold
([round 1](2026-11-14-unified.md)). In round 2, group B's first run was stopped and is Unknown: every delegated
dispatch failed to start because a command line was too long on Windows, a fault of the tested arm and not a result
about cheap first ([round 2, "Group B"](2026-11-27-round2.md)).

## 7. TODO: results not yet available

### 7.1 TODO: group B, cheap first vs doing the work alone

Design only (from [round 2, "What B asks"](2026-11-27-round2.md)): arm `self` vs arm `ccxcheapfirst2`, 60 new harder
tasks, one run per task per arm; pass needs non-inferiority on correctness and bounds on cost and wall time in three
analyses. The first run is Unknown; the rerun's verdict is `PENDING`. Fill in from the rerun report only, with each
pre-registered condition shown.

This is also the first place the "baseline session length" hypothesis (section 2, item 3) can be touched, **if** the
rerun's design includes a long-session arm. TODO: decide, with a preregistration, how to measure the baseline in a real
long session against a fresh one (the ledger already records the lead's own usage; see [DESIGN](../DESIGN.md) part 7),
and what bar would count as a measured bias. Until then the hypothesis stays a hypothesis.

### 7.2 TODO: the router (trade-off map)

The planned result is a per-task-type map of which agent and rung to use, with cell-by-cell evidence. No result exists.
TODO: write after the router's evaluation; relate it to single-request routing and cascades (section 3.2) and state
what is different about a coding session.

### 7.3 TODO: baseline comparison

TODO: compare against the strongest realistic baselines (doing it yourself in a long session; the built-in sub-agent of
Claude Code; the delegation methods in section 3). Earlier reports include a built-in sub-agent arm
([round 3](2026-10-25-r3.md), [hc1](2026-10-29-hc1-holdout.md)); they predate the pre-registered rounds and are not a
substitute.

### 7.4 TODO: relay scenario

TODO: the preregistered relay evaluation (section 4.3); no result yet.

## 8. Limits

Taken from [round 2, "Limits"](2026-11-27-round2.md) and [round 1, "Limits"](2026-11-14-unified.md), and added to here:

- **Task sets.** The A tasks are synthetic and built so the context or note is necessary; the baseline is near zero by
  design. They show the mechanism works when the information is needed; they do not say how often real tasks need it,
  and the size of the effect will not carry over to real work. Round 1's tasks had been used before.
- **One machine, Windows only,** one set of tool versions, one code pin per group; no macOS or Linux result.
- **A Claude lead only** in the round-2 evaluation scripts; other leads are not covered.
- **Two sub-agent models** (Claude haiku low, Codex gpt-6-luna low); DeepSeek's round-1 arm is Unknown.
- **One run per task per arm;** no repeat-run variance. 48 pairs per group can detect large effects, not small ones.
- **Small harm checks:** 8 neutral tasks in A1 / A1x and none in A2 / A2x.
- **Authorship and vendor bias.** The tasks were written by an agent session; this design cannot show whether authorship or
  the same-vendor relation favours any model. TODO: cite the evaluator self-preference literature after checking it
  (listed as unverified in the issue).
- **Cost.** No saving is shown for the lead's own quota; the ledger lacks the lead's tokens for delegated runs in the one
  real-use week it covered ([dogfood](2026-10-31-dogfood.md)).
- **Not shown at all:** group B, the router, the relay scenario, behaviour on long real sessions, end-user benefit, and
  any default change. A Pass is a prerequisite for proposing a default change, not a decision to make one.

## 9. TODO list for the next draft

1. Read the full text of [2611.33893](https://arxiv.org/abs/2611.33893) and rewrite section 3.1 from its experiments.
2. Read the abstracts of ProgRouter, STING, the Vals AI post, and the evaluator self-preference papers (listed unverified
   in the issue) and decide whether to cite them.
3. Fill sections 7.1 to 7.4 from their reports only; update the abstract and section 6.
4. Decide how the baseline-session-length hypothesis will be measured, and preregister it, before claiming it.
5. Re-run the receipt audit on later-round data (section 6.3).
6. Check every number in sections 6 and 8 against its report again after any report is corrected.

## Where each number comes from

| Section | Numbers | Report |
|---|---|---|
| 6.1 A rows | n, b / c, adjusted p, baseline-arm counts, verdicts | [round 2](2026-11-27-round2.md) |
| 6.1 G1, G2 rows | pairs, b / c, p | [round 1](2026-11-14-unified.md) |
| 6.2 G3 and wall time | right 3/6 vs 2/6, 2.72× | [round 1](2026-11-14-unified.md) |
| 6.2 pg1 | 12/30 vs 25/30 | [pg1](2026-10-31-polyglot-pg1.md) |
| 6.3 receipts | 8 of 209, 3.8%, 47 of 51 | [verdict audit](2026-10-31-verdict-audit.md) |
| 8 limits | 8 neutral tasks, 48 pairs, one run per task | [round 2](2026-11-27-round2.md) |
