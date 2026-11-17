# Three evaluation-rule decisions (draft, awaiting the maintainer)

English · [中文](2026-11-17-eval-rule-decisions.zh.md)

**Status: draft until the PR that adds this page is merged; merging it is the maintainer's approval.** The rows to be folded
into [DECISIONS](../DECISIONS.md) are in `changes/eval-lead-vendor-spend.decision.md`,
`changes/eval-receipt-fp-bar.decision.md` and `changes/eval-relay-evidence.decision.md`; this page gives the full
reasoning, numbers and sources behind them. No code, default, preregistration or report changes here, and nothing was
run. Evidence level of every number below: taken from earlier reports (measured) or computed with the merged
`scripts/eval/receipt_fp.py` (arithmetic only).

All three change how a claim is judged, so [engineering standards](../engineering-standards.md) section 2 asks for a
decision first. None of them changes a running or already registered evaluation: each applies from a named point
forward, and none re-judges an old result.

| # | Decision in one line | From when |
|---|---|---|
| 1 | Quota-scenario claims use **lead-vendor spend** as the primary cost metric; total spend becomes a "not much dearer" guardrail | The first preregistration of a quota-scenario claim committed after this is approved (planned: stage 3); not round 2 |
| 2 | The ordinary `ok` receipt false-positive bar is **point estimate ≤ 2% and one-sided 95% Clopper-Pearson upper bound ≤ 5%** | Every receipt false-positive verdict written after approval |
| 3 | "Work does not stop when quota runs out" is judged on **naturally occurring limit events**, with fixed definitions of an event, a success and a failure, and at least 5 counted events | Events from the approval date on |

---

## 1. Lead-vendor spend as the primary metric of the quota scenario

### Decision

