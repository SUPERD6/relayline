# Three evaluation-rule decisions (confirmed by the maintainer, 2026-11-19)

English · [中文](2026-11-17-eval-rule-decisions.zh.md)

**Status: decided. The maintainer confirmed all three decisions on 2026-11-19, taking every default and suggested
value on this page as written.** The rows to be folded into
[DECISIONS](../DECISIONS.md) are in `changes/eval-lead-vendor-spend.decision.md`,
`changes/eval-receipt-fp-bar.decision.md` and `changes/eval-relay-evidence.decision.md`; this page gives the full
reasoning, numbers and sources behind them. No code, default, preregistration or report changes here, and nothing was
run. Evidence level of every number below: taken from earlier reports (measured) or computed with the merged
`scripts/eval/receipt_fp.py` (arithmetic only). The thresholds of decision 1 are fixed numbers now, but they are written into a
claim's own preregistration before that claim runs and are not changed afterwards.

All three change how a claim is judged, so [engineering standards](../engineering-standards.md) section 2 asks for a
decision first. None of them changes a running or already registered evaluation: each applies from a named point
forward, and none re-judges an old result.

| # | Decision in one line | From when |
|---|---|---|
| 1 | Quota-scenario claims use **lead-vendor spend** as the primary cost metric; total spend becomes a "not much dearer" guardrail | The first preregistration of a quota-scenario claim committed after confirmation (2026-11-19); not round 2 |
| 2 | The ordinary `ok` receipt false-positive bar is **point estimate ≤ 2% and one-sided 95% Clopper-Pearson upper bound ≤ 5%** | Every receipt false-positive verdict written after confirmation (2026-11-19) (round 2: see section 2) |
| 3 | "Work does not stop when quota runs out" is judged on **naturally occurring limit events**, with fixed, mostly machine-checkable definitions of an event, a success and a failure, and at least 5 counted events | Events from confirmation (2026-11-19) on |

---

## 1. Lead-vendor spend as the primary metric of the quota scenario

### Decision

