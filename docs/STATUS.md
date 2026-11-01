# Status

English · [中文](STATUS.zh.md) · updated 2026-11-01 · version 0.5.0 + Unreleased (#105–#241) · 2245 tests collected; full suite not re-run

One page for hand-off. History and older confidence details: [archive](STATUS-archive.md); changes:
[CHANGELOG](../CHANGELOG.md) + [per-PR notes](../changes/README.md). The lead maintains this page.

## Now

**Hold-out run hc1 (2026-10-29, pre-registered):** on 10 tasks not used while building ccx, ccx was not seen to be
less right (29/30 vs self 29/30 and the built-in sub-agent's default usage 27/28) and cost $0.063 per success, about
30 % / 39 % less; about 3× self's wall time. Limits: builtin2 (lean recipe) not in the run, this repository's tasks
may leak answers (external tasks only: 15 % / 42 %), 10 tasks, one lead model.

**Wrap-up merges, 10-30 → 11-01, by the eight layers** (PR details in [changes](../changes/README.md)):

- **① Conversation:** #227 wake-up on by default (Claude inbox tried live; Codex hook experimental); #237 clean results use one line by default; #238 prompt slimming on, experimental; #239 fixed-rule cache prefix alignment, saving not measured.
- **② Memory:** #195 shared-context deduplication experimental, off by default.
- **③ Splitting:** #194 history-free native Codex children and #196 batch merging experimental, off by default.
- **④ Delegation and selection:** #200/#234 `small_self` off (`files` default, `cost` opt-in), `routing.mode=auto`; #230 ability table advisory, not used to route; #240 quota awareness on (fake only); #241 roles opt-in, shipped empty; project role checks display only.
- **⑤ Acceptance and receipts:** #211 coverage/provenance shown; #212 coverage rubric on, own tests are not independent evidence; #223 own-test-only pass labelled `ok_self_checked`, review by default; #215 `[must]` repro gate experimental/off; #235 `--max-usd` default 0 (unlimited); #232 API dollars + quota units, `api` default.
- **⑥ Control:** #231 worktrees default `sibling`, `inside` opt-in/experimental; #193 worktree race retry; #197 hub replacement guarded; #219 eval canaries on by default; #220 sandbox cancellation stops as `env`, resume needs `--env-fixed`.
- **⑦ Measurement and honesty:** #199 lean switches stay off; #221 polyglot negative result; #209 receipt audit 8/209; #216 public `bench/`; #204 evaluation/development sharing one machine/account remains a limitation.
- **⑧ Interface and onboarding:** optional `ccx ui`: #226 project-map home, #233 run views and preview/confirm composer; #202 isolated demo; #207/#208/#210/#218 GIF/screenshots/architecture/site; #228 eight-layer README.

**Safety:** #225 documents the threat model, controls and remaining risks; it adds no execution permission.

| Measurement | Result and limit | Source |
|---|---|---|
| hc1 | self 29/30 $0.090 21 s; built-in default 27/28 $0.103 123 s; ccx 29/30 $0.063 61 s; ccx's two paired cost CIs exclude 0 (built-in − self does not); pointwise rule, not statistical non-inferiority | [hc1](research/2026-10-29-hc1-holdout.md) |
| Polyglot pg1 | self 25/30 vs ccx2 12/30; keep small, strict-interface jobs with the lead; one lead/sub-agent setup, three unclean rows | [pg1](research/2026-10-31-polyglot-pg1.md) |
| B3 lean switches | nomem Unknown; clean Fail; leantools Fail by rule / undecided post hoc; all lean sides off, experimental; no reliable saving shown | [B3](research/2026-10-31-b3-lean-switches.md) |
| False “right” after #158 | report: 8/209 = 3.8%; excluding 18 lead-resumed successes: 8/(209−18) = 8/191 = 4.2%, above 2% bar; repeated tasks, one lead setup; #223 merged, **not re-run** | [audit](research/2026-10-31-verdict-audit.md) |

## Next three

No release date: make this usable every day first (11-01 priority order).

1. **Use it for a week in this and another project:** configure roles, then `ccx run --role build "one sentence"`, UI role buttons and quota awareness; the lead reads `ccx report` daily and opens PRs for small fixes.
2. **Validate P0-8 and recheck false receipts:** one polyglot ccx2 round is about $1.4 ([pg1](research/2026-10-31-polyglot-pg1.md)); results decide whether README's receipt section may quote a number. Not re-run.
3. **Other measurements, release-plan §11 batches:** fewer-runs B3 switches, tier matrix, five large-task groups, external-repository benchmark; one batch at a time, then ask about release.

## How sure we are (short)

**real** = real Windows machine, logged-in CLIs; **fake only** = fake-CLI tests, not a live trial.

- **real:** delegation both ways, `--check`, review (rounds 1–2), `ccx way`, stop/resume and killed-run accounting,
  after-run archiving, DeepSeek leading, three-vendor discuss, board via `say --resume`, shared-context A/B,
  hc1 (90 units, three arms), catalog scan, Claude plugin marketplace install (temporary config), UI test hiding,
  3-task batch (#100), non-ASCII paths, hidden consoles, Windows Codex hooks (H7, #82/#92), queue recovery,
  worktree delegation/undo, parallel Codex+dsh batch, `--fork`, interactive Codex `say --now`/turn hook,
  dsh queued archive after app exit; #227 wake-up into the live Claude desktop lead's inbox;
  the four-PR workflow with Codex implementing and Codex reviewing.
- **fake only:** seats; #240 quota-aware ordering/automatic reassignment; #241 role resolution, CLI/UI checks and `other` fallback. These tests are real engineering checks, not live quota/role-workflow evidence.
- **not verified:** live quota-stop reassignment, real probe cost, installed `gpt-6.1-terra` accounting price;
  macOS/Linux live machines (CI only); Gemini CLI; Codex desktop `say --now`, doctor Codex rule, Codex wake hook,
  dsh's own later archive writes, Codex plugin installed from GitHub, live own-sub-agent limits (F11 did not fire),
  `--review auto` trigger rate, live hook timeout, intake against GitHub, L2 auto-merge end to end, routing outside evals.
  The local plan-review is absent here; CI fixes for `/private/var`, 8.3 short names and `\\?\` prefixes have not been rechecked.

### Pending personal verification (2026-11-01)

Clear these together before building on their outcomes:

- #205: switch required branch checks to `ci-ok` + `personal-data`.
- Configure the test.pypi token.
- Decide global `worktree.location`: `inside` or `sibling` (no project-level setting).
- Confirm GitHub description/topics wording.
- Re-pin Claude desktop app's Pinned Git Origins.
