# Roadmap

English · [中文](ROADMAP.zh.md) · updated 2026-11-25 · tracker [#528](https://github.com/SUPERD6/relayline/issues/528)

**This is a living document.** It records where relayline is going, what is proven and what is not. When a
result changes the plan, a PR updates this file (and [ROADMAP.zh.md](ROADMAP.zh.md)) and adds a line to the
[adjustment log](#adjustment-log) at the end saying why. Every task and every phase hand-off goes through a GitHub
issue or PR; the lead session checks the roadmap once at the end of each phase. The tracker issue
([#528](https://github.com/SUPERD6/relayline/issues/528)) lists phases, milestones and status. Evidence labels follow
[engineering standards](engineering-standards.md): *measured*, *engineering check* (fake CLI or replay), *not run*,
plus *estimate* for numbers derived from few data. Dates are estimates: past schedules slipped, and the one thing
nobody controls is when a real quota event happens.

## Positioning

> When Claude Code runs out of quota, Codex picks up the same task on the same branch and finishes it (and the
> reverse). "Done" means a check you chose actually ran and passed.

This is the **goal, not yet a fact**. Today the relay is manual, off by default, and carries no check command; whether
a *real* quota event triggers it is *not tested*. Phase 2 exists to make the sentence true.

Two corrections from the phase-0 competitor check ([#534](https://github.com/SUPERD6/relayline/issues/534), 2026-11-25):

- Swapping to another vendor is **not unique** any more: Orca (about 138k stars) offers a manual one-click "continue
  the same session in the other harness", and the official `codex-plugin-cc` has a manual `/codex:transfer`. What no
  one checked is the combination: a handoff packet that carries the check command, an *executed* check, a receipt and a
  ledger entry (R3 [#522](https://github.com/SUPERD6/relayline/issues/522), R5 [#524](https://github.com/SUPERD6/relayline/issues/524)) and "does not take done on faith".
- Claude Code already auto-continues after the quota resets (on by default). The relay does not save "the ability to
  continue"; it saves the hours of waiting. Every demo and article has to say so.

Not promised: faster, cheaper or more accurate on every task. The trade-off map below says which kinds of task are
worth handing off, with the measurements.

## Three layers

| Layer | What it is | Where it is now | Target |
|---|---|---|---|
| 1. Reliability, always on | Four things agents often do are covered: forget, stall, falsely report "done", step on each other | Forget: shared context and memory passed one measured round. Stall: engineering check only. False "done": executed checks work, but receipt false positives are not yet under the bar. Step on each other: worktrees measured on Windows | ≥ 5 real quota events with ≥ 80% picked up and finished; receipt false positive ≤ 2%; shared context passes a second round on Codex |
| 2. Trade-off map | A table: which task type + which method wins on which dimension, and how much it may lose elsewhere. The router follows the table; unproven cells default to "do it yourself" | No cell of the 12 is proven | By launch: the floor cell has one formal verdict, the fat-context cell has a diagnostic result, the rest carry honest status |
| 3. Advanced switches hidden | The default path keeps install, relay, checks and receipts, shared memory, ledger; the experimental switches stay but leave the first screen and the daily command list | `ccx -h` lists daily commands only; `ccx advanced` lists all; install takes three steps | One-line install plus one `ccx setup`; no command to memorise |

Nothing is removed in any layer: "hide" means not on the first two README screens, not in the daily command list,
collected on one page ([T4-2](https://github.com/SUPERD6/relayline/issues/551)) with a label per switch.

## Trade-off map

A **cell** is one task type + one method + the dimension it should win. It counts as *proven* only if all three hold:
it beats both original usages (the lead doing it alone, and the tool's built-in sub-agent) on that dimension; its loss on other
dimensions stays under a limit written beforehand; and the evidence is current-version, fresh tasks, preregistered,
and repeated for two rounds (one round is only a signal). By that bar **no cell is proven today**. Serial delegation
has measured slower every time (2.7–5.5×) and never more accurate, so the realistic goal is "win one dimension per cell".

Thresholds are proposals until written into a preregistration. "Order" is the suggested sequence (1 first).

| Cell | Task type and method | Wins on | Status (evidence) | Gate to prove | How | Spend | Order | Issues |
|---|---|---|---|---|---|---|---|---|
| Floor | Installed, default path | Not worse than doing it alone | **Not tested.** Last related result: Fail (0/30 delegations, 1.27× cost vs bar 1.2) | Correctness-difference lower bound > −0.10; total-cost ratio upper bound ≤ 1.1 | Count install overhead tokens → offline replay → mixed-task paid comparison | $0, then $15–25 (estimate) | 1 | [#531](https://github.com/SUPERD6/relayline/issues/531) [#544](https://github.com/SUPERD6/relayline/issues/544) [#556](https://github.com/SUPERD6/relayline/issues/556) [#557](https://github.com/SUPERD6/relayline/issues/557) |
| 1 | Small tasks (≤ 3–4 requests alone) delegated | — | **Disproved**: 25/30 correct vs 12/30; handover cost ≈ doing it | The right method is to do it alone; what to prove is that routing to "alone" costs nothing | Folded into the floor | $0 | 1 | [#545](https://github.com/SUPERD6/relayline/issues/545) |
| 2 | Medium, short context, same-vendor cheap first (round 2, group B) | Total cost | **Disproved on 4 dev tasks** (estimate): cost ratio ≈ 2.1, wall ≈ 3.1×. Formal round 2 pending | As preregistered (all four pass) | Round 2 B | ≈ $26.5, approved $34.5 | scheduled | [#536](https://github.com/SUPERD6/relayline/issues/536) |
| 3 | Medium–large, short context, cross-vendor cheap sub-agent | Total cost | **Conflicting leads**: 0.70× (old code), 0.55–0.62× (dev set); also costlier or less correct runs | Total-cost ratio upper ≤ 0.8; correctness lower bound > −0.15 | Oracle upper bound on existing data; no separate eval | $0 | 6 | [#544](https://github.com/SUPERD6/relayline/issues/544) |
| 4 | Long task + fat context + cross-vendor | Quota of the vendor that leads | **Lead, not tested under real conditions**: lead's own spend 0.24×, lead tokens −54%. See "real lead context" below | Lead-vendor spend geometric-mean upper ≤ 0.6; guardrails: total ≤ 1.2×, correctness lower > −0.15, wall ≤ 3×; no worse than the built-in sub-agent | Fat-context three-arm diagnostic, then fresh-task confirmation | $15–25, then $30–55 | 2 | [#546](https://github.com/SUPERD6/relayline/issues/546) [#547](https://github.com/SUPERD6/relayline/issues/547) [#560](https://github.com/SUPERD6/relayline/issues/560) |
| 5 | A batch of clearly specified mechanical small tasks in one cheap run | Cost, maybe speed | **Lead**: ten blocks in one run all correct, $0.004–0.005, 68–83 s. Versus doing it alone: not tested | Total-cost ratio upper ≤ 0.8; correctness lower > −0.15; wall reported | 10–15 batches, two arms | $5–8 | 4 | [#548](https://github.com/SUPERD6/relayline/issues/548) |
| 6 | ≥ 4 unrelated large blocks in parallel | Speed | **Lead**: 10 paths 29–31 s vs 1 path 68–83 s, 7.4× tokens; baseline was not "alone" and blocks were tiny | Wall-clock median ratio ≤ 0.7, correctness not lower; token multiple reported, no 1.2× guardrail | Wait until real use shows there is parallelisable work | $15–25 | after launch | [#564](https://github.com/SUPERD6/relayline/issues/564) |
| 7 | High-risk change + other vendor's reading review | Accuracy | **Disproved lean**: of 29 self-check receipts 15 were wrong and the review passed all | Struck from the map | Not tested | — | — | — |
| 8 | High-risk change + executed sensitivity check | Accuracy (trustworthy receipt) | **Not tested** (group B is the first real run) | Receipt false positive point ≤ 2% and upper bound ≤ 5% | Use group B's rows | $0 | 3 | [#538](https://github.com/SUPERD6/relayline/issues/538) |
| 9 | Hand shared context and memory to the sub-agent | No accuracy drop | **Measured, one round Pass**: context 4/21 → 20/21, memory 2/18 → 16/18 (reused best-case tasks, Codex sub-agent). It compares with vs without context, not versus doing it alone | Exact McNemar, Holm-corrected | Round 2 group A | ≈ $2 | scheduled | [#536](https://github.com/SUPERD6/relayline/issues/536) |
| 10 | Quota out, continue on the other vendor | Faster (less waiting) | **Not tested.** The original behaviour waits for the reset and continues | ≥ 5 real events, ≥ 80% picked up and finished; also report waiting saved | Record natural events (no control arm is possible) | $0 | ongoing | R1–R8 ([#520](https://github.com/SUPERD6/relayline/issues/520)–[#527](https://github.com/SUPERD6/relayline/issues/527)), [#541](https://github.com/SUPERD6/relayline/issues/541) |
| 11 | Lead context too fat → relay to a fresh session | Lead quota | **Not tested.** Lead: 99% of the lead's spend is rereads | Before/after only; at most "lead" | Recompute "reread per request" weekly | $0 | 5 | [#532](https://github.com/SUPERD6/relayline/issues/532) |

### Router (draft, everything off until a cell is proven)

The router is not a new model but a short rule the lead can see before starting, plus checks `ccx` already has.
Three hard requirements: judging "do it yourself" must cost nothing (the lead decides, no `ccx` call); when unsure,
do it yourself; thresholds first, no learned model. Draft rules: quota event → cell 10; lead context above a
threshold → hint to relay (hint only); long task with fat context and a check that can see the new requirement →
cell 4; ≥ 5 clearly specified mechanical tasks → cell 5; ≥ 4 independent large blocks → cell 6; high risk → do it
alone with a sensitivity check; anything else, or any missing input → do it yourself. The thresholds (≈ 10 requests,
context size, 5 tasks, 4 blocks) are provisional and are set by the offline replay and the diagnostic. Floor
reasoning: with every cell off the router *is* "do it yourself", so the floor reduces to the install overhead.

## Phase-0 measurements (2026-11-25)

All dollars are **API-equivalent USD**, not bills. Reports are kept locally by the lead; the conclusions are in the
linked closed issues.

| Number | Value | Replaces | Source |
|---|---|---|---|
| Cumulative evaluation spend | **$101.92**: result files $98.10 + `eval-` tagged ledger runs $3.82 | "about $182" | Ledger reconciliation, [#529](https://github.com/SUPERD6/relayline/issues/529) |
| Formal round-2 spend so far | $0 (dry-runs only) | — | [#529](https://github.com/SUPERD6/relayline/issues/529), [STATUS](STATUS.md) |
| Real lead re-read per request (cache read, median) | **225,389** tokens; input total median 228,362; p25 152,060, p75 358,902, p90 545,958; 40,242 requests, 706 sessions, 2026-10-23 to 11-25; weekly medians 151k–284k; this repo's main directory median 304,944 | 352k (one week in October) | [#532](https://github.com/SUPERD6/relayline/issues/532) |
| Install-but-not-used overhead (lead's first request) | ≈ 710 tokens fresh default install (600–1,310), ≈ 470 on the maintainer's machine; 0.31% / 0.21% of 225k; worst case ≈ 1,700 = 0.75% (estimate, ±30%) | — | [#531](https://github.com/SUPERD6/relayline/issues/531) |
| Delegation cost split (26 units, estimate) | lead handover 22.7% of cost / 5.2% of time; work 37.3% / 62.5%; check and review 3.3% / 13.9%; repair or escalation 36.7% / 18.0%. Fixed overhead (handover + sub-agent start + check/review) is only about 19.5% of wall time; serial slowness comes mainly from the sub-agent redoing the work and re-checking, not from handover, and the cost shares are pulled by a few escalation events | — | [#530](https://github.com/SUPERD6/relayline/issues/530) |
| Daily A/B samples (10% of delegable tasks done alone) | 0 | — | [#532](https://github.com/SUPERD6/relayline/issues/532) |

**Why $182 was wrong.** It appears in no repository file and the ledger cannot reproduce it. The repository only
holds two lead estimates ($154 on 2026-11-07, about $165 on 2026-11-16). On the evaluation basis the ledger gives
$101.92 ($80.08 less); on an "everything dispatched" basis it gives $358.48 (it adds Codex sub-agent work priced by
token, $237.44, which is not a bill). Neither equals $182; the $17 step from $165 to $182 has no ledger source
(Unknown). We now manage the budget by the evaluation basis and the script-summed result files.

**What the 225k re-read changes.** The earlier plan set the fat-context diagnostic at 352k tokens. The measured
median is lower and moves from week to week, so the diagnostic now fills the lead to a **main tier of about 225k**
(median re-read) with an optional heavy tier of about 360k (p75 of total input), and reports the weekly spread. The
provisional "install overhead ≤ 1% of the median request" bar becomes ≈ 2,250 tokens instead of ≈ 3,500; the measured
overhead still passes it, but only against real lead contexts: in a thin 11–25k evaluation context the same ≈ 470–710 tokens exceed 1%, so every floor comparison must say so up front. A fresh evaluation session re-reads roughly 10–30k, so the baseline-bias claim (the "do it
alone" arm of every earlier evaluation was far cheaper than real use) holds, by roughly an order of magnitude. Limits:
one machine, one user, and the window starts on 2026-10-23, so the week behind 352k cannot be recomputed; Codex-led
sessions were not recomputed (Unknown).

## Budget

| Item | Evaluation spend (API-equivalent USD) | Source |
|---|---|---|
| Spent so far | **$101.92** (ledger-reconciled; was "about $182") | [#529](https://github.com/SUPERD6/relayline/issues/529) |
| Round 2 formal groups | ≈ $29, worst case ≈ $41 (estimate); report and review ≤ $8 | [preregistration](research/prereg/2026-11-16-round2.md) |
| Fat-context diagnostic | $15–25 (estimate, likely low: smoke test first, stop if $25 buys < 12 tasks) | [#547](https://github.com/SUPERD6/relayline/issues/547) |
| Mechanical-batch experiment | $5–8 (estimate) | [#548](https://github.com/SUPERD6/relayline/issues/548) |
| Floor comparison (mixed tasks) | $15–25 (estimate) | [#557](https://github.com/SUPERD6/relayline/issues/557) |
| Confirmation round (conditional) | $30–45 plus about $10 task selection (estimate) | [#560](https://github.com/SUPERD6/relayline/issues/560) |
| New spend to launch | about $94–162 | sum of the rows above |
| Cumulative at launch | about **$196–264**; $186–254 left under the $450 cap | $101.92 + new spend |
| Optional after launch | parallel cell $15–25; default-change confirmations $20–40 | [#564](https://github.com/SUPERD6/relayline/issues/564) [#565](https://github.com/SUPERD6/relayline/issues/565) |

The $450 cap is hard and only the maintainer may raise it. At $380 cumulative the lead stops and reports the rest of
the plan. Every evaluation measures its unit price (smoke or dev tasks) before the full run and stops if over the line.

## Phases

Order of work: the lead only coordinates; each task is its own sub-session; one issue per PR; every PR gets an
independent read-only review. Models: implementation and docs on the mid tier; high-risk review (over 300 lines,
over 3 source files, or touching `ccx/delegate.py` or the relay start path) and paid evaluations on the strongest tier;
read-only sweeps on the cheap tier. While an evaluation window is open the evaluation machine runs no pytest, so
implementation sessions work in the day and evaluations run at night. Each task's issue states its model, acceptance and
dependencies.

| Phase | Dates (estimate) | Goal | Acceptance | Milestone |
|---|---|---|---|---|
| 0. Free groundwork | 11-25 – 11-30 | Get the numbers later decisions need for free; turn the plan into issues | Five read-only results; issues and milestones exist | [Phase 0](https://github.com/SUPERD6/relayline/milestone/2) |
| 1. Round 2 as preregistered | 11-27 – 12-06 | Five groups each have a verdict | No threshold or task changed; each group archived before the next starts | [Phase 1](https://github.com/SUPERD6/relayline/milestone/3) |
| 2. Relay for real, one-line install | 12-01 – 12-13 | One fully recorded real relay; others can install the latest version in one line | A real quota event page with all fields from real files; 0.8.0 installable | [Phase 2](https://github.com/SUPERD6/relayline/milestone/1) |
| 3. First map | 12-07 – 12-20 | Every cell has today's status; router rule v0 has offline numbers; cell 4 has a diagnostic | Replay, oracle bound, diagnostic and `docs/map.md` published | [Phase 3](https://github.com/SUPERD6/relayline/milestone/4) |
| 4. Simplify, first screen, soft launch | 12-14 – 12-22 | README first screen, advanced page, setup question, small validation | README links stay absolute; no command or switch removed; walkthrough minutes recorded | [Phase 4](https://github.com/SUPERD6/relayline/milestone/5) |
| 5. Floor comparison and article | 12-28 – 01-10 | Floor verdict; honest data article; signal gate on 01-09 | Pass/Fail/Unknown; every article number has sample size, version, date, limit and link | [Phase 5](https://github.com/SUPERD6/relayline/milestone/6) |
| 6. Confirmation and public launch | 01-11 – 01-24 | Confirmation round if the diagnostic qualifies; public launch on 01-19 | README, article and map page agree; every external issue answered within 24 h | [Phase 6](https://github.com/SUPERD6/relayline/milestone/7) |
| 7. After launch | 01-25 – 02-28 | Technical report, parallel cell, default decisions, 1.0 | Each default change has a decision record and two reports | [Phase 7](https://github.com/SUPERD6/relayline/milestone/8) |

### Phase 0: free groundwork (done except T0-7)
[#529](https://github.com/SUPERD6/relayline/issues/529) ledger reconciliation · [#530](https://github.com/SUPERD6/relayline/issues/530) cost split · [#531](https://github.com/SUPERD6/relayline/issues/531) install overhead · [#532](https://github.com/SUPERD6/relayline/issues/532) real use today ·
[#533](https://github.com/SUPERD6/relayline/issues/533) relay gap check (R1–R8, [#520](https://github.com/SUPERD6/relayline/issues/520)–[#527](https://github.com/SUPERD6/relayline/issues/527)) · [#534](https://github.com/SUPERD6/relayline/issues/534) competitor check · [#535](https://github.com/SUPERD6/relayline/issues/535) this roadmap.
T0-1 to T0-6 are closed issues kept as a trace; each holds its conclusion in the body, so the numbers survive without
the lead's local files.

### Phase 1: round 2 as preregistered
[#536](https://github.com/SUPERD6/relayline/issues/536) run A1 → A2 → A1x → A2x → B one group at a time with the formal pin recorded · [#537](https://github.com/SUPERD6/relayline/issues/537) report ·
[#538](https://github.com/SUPERD6/relayline/issues/538) receipt false positive from group B · [#539](https://github.com/SUPERD6/relayline/issues/539) replay two rules on group B rows · [#540](https://github.com/SUPERD6/relayline/issues/540) STATUS.
How results are handled (decided before any result): A1x/A2x Pass → shared context and memory have two passing rounds
on Codex and may be quoted with limits; A group Fail → the evidence goes back to one round, no re-run with more money;
B Fail (expected: the wall-clock bar is ≤ 2× while every past run was 2.7–5.5×) → "same-vendor cheap first" is marked
*tested, not recommended*, the feature stays, group B's rows feed replay and false-positive work, and the one remaining
improvement chance goes to the cross-vendor version in cell 4; B Pass → recorded as is and the preregistered
confirmation round follows; fewer than 59 ordinary `ok` receipts → Unknown, keep accumulating.

### Phase 2: relay for real
The eight relay gaps: [#520](https://github.com/SUPERD6/relayline/issues/520) real-event record template · [#521](https://github.com/SUPERD6/relayline/issues/521) goal carried automatically · [#522](https://github.com/SUPERD6/relayline/issues/522) check command in the
packet and an executed receipt · [#523](https://github.com/SUPERD6/relayline/issues/523) hint when the other vendor's session opens · [#524](https://github.com/SUPERD6/relayline/issues/524) ledger entry for the relay
path · [#525](https://github.com/SUPERD6/relayline/issues/525) Codex → Claude direction (no quota hook in the Codex hooks docs; only `ccx`-started Codex sessions can be
covered) · [#526](https://github.com/SUPERD6/relayline/issues/526) daily quota-event page matches R1 · [#527](https://github.com/SUPERD6/relayline/issues/527) rewrite the first screen of `docs/relay.md` into three steps.
R1 can start now and only waits for an event; R2 and R3 are required before the validation post; R4 is wanted; R5–R8 may
wait for the signal gate. Also [#541](https://github.com/SUPERD6/relayline/issues/541) daily real-use page · [#542](https://github.com/SUPERD6/relayline/issues/542) 0.8.0 release prep (the maintainer publishes to PyPI;
agents never touch credentials) · [#543](https://github.com/SUPERD6/relayline/issues/543) setup and Codex plugin walkthrough. New features are frozen in these two
weeks except this list and problems found in real use. New relay behaviour stays default-off.

### Phase 3: first map
[#544](https://github.com/SUPERD6/relayline/issues/544) offline replay and oracle bound · [#545](https://github.com/SUPERD6/relayline/issues/545) router rule v0 · [#546](https://github.com/SUPERD6/relayline/issues/546) diagnostic arms · [#547](https://github.com/SUPERD6/relayline/issues/547) diagnostic run ·
[#548](https://github.com/SUPERD6/relayline/issues/548) mechanical-batch experiment · [#549](https://github.com/SUPERD6/relayline/issues/549) `docs/map.md`.

### Phase 4: simplify, first screen, soft launch
[#550](https://github.com/SUPERD6/relayline/issues/550) README first screen · [#551](https://github.com/SUPERD6/relayline/issues/551) `docs/advanced.md` · [#552](https://github.com/SUPERD6/relayline/issues/552) setup question · [#553](https://github.com/SUPERD6/relayline/issues/553) 60-second demo from a real
event · [#554](https://github.com/SUPERD6/relayline/issues/554) validation-post drafts (a person reads and posts; agents only draft) · [#555](https://github.com/SUPERD6/relayline/issues/555) newcomer walkthrough.
The demo must record a real event with date, both CLI versions and the commit; no replay passed off as real.

### Phase 5: floor comparison and article
[#556](https://github.com/SUPERD6/relayline/issues/556) preregistration · [#557](https://github.com/SUPERD6/relayline/issues/557) run · [#558](https://github.com/SUPERD6/relayline/issues/558) article draft · [#559](https://github.com/SUPERD6/relayline/issues/559) signal gate. If the floor **Fails**, that is the
most serious result: stop new features, make the default path conservative (with a decision record), and the first
screen cannot say "no worse than the original".

### Phase 6: confirmation and launch
[#560](https://github.com/SUPERD6/relayline/issues/560) confirmation round (only if the diagnostic meets its entry condition: lead-vendor spend ratio ≤ 0.7, correct
count not below "alone" minus 2, not worse than the built-in sub-agent arm; otherwise skipped and cell 4 says "diagnostic
showed no advantage", the efficiency claim shrinks to "does not make things worse") · [#561](https://github.com/SUPERD6/relayline/issues/561) public launch ·
[#562](https://github.com/SUPERD6/relayline/issues/562) launch-day triage.

### Phase 7: after launch
[#563](https://github.com/SUPERD6/relayline/issues/563) technical report (baseline bias in delegation evaluation as the main line; literature search first) ·
[#564](https://github.com/SUPERD6/relayline/issues/564) parallel cell (conditional) · [#565](https://github.com/SUPERD6/relayline/issues/565) default changes (one decision record each) · [#566](https://github.com/SUPERD6/relayline/issues/566) other vendor as lead ·
[#567](https://github.com/SUPERD6/relayline/issues/567) 1.0 (needs two floor passes and 5 real relay events).

## Gates and fallbacks

| Gate | Pass | Unclear | No signal |
|---|---|---|---|
| Independent users saying "I need this" or "I hit this" | ≥ 10 | 3–9 | ≤ 2 |
| External users who installed it and ran it once | ≥ 3 | 1–2 | 0 |
| What people ask about | mostly the relay itself | scattered | mostly "I'll just buy another subscription" |
| Stars (reference only) | ≥ 50 | 10–49 | < 10 |

The lines are the lead's proposal, set from the scale of similar small projects, not an external benchmark. At the
01-09 gate: signal → launch on 01-19; unclear → change only the packaging (title, demo, install), post once more
elsewhere, look again after two weeks, once; no signal and "buy another subscription" → stop adding relay features and
fall back to a personal tool plus an honest evaluation report; no signal but questions concentrate elsewhere → use that
question as the next two-week test, at most one change of angle.

Other exit conditions: no real quota event by 12-20 → the validation post waits (replay is never passed off as real);
the hook never fires in a real event → at most two fix rounds, then a half-automatic "say relay" trigger and drop the
word "automatic"; an official cross-vendor relay appears → re-assess at once; floor Fail → see phase 5; any real event
with two agents writing the same branch → remove relay from the setup recommendations until fixed and tested;
cumulative $380 → stop and report. If time slips by more than a week, cut scope, not discipline: first the mechanical-batch
experiment, then the confirmation round (moved after launch), the launch date last.

## Handoff rules

1. Every task and every phase hand-off goes through a GitHub issue or PR: the issue says what to do, acceptance, the
   model, dependencies, and links the tracker ([#528](https://github.com/SUPERD6/relayline/issues/528)).
2. When a result changes the plan, a PR updates this file and its Chinese twin and adds a line to the adjustment log
   with the reason. Changes to preregistrations, frozen data and registered SHAs follow their own rules, not this file.
3. The lead session checks the roadmap once at the end of each phase and records it in the log (even "no change").
4. Public claims follow the [engineering standards](engineering-standards.md): no number without sample size, version,
   date, limit and report link.

## Adjustment log

| Date | Change | Why | Where |
|---|---|---|---|
| 2026-11-25 | First public version: positioning, three layers, 12-cell map, phases 0–7, issues and milestones | Make the plan adjustable through PRs; tracker [#528](https://github.com/SUPERD6/relayline/issues/528) | [#535](https://github.com/SUPERD6/relayline/issues/535) |
| 2026-11-25 | Spent so far $101.92 instead of about $182; remaining budget $348.08 (cumulative at launch $196–264) | Ledger reconciliation: $182 has no source | [#529](https://github.com/SUPERD6/relayline/issues/529) |
| 2026-11-25 | Fat-context diagnostic filled to a main tier of about 225k (heavy tier about 360k) instead of 352k; install-overhead bar ≈ 2,250 tokens | Measured real lead re-read median 225,389 over 2026-10-23 – 11-25 | [#532](https://github.com/SUPERD6/relayline/issues/532) [#531](https://github.com/SUPERD6/relayline/issues/531) |
| 2026-11-25 | "No high-star project does swap-and-continue" corrected; differentiation narrowed to packet + executed check + receipt + ledger | Orca and `/codex:transfer` found; official changelogs show no automatic cross-vendor relay | [#534](https://github.com/SUPERD6/relayline/issues/534) |
