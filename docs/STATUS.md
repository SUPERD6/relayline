# Status

English · [中文](STATUS.zh.md) · updated 2026-11-04 · version 0.6.0 (tag and PyPI: see Next three)

One page for hand-off. History and older confidence details: [archive](STATUS-archive.md); changes:
[CHANGELOG](../CHANGELOG.md) + [per-PR notes](../changes/README.md). The lead maintains this page.

## Now

**Recheck on the 0.6.0 candidate (hc2, 2026-11-04, pre-registered):** 28/30 right on the hold-out tasks (clean rows 25/27), $0.088 per success, median wall 168 s; self and the built-in sub-agent were **not rerun**. 19 ordinary `ok` receipts had no false positive in this run: that is all it shows (95 % upper bound about 15 %, only 6 with `status=done`), not below 2 %. Rule 3 of the pre-registration was ambiguous; the lead read it as a proportion and says so in the [report](research/2026-11-04-hc2-holdout.md). Cost and wall were higher than hc1 (paired +32 % / +157 %); code, sandbox and Claude version all changed, so no cause is isolated and no product slowdown is established. **hc1 (2026-10-29, old code) is now a historical experiment:** its "about 30 % cheaper" does not describe this version.

**10-30 → 11-01 wrap-up, eight layers:** details in [changes](../changes/README.md).
① Wake-up/one-line results/slimming on (Codex wake hook and slimming experimental; #239 cache-prefix saving unmeasured); ② memory deduplication and ③ history-free children/batch merging experimental, off; ④ `routing.mode=auto`, `small_self` off, ability table advisory, quota awareness on, roles opt-in/empty.
⑤ Coverage rubric/review on, own tests not independent, `ok_self_checked` retained, repro gate experimental/off, budget 0/unlimited, billing `api`; ⑥ worktrees default `sibling`, `inside` opt-in/experimental, canaries on, sandbox authorization cancellation (`kind=env`) needs `--env-fixed`; ⑦ lean switches off, negative results retained, #204 evaluation/development share one machine/account; ⑧ optional UI with project map, run views and preview/confirm.

**Merged 11-03 → 11-04:** #243–#262, in the [0.6.0 changelog](../CHANGELOG.md): readiness-aware routing (#253), receipts naming the final executor (#252) and no longer reading `check_failed` as right (#261), daily UI (#249), memory-suggestion filtering and batch accept/reject (#257, #260), `needs_lead` hints on the repair chain (#258), evaluation summaries separating completion from correctness (#256), outward numbers rewritten (#262).

**Waived for 0.6.0 (lead's proposal, the person did not object):** GIF, blog post (release notes stand in), new H11 trial (`memory.by_kind` stays off, experimental).

**Safety:** #225 documents the threat model, controls and remaining risks; it adds no execution permission.

| Measurement | Result and limit | Source |
|---|---|---|
| hc2 (0.6.0 candidate) | ccx 28/30 (clean 25/27), $0.088, 168 s; self and built-in not rerun; 0/19 false positives, upper bound about 15 % | [hc2](research/2026-11-04-hc2-holdout.md) |
| pg3b receipts | 0 ordinary `ok` receipts: insufficient evidence for the 2 % bar; 15 of 29 `ok_self_checked` failed hidden tests and review passed all 29 | [pg3b](research/2026-11-03-pg3b-receipts.md) |
| hc1 (historical, old code) | self 29/30 $0.090 21 s; built-in default 27/28 $0.103 123 s; ccx 29/30 $0.063 61 s; pointwise rule, not statistical non-inferiority | [hc1](research/2026-10-29-hc1-holdout.md) |
| Polyglot pg1 | self 25/30 vs ccx2 12/30; keep small, strict-interface jobs with the lead; one lead/sub-agent setup, three unclean rows | [pg1](research/2026-10-31-polyglot-pg1.md) |
| B3 lean switches | nomem Unknown; clean Fail; leantools Fail by rule / undecided post hoc; all lean sides off, experimental; no reliable saving shown | [B3](research/2026-10-31-b3-lean-switches.md) |
| False “right” after #158 | 8/209 = 3.8 %; excluding 18 lead-resumed successes 8/191 = 4.2 %, above the 2 % bar; before #223. After #223 no retest has enough `done` receipts to measure the bar (hc2: 6) | [audit](research/2026-10-31-verdict-audit.md) |

## Next three

1. **Publish 0.6.0:** tag, full-matrix CI and GitHub release by the lead; TestPyPI and PyPI wait for the person's tokens. After PyPI, switch the install lines to `pipx install relayline`.
2. **Use it for a week in this and another project:** the lead reads `ccx report` daily and makes only small fixes.
3. **After approval:** rerun self on the hold-out set to separate code from environment in the hc1 → hc2 rise; P0-13 discuss A/B (about $2; [preregistration](research/2026-11-03-p13-discuss-prereg.md), not run).

## How sure we are (short)

**real** = real Windows machine, logged-in CLIs; **fake only** = fake-CLI tests, not a live trial.

- **real:** delegation both ways, `--check`, review (rounds 1–2), `ccx way`, stop/resume and killed-run accounting,
  after-run archiving, DeepSeek leading, three-vendor discuss, board via `say --resume`, shared-context A/B,
  hc1 (90 units, three arms), pg3b and hc2 (30 units each, ccx only), catalog scan, Claude plugin marketplace install (temporary config), UI test hiding,
  3-task batch (#100), non-ASCII paths, hidden consoles, Windows Codex hooks (H7, #82/#92), queue recovery,
  worktree delegation/undo, parallel Codex+dsh batch, `--fork`, interactive Codex `say --now`/turn hook,
  dsh queued archive after app exit; #227 wake-up into the live Claude desktop lead's inbox;
  the four-PR workflow with Codex implementing and Codex reviewing.
  The Codex implementation + Codex/Claude cross-review workflow was used across #243–#254, with exceptions:
  #248 lacked Claude review (quota limit); #250 was lead cherry-picking; #244/#246 fix rounds were accepted by the lead outside the sandbox.
- **fake only:** seats; #240 quota ordering/automatic reassignment; #241 roles/`other`; #253 readiness/refresh scope; #252 one-line outcomes; #249 dashboard. Engineering checks, not live workflow evidence.
- **real samples, replayed:** #245 Claude limit events and four probe-cost/window readings, each probe < $0.005; Codex refusal samples remain synthetic; no live automatic reassignment proved ([fixtures](../tests/data/real_signals/)).
- **not verified:** live quota-stop reassignment, macOS keychain readiness (missing credential files stay Unknown), worktree-fetch timeouts on real offline/slow networks, installed `gpt-6.1-terra` accounting price;
  macOS/Linux live machines (CI only); Gemini CLI; Codex desktop `say --now`, doctor Codex rule, Codex wake hook,
  dsh's own later archive writes, Codex plugin installed from GitHub, live own-sub-agent limits (F11 did not fire),
  `--review auto` trigger rate, live hook timeout, intake against GitHub, L2 auto-merge end to end, routing outside evals.
  The local plan-review is absent here; CI fixes for `/private/var`, 8.3 short names and `\\?\` prefixes have not been rechecked.

### Pending personal verification (2026-11-04)

More than three items remain: please clear these first, before building on their outcomes.

- #205: switch required branch checks to `ci-ok` + `personal-data`.
- Configure the TestPyPI and PyPI tokens (in `~/.pypirc` or one shell, never in chat).
- Decide whether Git history keeps old personal paths (`git log -S`): the lead leans towards leaving it.
- Decide global `worktree.location`: `inside` or `sibling` (no project-level setting).
- Confirm GitHub description/topics wording.
- Re-pin Claude desktop app's Pinned Git Origins.
- Decide whether to delete old local branches `control/preflight-e2e`, `debug/b4-queue-flake`, `private-history` (and `claude/silly-fermi` etc. after #205 merges); nothing deleted here.
- Approve P0-13 (about $2) or a self rerun on the hold-out set? Neither is running.