- For a claim of the form "delegating saves the quota of the vendor that leads" (roadmap claim S(2)), the primary cost
  metric is **lead-vendor spend**: the API-equivalent USD of every call in the unit that goes to the lead's vendor
  (the lead, sub-agents of the same vendor, reviewers of the same vendor), summed from the ledgers. This is the
  definition round 2 already registered as a secondary metric
  ([round 2](prereg/2026-11-16-round2.md) section 4, computed by `unified_summary` since #347).
- **Whoever leads is the lead vendor.** The metric names no vendor. With a Codex lead it is Codex's spend, with a
  Claude lead Claude's. relayline does not favour a vendor; which one leads is the user's choice. A result is stated
  only for the lead / sub-agent combination that was measured.
- Total spend (all vendors, API-equivalent) stays in the verdict as a **guardrail**: the claim fails if it is much
  dearer overall. Correctness and wall time keep their guardrails.
- Proposed numbers (the roadmap's, section 3.2), fixed only in the claim's own preregistration: per-task geometric-mean
  ratio of lead-vendor spend, one-sided 95% upper bound ≤ 0.6; guardrails total spend ≤ 1.2×, correctness difference
  lower bound > −0.15, median wall ≤ 3×.
- Every other cost claim (default path not worse, cheap first round, faster) keeps **total spend** as its primary cost.

### Why, and where the data come from

- G4 in the [unified test](2026-11-14-unified.md) (8 tasks, one run each, used tasks, Claude lead, Codex
  `gpt-6.1-sol` medium sub-agent): self → ccxlong right 7 = 7; total spend 1.39×, so **Fail** under the registered
  total-spend rule; Claude's own spend $0.25 vs $1.03, **24% of self**. The preregistration had no bar for this.
- What a subscription user runs out of is the quota with the vendor that leads. Total spend adds the other vendor's
  spend, which comes out of a different quota; it answers "is it cheaper in API dollars", not "does my lead's quota
  last longer". The lead session's roadmap of 2026-11-16 (a local planning file, not in the repository) proposes
  splitting the two.
- Only a sub-agent from another vendor can save the lead's quota; a same-vendor sub-agent spends the same quota
  (round 2, group C).

### This is a new ruler before a new run, not a rescue

- **G4 stays Fail.** It is not re-judged with the new metric; its 24% is the reason to ask the question, not
  evidence for the answer (8 used tasks, one run each, diagnostic).
- **Round 2 is unchanged.** Group C keeps its registered verdict (total cost ≤ 1.0, lead-vendor spend secondary,
  diagnostic, no default change), whether or not it has run when this is approved.
- The new metric applies only to a preregistration committed after approval, on **new tasks not used before**
  (stage 3 plans about 60 new long upstream tasks). The thresholds are written into that preregistration before any
  run and do not change afterwards.

### Alternatives considered

| Alternative | Why not |
|---|---|
| Keep total spend as the only primary cost | It does not measure the quota the user runs out of; cross-vendor offloading adds the sub-agent's spend by construction, so the quota claim could never be shown |
| Lead-vendor spend and total spend both primary (both must beat a saving bar) | Same problem: total spend ≤ 0.8 is a different claim (cheaper overall). Total spend as a guardrail (≤ 1.2×) keeps "not much dearer" without asking for that |
| Measure quota percentage (usage windows) directly | Window readings exist only for some vendors and windows and are not per call; ledger USD is available for every vendor and every call |
| Weight by subscription price | No reliable conversion from subscription quota to dollars |
| Name Claude's spend as the metric (all leads so far were Claude) | Ties the metric to one vendor; the product is vendor-neutral |

### What it affects

- New: the stage-3 quota-scenario preregistration (primary metric and guardrails); the stage-5 control with another
  vendor leading.
- Unchanged: the round-2 preregistration and its group C, the unified G1–G4 report, every non-quota claim.
- After approval, a follow-up docs PR adds a "lead-vendor spend" row to the metric table in
  `docs/engineering-standards.md` (not in this PR).

### Rollback

A later decision row reverts it. A preregistration already committed under this decision keeps its metric until its
verdict (no switching during a run); the revert applies only to preregistrations committed after it.

---

## 2. Receipt false-positive bar: point ≤ 2% and upper bound ≤ 5%

### Decision

- An ordinary `ok` receipt whose hidden tests fail is a false positive (definition unchanged,
  [engineering standards](../engineering-standards.md) section 2). For `failures / n` ordinary `ok` receipts:
  - **Pass**: point estimate `failures / n ≤ 2%` **and** one-sided 95% Clopper-Pearson upper bound **≤ 5%**.
  - **Fail**: point estimate > 2% (as 8/209 = 3.8% was judged).
  - **Unknown**: point estimate ≤ 2% but upper bound > 5% (too few receipts), or n = 0.
- Method: one-sided 95% Clopper-Pearson (exact binomial), the same as `cp_upper` in the merged
  `scripts/eval/receipt_fp.py` (#377). `ok_self_checked`, `done` and `UNVERIFIED` are still counted separately and
  are not judged against this bar.
- Which rows are pooled into one `n` (for example the delegating arms of several groups on one pin) is written down
  before the receipt numbers are computed, and only rows from one pin and one receipt rule are pooled.

### Why

- The old wording, "≤ 2%", does not say whether it is the point estimate or the upper bound.
  - Read as the point estimate, 0/6 passes: no uncertainty is taken into account.
  - Read as the upper bound, it needs **149** receipts with zero failures (236 with one): no planned evaluation gets
    there, so the bar can never be judged. `receipt_fp.py` currently reports this reading as `below_2pct`.
- hc2 had 0/19: upper bound 14.6%. Under the old wording it was "cannot show below 2%"; under this one it is Unknown,
  with a stated sample size that would settle it.
- The new bar keeps 2% as the target and adds a limit on how uncertain a Pass may be.

### Sample size needed (computed with `receipt_fp.cp_upper`)

| Failures | Smallest n that can Pass | Upper bound at that n | For comparison: n for upper bound ≤ 2% |
|---|---|---|---|
| 0 | 59 | 4.95% | 149 |
| 1 | 93 | 5.00% | 236 |
| 2 | 124 | 4.99% | 313 |
| 3 | 153 | 4.99% | 386 |
| 4 | 200 | 4.52% | 456 |

So: below 59 ordinary `ok` receipts, the result is Unknown or Fail, never Pass. 100 receipts may hold at most 1
failure, 150 at most 2, 200 at most 4. Round 2's group B has 60 tasks, so its delegating arm alone gives at most about
60 receipts, and only some are ordinary `ok`; a Pass will likely need pooling stated in advance or a later round.

Historical results under the new rule, for orientation only (not re-judged): 8/209 = 3.8% (upper bound 6.8%) is Fail;
0/19 is Unknown.

### Alternatives considered

| Alternative | Why not |
|---|---|
| Upper bound ≤ 2% | Needs 149+ receipts; never judgeable at this project's scale |
| Point estimate ≤ 2% only | Passes 0/6 or 0/19, where the true rate could be 15–39% |
| Fail only when the lower bound is above 2% | More lenient to the product; kept as a question for the maintainer, not the default (standards section 9: do not pick the reading that favours the result) |
| Two-sided interval or Wilson | One-sided matches the question ("at most how high") and the merged script; exact is safe for small counts |

### What it affects

- Every receipt false-positive verdict written after approval, starting with the round-2 report's receipt analysis
  (which is not a gate of any round-2 group). The rule only adds a condition to the "≤ 2%" wording it clarifies, so it
  cannot turn an old Fail into a Pass.
- Follow-ups after approval (separate issue and PR each): `receipt_fp.py` gets a field for this bar next to
  `below_2pct` (existing fields keep their meaning); the "Receipt false positive" row in engineering standards cites
  the bar. Not in this PR.
- Unchanged: STATUS, measured, the hc2 and audit reports.

### Rollback

A later decision row reverts it; verdicts already written keep the rule they were written under, labelled as such.

---

## 3. Evidence for "work does not stop when quota runs out"

### Decision

This claim cannot be a preregistered controlled experiment: nobody burns quota on purpose. It is judged on a log of
**naturally occurring** limit events. Evidence level: measured, not controlled; reports say so.

**What counts as an event** (one row each, logged within 24 hours with its packet id or run id):

| Source | Counts when |
|---|---|
| Lead hits a limit (Claude `StopFailure` hook, `ccx relay capture --hook`) | A packet in `.ccx/relay/` with `state = quota_stopped` (confirmed usage limit) |
| Sub-agent hits quota during `ccx run` / `batch` / `q` | The run record carries `quota_fallback` (from → to, reset time) |

Not counted, but listed with counts: `rate_limit_unconfirmed` packets (may be a short rate limit); `capacity_recovery`
(model busy, not quota); simulated or replayed events (such as the 2026-11-10 check in [relay](../relay.md));
events inside evaluation hubs; any event caused on purpose.

**Success** (work did not stop), all of:

1. The work continued at another vendor or model from the saved state: for a lead, `ccx relay continue PACKET_ID
   --launch` started from that packet (the user running the command is by design); for a sub-agent, the fallback run
   started.
2. Nothing was lost: the worktree, uncommitted files and checkpoint present at the event are still there or were
   carried into the continuation.
3. The task was finished: the continuation's own check passed, or the person marked it done (`ccx verify` or the
   daily usage log), within the same working day, without redoing the work from scratch.

**Failure**: an event that is counted and not a success: no continuation possible (for example the packet was
blocked by an Unknown Git snapshot), the continuation ended `no_changes` / `changes_unknown` / with an error and the
work was redone by hand, or the task was abandoned. **Any event that loses uncommitted work fails the whole claim**,
whatever the ratio (the roadmap's guardrail).

**Not attempted**: the person chose to wait for the reset and wrote so in the log at the time. Listed with counts and
excluded from the ratio (see question 4 in the PR).

**When to conclude**: at least **5 counted events**, success ≥ **80%** (so 4 of 5, 8 of 10). Fewer than 5 is Unknown.
The report gives successes / counted events, the one-sided 95% Clopper-Pearson lower bound (4/5 gives about 34%, so
this is weak evidence and is labelled so), and a split by role (lead / sub-agent) and by vendor pair. Quoting a number
publicly needs two separate windows of at least 5 events each, both ≥ 80% (the standards' two-round rule).

### Why

- [relay](../relay.md) today has only an engineering check: fake CLIs, captured and redacted Claude events, one
  simulated `StopFailure` (2026-11-10). A real limit has never been recorded. STATUS lists the claim as not verified.
- Without a definition written before events arrive, any later count could be argued either way.

### Alternatives considered

| Alternative | Why not |
|---|---|
| Exhaust quota on purpose in a controlled run | Costs the user's quota, not natural behaviour, and the relay docs say not to |
| Count `rate_limit_unconfirmed` packets | Many are short rate limits; they would inflate the denominator with events that need no handoff |
| Count `capacity_recovery` | Model busy is a different failure; reported next to it, not in it |
| Continue to say "Unknown" with no definition | Never resolvable; the claim is one of the user's headline positions |

### What it affects

- Stage 2 (two weeks of real use): the daily usage log (#376) records these rows.
- Known gap: Codex has no quota `StopFailure` hook ([relay](../relay.md)), so a Codex lead's limit is not captured
  automatically; events with a Codex lead stay Unknown unless logged by hand with their evidence.
- Unchanged: `[relay] enabled = false` default, quota classification, every command and JSON field.

### Rollback

A later decision row reverts it; events already logged are kept and reported under the definition they were logged
with.

---

## Change log

- 2026-11-17: first draft for the maintainer (not approved).
