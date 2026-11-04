# Status

English · [中文](STATUS.zh.md) · updated 2026-11-04 · version 0.6.0 (GitHub Release and PyPI published)

One page for hand-off, maintained by the lead. History: [archive](STATUS-archive.md);
changes: [CHANGELOG](../CHANGELOG.md) + [per-PR notes](../changes/README.md).

## Now

**Released:** 0.6.0 is on GitHub Releases and PyPI; install with `pipx install relayline` (#265).
The [engineering standards](engineering-standards.md) and [optimization plan](research/2026-11-04-optimization-plan.md) merged (#266). The goal is no default regression and one reproducible positive scenario; current benefit remains **Unknown**.

**Stage 0 — measured, diagnostic, reused tasks, not final evidence:** self scored 30/30, $0.0989 per success, median wall 26.9 s, `env_clean` 30/30, total $2.97. Under the preregistered rules, self's paired cost ratio 1.017 is **Pass** (cost growth is not on the lead side); paired wall ratio 1.276 is in the gray zone (**Unknown**). Same-version hc2 ccx2: 28/30, $0.0861 per success, median wall 169 s, run at a different time. These diagnostics do not establish current-version savings. [hc2 report](research/2026-11-04-hc2-holdout.md)

**Sandbox — measured:** WinError 5 occurred only with TMP outside the workspace; default system Temp worked. This is an evaluation-condition issue ([report](research/2026-11-04-sandbox-tmp.md)).

**Stage 1 — engineering check, effects Unknown:** merged #267 (user's original wording), #268 (hooks/report speed), #269 (evaluation temporary directories/event stream), #270 (`small_self_run` + `strict_escalate`); **#271 pending merge** (test-based review/replay scripts). All are off by default or evaluation-only. #268 synthetic timings: report 336→97 ms; archive hook path 914→5 ms (scheduling only, not completed archive work).

**Existing defaults/history:** routing auto, quota awareness/review on; `small_self`, lean switches, memory deduplication, history-free children/batch merging and repro gate off/experimental; worktrees `sibling`, `inside` opt-in/experimental; budget 0/unlimited, billing `api`. #243–#262 and the eight-layer wrap-up are in the changelog/archive. GIF, blog post and a new H11 trial were waived for 0.6.0 (lead proposed, person did not object); `memory.by_kind` stays off/experimental. #225 documents safety controls and risks, adding no permission.

| Evidence | Result and limit | Source |
|---|---|---|
| hc2 receipts | 0/19 ordinary `ok` false positives, 95% upper bound about 15%; only 6 `done`, insufficient for the 2% bar; built-in sub-agent not rerun | [hc2](research/2026-11-04-hc2-holdout.md) |
| pg3b | No ordinary `ok` receipts; 15/29 `ok_self_checked` failed hidden tests, review passed all 29 | [pg3b](research/2026-11-03-pg3b-receipts.md) |
| hc1, historical old code | self 29/30 $0.090 21 s; built-in 27/28 $0.103 123 s; ccx 29/30 $0.063 61 s; pointwise rule, not statistical non-inferiority; “about 30% cheaper” does not describe 0.6.0 | [hc1](research/2026-10-29-hc1-holdout.md) |
| Polyglot pg1 | self 25/30 vs ccx2 12/30; small strict-interface tasks, one setup, three unclean rows | [pg1](research/2026-10-31-polyglot-pg1.md) |
| B3 | nomem Unknown; clean Fail; leantools Fail by rule / undecided post hoc; all lean sides off, no reliable saving | [B3](research/2026-10-31-b3-lean-switches.md) |
| False “right” after #158, before #223 | 8/209 = 3.8%; excluding lead-resumed successes 8/191 = 4.2%, above 2%; no sufficient post-#223 retest | [audit](research/2026-10-31-verdict-audit.md) |

## Next three

1. **Stage 2:** replay test-based review; catch rate ≥ 50%, false-block rate ≤ 20% (engineering check).
2. **Stages 3 and 4:** fresh-task and large-task evaluations; thresholds in the [plan](research/2026-11-04-optimization-plan.md).
3. **Stage 5:** repeat and benchmark external issues, then decide public positioning. **Total hard cap: $60**, including failures/interruption; stop at 1.5× a stage's estimate ceiling.

## How sure we are (short)

- **real (Windows, logged-in CLIs):** delegation both ways, check/review, stop/resume/accounting, archiving, DeepSeek lead, discuss, board/wake-up, shared-context A/B, hc1/pg3b/hc2 and stage 0, batch/worktrees/undo, non-ASCII paths/hidden consoles, Windows Codex hooks, interactive Codex turns, dsh queued archive, temporary Claude marketplace install, UI test hiding and Codex implementation/review workflow. #243–#254 exceptions: #248 no Claude review (quota), #250 lead cherry-pick, #244/#246 fixes accepted outside sandbox.
- **fake only / engineering:** seats, quota ordering/reassignment, roles, readiness/refresh, one-line outcomes, dashboard and stage 1. **Real samples replayed:** #245 Claude limit events/four probe readings (< $0.005 each); Codex refusal samples synthetic, no live automatic reassignment proved ([fixtures](../tests/data/real_signals/)).
- **not verified:** live quota-stop reassignment, macOS keychain readiness (missing credentials = Unknown), real offline/slow fetch timeouts, installed `gpt-6.1-terra` accounting price; macOS/Linux live machines (CI only), Gemini CLI, Codex desktop `say --now`/doctor rule/wake hook, dsh later archive writes, GitHub Codex plugin install, live own-sub-agent limits (F11 did not fire), `--review auto` trigger rate, live hook timeout, GitHub intake, L2 auto-merge end to end, routing outside evals. Local plan-review absent; CI fixes for `/private/var`, 8.3 short names and `\\?\` prefixes not rechecked.

### Pending personal verification (2026-11-04)

- ~~#205 required checks~~: API confirmed `ci-ok` + `personal-data`; ~~TestPyPI/PyPI tokens~~: published; ~~old personal paths~~: keep history; ~~old local branches~~: deleted, backups retained; ~~`worktree.location`~~: keep default `sibling`.
- Confirm GitHub description/topics wording.
- Re-pin Claude desktop app's Pinned Git Origins.
- Approve P0-13 (about $2)? Not running. ~~Self rerun on the hold-out set~~: completed in stage 0.
