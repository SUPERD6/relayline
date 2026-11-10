# Status

English · [中文](STATUS.zh.md) · updated 2026-11-10 · version 0.6.0 released (GitHub Release and PyPI); main is ahead of it, unreleased

One page for hand-off, maintained by the lead. History: [archive](STATUS-archive.md);
changes: [CHANGELOG](../CHANGELOG.md) + [per-PR notes](../changes/README.md).

## Now

**Released:** 0.6.0 (`pipx install relayline`, #265). Main has since merged #266–#316, not yet released; the notes in `changes/` are not yet folded into the CHANGELOG. Goal unchanged ([engineering standards](engineering-standards.md), [optimization plan](research/2026-11-04-optimization-plan.md)): no default regression and one reproducible positive scenario. Current benefit of every new switch below is **Unknown**.

**Evaluation tooling and rounds 2–3 (#271–#277, engineering check, mostly off by default):** test-based review and replay, stage 3 (30 new tasks, candidate default-path groups) and stage 4 (long session) tools, receipt/check-baseline/review/short-task changes, quota relay, cheap first round, review contract, narrower onboarding. Stage 0 (diagnostic, reused tasks; self 30/30, paired cost ratio 1.017 Pass, wall ratio 1.276 Unknown) is in the [hc2 report](research/2026-11-04-hc2-holdout.md).

**Fixes and switches merged since (#290–#316):**
- Windows: `--check` with `export` runs under Git Bash, not PowerShell (#293); preflight output is UTF-8 (#301).
- Before dispatch: a brief that contradicts the run mode fails early (#294); `ccx verify --list` lists results awaiting a verdict (#295).
- Receipts: `ok` is no longer shown as "correct" — runs with no independent check show UNVERIFIED (#296); a timed-out run leaves a changed-files list and the last message, time limit configurable (#304); unfinished Git steps are listed (#309); credential-guard state is recorded per attempt (#305).
- Model busy: switch model, then vendor, instead of retrying the same model (#298, **default on**, can be turned off).
- Off by default: `routing.default = self_first` ([doc](self-first.md), #299); `lead.slim_context` (#300); credential deny rules for sub-agents (#297, **Claude side only**; Codex side has no effective deny rule, open issue #289); optional staging of resolved conflict files by ccx (#309).
- Docs/diagnostics: the home and features pages list the "experimental, tested, not recommended" switches in one place with numbers and sources (#302); `CCX_NO_START_ARCHIVE=1` turns off the start-of-session archive (#310; `CCX_NO_AUTO_ARCHIVE` covers only the after-run archive); number hints (429/401) match as separate words, so UUIDs and hashes no longer read as rate-limit/login problems (#313).
- Tests/tools: tests wait for background maintenance children and the UI thread before cleaning up (#308, #312); read-only evaluation summary script `scripts/eval/unified_summary.py` (per-group successes, paired McNemar, any two groups in p4) (#315).

**Unified test — preregistered, not started:** [pre-registration](research/prereg/2026-11-07-unified.md) merged (#316): this round runs G1 shared context, G2 memory, G3 cheap first round, G4 long task, one switch per group, diagnostic only; G5/G6 moved out of this round. Waiting for Codex quota to recover. Until it runs, nothing here may be described as cheaper or better.

**Existing defaults:** routing auto, quota awareness/review on; `small_self`, lean switches, memory deduplication, history-free children/batch merging and repro gate off/experimental; worktrees `sibling`, `inside` opt-in/experimental; budget 0/unlimited, billing `api`; `memory.by_kind` off/experimental.

| Evidence | Result and limit | Source |
|---|---|---|
| hc2 receipts | 0/19 ordinary `ok` false positives, 95% upper bound about 15%; only 6 `done`, insufficient for the 2% bar; built-in sub-agent not rerun | [hc2](research/2026-11-04-hc2-holdout.md) |
| pg3b | No ordinary `ok` receipts; 15/29 `ok_self_checked` failed hidden tests, review passed all 29 | [pg3b](research/2026-11-03-pg3b-receipts.md) |
| hc1, historical old code | self 29/30 $0.090 21 s; built-in 27/28 $0.103 123 s; ccx 29/30 $0.063 61 s; pointwise rule, not statistical non-inferiority; “about 30% cheaper” does not describe 0.6.0 | [hc1](research/2026-10-29-hc1-holdout.md) |
| Polyglot pg1 | self 25/30 vs ccx2 12/30; small strict-interface tasks, one setup, three unclean rows | [pg1](research/2026-10-31-polyglot-pg1.md) |
| B3 | nomem Unknown; clean Fail; leantools Fail by rule / undecided post hoc; all lean sides off, no reliable saving | [B3](research/2026-10-31-b3-lean-switches.md) |
| False “right” after #158, before #223 | 8/209 = 3.8%; excluding lead-resumed successes 8/191 = 4.2%, above 2%; no sufficient post-#223 retest | [audit](research/2026-10-31-verdict-audit.md) |

## Next three

1. Run the unified test G1–G4 per the [pre-registration](research/prereg/2026-11-07-unified.md) and publish the report (needs Codex quota).
2. Verify #289 with the real Codex CLI: does the credential deny rule take effect on the Codex side?
3. Release: fold `changes/` into the CHANGELOG and bump the version (`scripts/collect_changes.py`, see [changes/README](../changes/README.md)).

## How sure we are (short)

- **real (Windows, logged-in CLIs):** delegation both ways, check/review, stop/resume/accounting, archiving, DeepSeek lead, discuss, board/wake-up, shared-context A/B, hc1/pg3b/hc2 and stage 0, batch/worktrees/undo, non-ASCII paths/hidden consoles, Windows Codex hooks, interactive Codex turns, dsh queued archive, temporary Claude marketplace install, UI test hiding and Codex implementation/review workflow.
- **fake only / engineering (including everything merged since #271):** seats, quota ordering/reassignment, quota relay, model-busy switching, roles, readiness/refresh, one-line outcomes, dashboard, receipt UNVERIFIED display, timeout receipts, Git-pending listing, brief/mode conflict check, self_first, slim_context, Claude-side credential deny rules, summary script. **Real samples replayed:** #245 Claude limit events/four probe readings; Codex refusal samples synthetic, no live automatic reassignment proved ([fixtures](../tests/data/real_signals/)).
- **not verified:** Codex-side credential deny rules (#289); live quota-stop reassignment, macOS keychain readiness (missing credentials = Unknown), real offline/slow fetch timeouts, installed `gpt-6.1-terra` accounting price; macOS/Linux live machines (CI only), Gemini CLI, Codex desktop `say --now`/doctor rule/wake hook, dsh later archive writes, GitHub Codex plugin install, live own-sub-agent limits, `--review auto` trigger rate, live hook timeout, GitHub intake, L2 auto-merge end to end, routing outside evals; effect of every switch listed above on cost or success (Unknown until the unified test runs).
- **known issues:** open: #289 only.

### Pending personal verification (2026-11-10)

- Quota relay desktop hook: 1-minute check ([docs/relay.md](relay.md)).
- Create a Codex login directory for evaluations.
- Carried over: confirm GitHub description/topics wording; re-pin Claude desktop app's Pinned Git Origins.
