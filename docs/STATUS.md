# Status

English · [中文](STATUS.zh.md) · updated 2026-11-03 · version 0.5.0 + Unreleased (#105–#253) · 2417 tests collected; full suite not re-run

One page for hand-off. History and older confidence details: [archive](STATUS-archive.md); changes:
[CHANGELOG](../CHANGELOG.md) + [per-PR notes](../changes/README.md). The lead maintains this page.

## Now

**Hold-out run hc1 (2026-10-29, pre-registered):** on 10 tasks not used while building ccx, ccx was not seen to be
less right (29/30 vs self 29/30 and the built-in sub-agent's default usage 27/28) and cost $0.063 per success, about
30 % / 39 % less; about 3× self's wall time. Limits: builtin2 (lean recipe) not in the run, this repository's tasks
may leak answers (external tasks only: 15 % / 42 %), 10 tasks, one lead model.

**10-30 → 11-01 wrap-up, eight layers:** details in [changes](../changes/README.md).
① Wake-up/one-line results/slimming on (Codex wake hook and slimming experimental; #239 cache-prefix saving unmeasured); ② memory deduplication and ③ history-free children/batch merging experimental, off; ④ `routing.mode=auto`, `small_self` off, ability table advisory, quota awareness on, roles opt-in/empty.
⑤ Coverage rubric/review on, own tests not independent, `ok_self_checked` retained, repro gate experimental/off, budget 0/unlimited, billing `api`; ⑥ worktrees default `sibling`, `inside` opt-in/experimental, canaries on, sandbox authorization cancellation (`kind=env`) needs `--env-fixed`; ⑦ lean switches off, negative results retained, #204 evaluation/development share one machine/account; ⑧ optional UI with project map, run views and preview/confirm.

**Merged 11-03** (11 PRs, #243–#253; #250 collects five review-fix rounds):

- **⑤ Receipts #252:** final executor in agent/model/effort; reassignment, budget stops and unavailable reviews reach the lead's one-line result; auto-effort reasons visible. On by default; exit codes and `ok_self_checked` unchanged.
- **④ Readiness #253:** `routing.require_ready=true` prefers installed CLIs with login evidence; explicit negative readiness only demotes, missing-file Unknown does not. Refresh probes candidates (named/role-constrained target: that vendor; otherwise Claude/Codex), not just the eventual pick; empty roles show examples. Roles remain opt-in/empty; existing fallback retained.
- **⑧ Daily UI #249:** budget/review stops, quota age/Unknown, Today spend, multiline role buttons and read/write mode hints in the UI preview. Optional UI; opening it never probes; preview/confirm retained.
- **⑥ Control #246/#244:** `[worktree] fetch=true` warns about upstream lag, never pulls or moves the local base; launcher variables isolated from checks/workers/reviewers by default; background full logs retained.
- **⑦ Evidence #245/#248:** real Claude quota-event/probe-cost samples now replayed in fakes (each recorded probe < $0.005); Codex refusal samples remain synthetic; no routing default change. P0-13 discuss A/B script/preregistration ready, paid execution off without `--execute`; not run.
- **Process #243/#251/#247:** decisions use `changes/<PR>.decision.md`; relayline paths use `workspace.canonical()`; notes normalized and maintenance page lists post-release candidates. Documentation/workflow only; runtime defaults unchanged, no version bump or release.

**Safety:** #225 documents the threat model, controls and remaining risks; it adds no execution permission.

| Measurement | Result and limit | Source |
|---|---|---|
| hc1 | self 29/30 $0.090 21 s; built-in default 27/28 $0.103 123 s; ccx 29/30 $0.063 61 s; ccx's two paired cost CIs exclude 0 (built-in − self does not); pointwise rule, not statistical non-inferiority | [hc1](research/2026-10-29-hc1-holdout.md) |
| Polyglot pg1 | self 25/30 vs ccx2 12/30; keep small, strict-interface jobs with the lead; one lead/sub-agent setup, three unclean rows | [pg1](research/2026-10-31-polyglot-pg1.md) |
| B3 lean switches | nomem Unknown; clean Fail; leantools Fail by rule / undecided post hoc; all lean sides off, experimental; no reliable saving shown | [B3](research/2026-10-31-b3-lean-switches.md) |
| False “right” after #158 | report: 8/209 = 3.8%; excluding 18 lead-resumed successes: 8/(209−18) = 8/191 = 4.2%, above 2% bar; repeated tasks, one lead setup; #223 merged, **not re-run** | [audit](research/2026-10-31-verdict-audit.md) |

## Next three

No release date: make this usable every day first (11-03 priorities).

1. **Use it for a week in this and another project:** roles, quota awareness, daily UI and one-line receipts; the lead reads `ccx report` daily and makes only small fixes.
2. **After approval:** P0-8 validation + false-receipt recheck (about $1.4; [pg1](research/2026-10-31-polyglot-pg1.md), not re-run), plus P0-13 discuss A/B (about $2; [preregistration](research/2026-11-03-p13-discuss-prereg.md), not run). Ready command: `python scripts/eval/p13_discuss.py run --execute --tag p13-r1 --wait-quiet 30 --budget 2`.
3. **Other measurements, release-plan §11 batches (about $49, lead's local plan, not in this repo):** B3 switches, tier matrix, five large-task groups, external benchmark and final hold-out regression; one approved batch at a time, then ask about release. This plan total includes P0-8; do not add it twice.

## How sure we are (short)

**real** = real Windows machine, logged-in CLIs; **fake only** = fake-CLI tests, not a live trial.

- **real:** delegation both ways, `--check`, review (rounds 1–2), `ccx way`, stop/resume and killed-run accounting,
  after-run archiving, DeepSeek leading, three-vendor discuss, board via `say --resume`, shared-context A/B,
  hc1 (90 units, three arms), catalog scan, Claude plugin marketplace install (temporary config), UI test hiding,
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

### Pending personal verification (2026-11-03)

More than three items remain: please clear these first, before building on their outcomes.

- #205: switch required branch checks to `ci-ok` + `personal-data`.
- Configure the test.pypi token.
- Decide global `worktree.location`: `inside` or `sibling` (no project-level setting).
- Confirm GitHub description/topics wording.
- Re-pin Claude desktop app's Pinned Git Origins.
- Decide whether to delete old local branches `control/preflight-e2e`, `debug/b4-queue-flake`, `private-history` (and `claude/silly-fermi` etc. after #205 merges); nothing deleted here.
- Approve P0-8 + P0-13 small measurements now? About $3.4 combined; neither run here.