- For a claim of the form "delegating saves the quota of the vendor that leads" (the quota scenario: a long task
  handed to another vendor's sub-agent), the primary cost metric is **lead-vendor spend**: the API-equivalent USD of
  every call in the unit that goes to the lead's vendor (the lead, sub-agents of the same vendor, reviewers of the
  same vendor), summed from the ledgers. This is the definition round 2 already registered as a secondary metric
  ([round 2](prereg/2026-11-16-round2.md) section 4, computed by `unified_summary` since #347).
- **Whoever leads is the lead vendor.** The metric names no vendor. With a Codex lead it is Codex's spend, with a
  Claude lead Claude's. relayline does not favour a vendor; which one leads is the user's choice. A result is stated
  only for the lead / sub-agent combination that was measured.
- Total spend (all vendors, API-equivalent) stays in the verdict as a **guardrail**: the claim fails if it is much
  dearer overall. Correctness and wall time keep their guardrails.
- Numbers (confirmed 2026-11-19; each preregistration copies them in before the run): per-task geometric-mean ratio of lead-vendor
  spend, one-sided 95% upper bound ≤ 0.6; guardrails: total spend ≤ 1.2×, correctness difference lower bound
  > −0.15, median wall ≤ 3×. Reasons for these values: 0.6 asks for a clear saving (G4's point value was 0.24, so the
  bar leaves room for a smaller effect on new tasks while still meaning "about half or less"); 1.2× is the cost
  margin an earlier cost bar in this project used (stage 3 of the [optimization plan](2026-11-04-optimization-plan.md):
  cost per success ≤ 1.2× self);
  −0.15 is round 2's non-inferiority margin; 3× allows for handover overhead on long tasks, where G4 measured 4.98×.
- Every other cost claim (default path not worse, cheap first round, faster) keeps **total spend** as its primary cost.

### Why, and where the data come from

- G4 in the [unified test](2026-11-14-unified.md) (8 tasks, one run each, used tasks, Claude lead, Codex
  `gpt-6.1-sol` medium sub-agent): self → ccxlong right 7 = 7; total spend 1.39×, so **Fail** under the registered
  total-spend rule; Claude's own spend $0.25 vs $1.03, **24% of self**. The preregistration had no bar for this.
- What a subscription user runs out of is the quota with the vendor that leads. Total spend adds the other vendor's
  spend, which comes out of a different quota; it answers "is it cheaper in API dollars", not "does my lead's quota
  last longer". The two questions need separate metrics.
- Only a sub-agent from another vendor can save the lead's quota; a same-vendor sub-agent spends the same quota
  (round 2, group C).

### This is a new ruler before a new run, not a rescue

- **G4 stays Fail.** It is not re-judged with the new metric; its 24% is the reason to ask the question, not
  evidence for the answer (8 used tasks, one run each, diagnostic).
- **Round 2 is unchanged.** Group C keeps its registered verdict (total cost ≤ 1.0, lead-vendor spend secondary,
  diagnostic, no default change), whether or not it has run at confirmation (2026-11-19).
- The new metric applies only to a preregistration committed after confirmation (2026-11-19), on **new tasks not used before**
  (planned: about 60 new long tasks from real upstream commits). The thresholds are written into that
  preregistration before any run and do not change afterwards.

### Alternatives considered

| Alternative | Why not |
|---|---|
| Keep total spend as the only primary cost | It does not measure the quota the user runs out of; cross-vendor offloading adds the sub-agent's spend by construction, so the quota claim could never be shown |
| Lead-vendor spend and total spend both primary (both must beat a saving bar) | Same problem: total spend ≤ 0.8 is a different claim (cheaper overall). Total spend as a guardrail (≤ 1.2×) keeps "not much dearer" without asking for that |
| Measure quota percentage (usage windows) directly | Window readings exist only for some vendors and windows and are not per call; ledger USD is available for every vendor and every call |
| Weight by subscription price | No reliable conversion from subscription quota to dollars |
| Name Claude's spend as the metric (all leads so far were Claude) | Ties the metric to one vendor; the product is vendor-neutral |

### What it affects

- New: the next quota-scenario preregistration (primary metric and guardrails); a later control with another
  vendor leading.
- Unchanged: the round-2 preregistration and its group C, the unified G1–G4 report, every non-quota claim.
- After confirmation (2026-11-19), a follow-up docs PR adds a "lead-vendor spend" row to the metric table in
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
  - **Fail**: point estimate > 2%.
  - **Unknown**: point estimate ≤ 2% but upper bound > 5% (too few receipts), or n = 0.
- Method: one-sided 95% Clopper-Pearson (exact binomial), the same as `cp_upper` in the merged
  `scripts/eval/receipt_fp.py` (#377). `ok_self_checked`, `done` and `UNVERIFIED` are still counted separately and
  are not judged against this bar.
- Which rows are pooled into one `n` (for example the delegating arms of several groups on one pin) is written down
  before the receipt numbers are computed, and only rows from one pin and one receipt rule are pooled.
- **Round 2:** if round 2 has not started at confirmation (2026-11-19), its report's receipt analysis uses this bar. If it
  has already started, the report keeps the old wording ("≤ 2%"), says so, and may show this bar next to it only as
  a labelled extra. Either way the receipt analysis is not a gate of any round-2 group.

### Why

- The 2% bar comes from the release plan's item P1-10, as quoted in the [verdict audit](2026-10-31-verdict-audit.md)
  ("Against the bar"): more than 2% false "right" after #158 is a must-fix before release. That wording, and the
  standards' "≤ 2%", do not say whether it is the point estimate or the upper bound.
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

For orientation only, not re-judged: hc2's 0/19 ordinary `ok` would be Unknown. The audit's 8/209 = 3.8% is **not
comparable**: it counts units whose receipt "said right", including `done` and the sub-agent's own `partial`
([verdict audit](2026-10-31-verdict-audit.md), method and "partial with ok: true"), not only ordinary `ok` receipts,
so this bar is not applied to it.

### Alternatives considered

| Alternative | Why not |
|---|---|
| Upper bound ≤ 2% | Needs 149+ receipts; never judgeable at this project's scale |
| Point estimate ≤ 2% only | Passes 0/6 or 0/19, where the true rate could be 15–39% |
| Fail only when the lower bound is above 2% | More lenient to the product; considered and not chosen by the maintainer (2026-11-19); standards section 9: do not pick the reading that favours the result |
| Two-sided interval or Wilson | One-sided matches the question ("at most how high") and the merged script; exact is safe for small counts |

### What it affects

- Every receipt false-positive verdict written after confirmation (2026-11-19) (round 2 as stated above). The rule only adds a
  condition to the "≤ 2%" wording it clarifies, so it cannot turn a Fail into a Pass.
- Follow-ups after confirmation (2026-11-19) (separate issue and PR each): `receipt_fp.py` gets a field for this bar next to
  `below_2pct` (existing fields keep their meaning); the "Receipt false positive" row in engineering standards cites
  the bar. Not in this PR.
- Unchanged: STATUS, measured, the hc2 and audit reports.

### Rollback

A later decision row reverts it; verdicts already written keep the rule they were written under, labelled as such.

---

## 3. Evidence for "work does not stop when quota runs out"

### Decision

This claim cannot be a preregistered controlled experiment: nobody burns quota on purpose. It is judged on a log of
**naturally occurring** limit events. Evidence level: measured, not controlled; reports say so. Each condition below
is marked **machine** (checkable from ccx's own records) or **manual** (needs the person's note, written at the time).
`N` is the continuation window, **4 hours** (confirmed by the maintainer, 2026-11-19).

**What counts as an event.** One event per original task; review fix rounds and resumes that inherit a field from the
run they continue are not new events.

| Source | Counts when | How checked |
|---|---|---|
| Sub-agent hits quota during `ccx run` / `batch` / `q` | The run record has `quota_stop`, or `quota_fallback`, or an attempt with `kind == "quota"`: the same "hit" rule as the daily usage page (`ccx/daily.py`, #376). It does not matter whether a fallback happened | machine |
| Lead hits a confirmed limit (Claude `StopFailure` hook, `ccx relay capture --hook`) | A packet in `.ccx/relay/` with `state = quota_stopped` | machine |
| Lead hits an unconfirmed limit | A `rate_limit_unconfirmed` packet counts **only** through this fixed manual path: within 1 hour of the packet, and before the continuation's outcome is known, the person logs a usage reading showing the window exhausted, or a reset time at least 1 hour away (from `ccx quota`, the CLI's own usage screen, or the limit message), with the packet id. Without that note it is not counted | manual, fixed in advance |

Not counted, but listed with counts: `rate_limit_unconfirmed` packets without the note above; `capacity_recovery`
(model busy, not quota); simulated or replayed events (such as the 2026-11-10 check in [relay](../relay.md)); events
inside evaluation hubs (`ledger.is_eval`); any event caused on purpose.

Real Claude `StopFailure` events are often `rate_limit_unconfirmed` (`ccx/quota_signals.py`; [relay](../relay.md)).
**Lead events may therefore stay at 0 for a long time.** In that case the claim is reported for sub-agents only, and
the report says that the lead side is Unknown.

**Success** (work did not stop), all of:

1. **Continued from the event** (machine). Sub-agent: the same run went on through its `quota_fallback`, or a later
   run whose `resumed_from` is the event run started at another vendor or model. Lead: a continuation record
   `.ccx/relay/<packet id>.continue-*.json` exists for the event's packet with `state` neither `prepared` nor
   `interrupted` (the person running `ccx relay continue ... --launch` is by design).
2. **Within N hours** (machine, with one limit). Sub-agent: from the event run's `ts` to the continuing run's start,
   from the ledger. Lead: packet and continuation records have no time field, so the files' modification times are
   used; a copied or touched file makes this **manual**.
3. **Nothing lost** (machine where possible). Lead: the continuation record's `workspace_changed` is `false` (ccx
   compares the snapshot at launch, including the dirty-file `content_fingerprint`, with the packet's). If it is
   `true` or the fingerprint is `Unknown`, the person checks that no change from the packet's file list was lost
   (**manual**). Sub-agent: the event run's worktree / write snapshot is the one the continuation inherits (a resume
   inherits the snapshot of the run it goes on; a fallback is the same run).
4. **Not redone from scratch** (machine). Between the event and the continuation, no other run started in the same
   workspace with the same label and an empty `resumed_from`, and (lead) no second packet for the same session was
   continued instead.
5. **Finished** (machine or manual). Sub-agent: the continuing run ends `ok`, not overturned by a later `ccx verify`.
   Lead: the continuation ends `exited` with exit code 0 and `changes_observed` true, and the task is then marked done
   by `ccx verify` or in the daily log (**manual**), within the same N-hour window counted from the continuation's end.

**Failure**: a counted event that is not a success. In particular: a `quota_stop` with no fallback and no
continuation within N hours; a packet that could not be continued (for example an Unknown Git snapshot); a
continuation ending `no_changes`, `changes_unknown` or with an error after which the work was redone; an abandoned
task. **Any event that loses uncommitted work fails the whole claim**, whatever the ratio.

**Not attempted**: the person chose to wait for the reset and wrote so in the daily log at the time. Listed with
counts and excluded from the ratio (confirmed by the maintainer, 2026-11-19).

**When to conclude**: at least **5 counted events**, success ≥ **80%** (so 4 of 5, 8 of 10). Fewer than 5 is Unknown. Lead and sub-agent events are pooled in the count and also reported by role.
The report gives successes / counted events, the one-sided 95% Clopper-Pearson lower bound (4/5 gives about 34%, so
this is weak evidence and is labelled so), and a split by role (lead / sub-agent) and by vendor pair. Quoting a number
publicly needs two separate windows of at least 5 events each, both ≥ 80% (the standards' two-round rule).

### Why

- [relay](../relay.md) today has only an engineering check: fake CLIs, captured and redacted Claude events, one
  simulated `StopFailure` (2026-11-10). A real limit has never been recorded. STATUS lists the claim as not verified.
- Counting only fallbacks (`quota_fallback`, written only when a fallback was found) would leave failed handoffs out
  of the denominator; the daily page's "hit" rule counts every limit hit.
- Without a definition written before events arrive, any later count could be argued either way.

### Alternatives considered

| Alternative | Why not |
|---|---|
| Exhaust quota on purpose in a controlled run | Costs the user's quota, not natural behaviour, and the relay docs say not to |
| Count only runs with `quota_fallback` | Biased toward success: a hit with no fallback writes `quota_stop` instead |
| Count every `rate_limit_unconfirmed` packet | Many are short rate limits; they would fill the denominator with events that need no handoff |
| Never count `rate_limit_unconfirmed` | Lead events might never occur; the fixed manual path keeps them countable without hindsight |
| Count `capacity_recovery` | Model busy is a different failure; reported next to it, not in it |
| Continue to say "Unknown" with no definition | Never resolvable; the claim is one of the user's headline positions |

### What it affects

- The planned period of real daily use: the daily usage page (#376) already counts hits and relays; the remaining
  fields (continuation, N-hour window, notes) are logged per event.
- Known gap: Codex has no quota `StopFailure` hook ([relay](../relay.md)), so a Codex lead's limit is not captured
  automatically; events with a Codex lead stay Unknown unless logged by hand with their evidence.
- Unchanged: `[relay] enabled = false` default, quota classification, every command and JSON field.

### Rollback

A later decision row reverts it; events already logged are kept and reported under the definition they were logged
with.

---

## Change log

- 2026-11-17: first draft for the maintainer (not approved).
- 2026-11-17, after the independent review (1 blocker, 6 should-fix, minor points): sub-agent events use the daily
  page's hit rule and a `quota_stop` with no continuation is a failure; a fixed manual path for unconfirmed lead
  limits, and lead events may stay 0; success conditions made machine-checkable where possible, with an N-hour window;
  8/209 marked not comparable; round-2 timing stated; no reliance on the local roadmap; source of the 2% bar.
- 2026-11-19: the maintainer confirmed all nine questions with the defaults: (1) lead-vendor spend is the primary
  metric of quota-scenario claims, effective from the next quota-scenario preregistration, round 2 unchanged; (2) the
  numbers 0.6 / total spend 1.2× / correctness lower bound > −0.15 / wall 3×; (3) the receipt bar is point estimate
  ≤ 2% and upper bound ≤ 5%, Fail = point estimate > 2%; (4) waiting for the reset by the user's choice counts as
  not attempted; (5) at least 5 events and ≥ 80%, two windows of ≥ 5 for public use, lead and sub-agent events
  pooled and also reported by role; (6) a `quota_stop` with no fallback is counted, and no fallback or continuation
  within N hours is a failure; (7) the fixed manual confirmation path for `rate_limit_unconfirmed` is allowed;
  (8) N = 4 hours; (9) this note stays in `docs/research/` and moves into `docs/DESIGN.md` after implementation.
  Wording above changed from draft to decided; no number changed.
