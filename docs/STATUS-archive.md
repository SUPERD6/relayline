# Status archive

English · [中文](STATUS-archive.zh.md) · moved out of [STATUS.md](STATUS.md) on 2026-10-24 (proposal J6: STATUS.md is one page now). Older notes, the full confidence table, acceptance checks and the done list, as they stood then; newer items go to CHANGELOG.md.

## STATUS.md as of 2026-11-19, moved here on 2026-11-24

The "merged since" list of #440–#471, the round-2 preparation paragraph, "Next three" and the known-issues bullet, as they stood in STATUS.md on 2026-11-19 (updated 2026-11-24 in the new STATUS.md).

**Merged since (PRs #440–#471, 2026-11-18 to 11-19).** All unreleased; no default changed; the effect of every switch is **Unknown**. Everything before #440 (#267–#439: stage 1 to 3 tooling, fixes and switches, merge paths, routing cold start, cost-cutting switches) is in the [archive](STATUS-archive.md). Merged: #443 STATUS; #444 round-2 `prepare` no longer reports a failed pinned download as installed, exit code 1 when pytest is missing (#442); #445 `ccx doctor --backfill-kinds` fills `kind_counts` from old run records (#440); #448 pre-registration change record, group C deferred to round 3; #450 round-2 B newly authored tasks (generator script, two starter repositories, 4 development tasks) (#375); #453 P4 `--hide PATH` (#451); #455 group A units are denied the running checkout and task data by default, `--hide`, tool-call path audit (#454); #459 pre-registration change record for A and B isolation (#458); #460 `canon()` no longer reads a single-letter folder after a drive as a Git Bash drive (#456); #462 pinned "now" in a `context_share` test, fixes a failure around midnight (#457); #463 `check_authored` runs the existing and the hidden tests on the reference tree (#452); #465 quota cache test no longer depends on file mtime resolution (#464); #466 dropped the `strength_runner` canon wrapper (#461); #469 correction of the published G1 result (#468); #471 strength units no longer get or read answer files, the `off` arm gets no answer files, and sibling units and run files are added to the no-read list (#467). **In progress:** #472 (open, not merged): a strength unit must not read other units' session records in the shared login home (#470).

**Round 2 preparation (2026-11-19).** Design: [pre-registration](research/prereg/2026-11-16-round2.md) (#369), change record up to #458. Round 2 now runs A + B; group C is deferred to round 3 (maintainer, 2026-11-18, #448), so there are 56 development units. A task sets are frozen (#407). B: 4 development tasks written and checked (#450); the full upstream selection gave **36/60** (C pushed to round 3), and the 51 repositories from rank 239 on (azure-sdk-for-python and later) were recorded as "not in --ext-cache" because of a transient `git log` failure, not because they have no tasks; only those 51 are being rerun now (equivalence check posted on #375). Newly authored tasks are validated by running the whole suite (#463). Isolation: the answer files are no longer on directly readable paths (#453, #455, #460, #471 merged, record #459), but the gap of session records in the shared login home is not closed yet (#470/#472 open, not merged).

**Next three (as of 2026-11-19):**

1. Round 2 task sets: when the rerun of the 51 selection repositories finishes, settle how many B final tasks must be newly authored (36 upstream + rerun yield, up to 60) and write them (generator `scripts/eval/round2_bc/`); then the B SHA change record.
2. Isolation, last item: merge #472 (session records in the shared login home), then fold all isolation changes (`off` arm content, no-read rules, session records) into one pre-registration change record; `PIN` is then taken from main after that.
3. Check the cost of the 56 development units, then start A1. Budget: cumulative evaluation cap $450 (maintainer, 2026-11-16), about $165 spent as of 2026-11-16 (lead session's report). Authoring cost: the maintainer's 2026-11-18 decision (C to round 3) already approves group B's newly authored tasks (4 development tasks plus the final tasks needed to reach 60); group C's authoring cost does not occur.

- **known issues:** open: #375 (second-round task sets: B remaining), #470/#472 (session records in the shared login home), #446 (pinned numpy 2.5.0 / scipy 1.18.0 do not install on Python 3.11, left unfixed, 69 candidates), #449 (switch to skip C in `select`), #411 (decisions draft: the maintainer approved all 9 answers on 2026-11-19; the author syncs the text, then it merges). #442, #440, #451, #454, #456, #452 are fixed and closed; #468 closes with this PR. **Limit:** upstream selection yield is low and Windows-biased. Systematically excluded on this machine: compiled repositories, localized time-zone names (dateutil, 12 candidates), pytest plugin conflicts (14), werkzeug file locking (39), the embedded-copy check (idna, urllib3; the leak risk is real, rule kept), and #446 (69); the task sets are not a sample of all Python projects, so round 3 should select again on Linux. The audit is a backstop: Codex units cannot be confined (`codex exec` has no read-deny option), only audited afterwards. Claude deny wildcard matching has not been verified with a real CLI. PyPI is still 0.6.0 (0.7.0 waits for the maintainer). Still unverified from before: no local plan-review; CI fixes for `/private/var`, 8.3 short names and `\\?\` prefixes not rechecked; live own-sub-agent limits (F11 did not fire).

## STATUS.md as of 2026-11-18, moved here on 2026-11-19

The per-PR "merged since" lists of #267–#439 and the stage 1 paragraph, as they stood in STATUS.md on 2026-11-18 (the unified-test paragraph stays in STATUS.md with its G1 correction; see the [unified report](research/2026-11-14-unified.md)).

**Stage 1 and later tooling, rounds 2–3 (#267–#277, engineering check, mostly off by default):** #267 passes the user's original wording to sub-agents; #268 moves archiving to the background and reads the ledger once per report (speed, scheduling only; effect on completed work not measured); #269 puts evaluation temporary directories in the workspace and keeps the event stream; #270 adds `small_self_run` and a guard on the cheapest tier. Then #271 test-based review and replay, #273 fixes from the first replay, #274 stage 3 tools (30 new tasks, candidate default-path groups), #275 stage 4 tools (long session), #276 second round (receipts, check baseline, review, short-task overhead) and #277 third round (quota relay, cheap first round, review contract, narrower onboarding). **Stage 0** (diagnostic, reused tasks; self 30/30, paired cost ratio 1.017 Pass, wall ratio 1.276 Unknown; same-version hc2 ccx2 was run at a different time) is diagnostic only and is not evidence of current-version savings: [hc2 report](research/2026-11-04-hc2-holdout.md). **Sandbox:** WinError 5 occurred only with TMP outside the workspace, so it is an evaluation-condition issue ([report](research/2026-11-04-sandbox-tmp.md)).

**Fixes and switches merged since (#290–#316):**

- Windows: `--check` with `export` runs under Git Bash, not PowerShell (#293); preflight output is UTF-8 (#301).

- Before dispatch: a brief that contradicts the run mode now warns; only `--strict-brief` (experimental, off by default) refuses (#294); `ccx verify --list` lists results awaiting a verdict (#295).

- Receipts: `ok` is no longer shown as "correct" — runs with no independent check show UNVERIFIED (#296); a timed-out run leaves a changed-files list and the last message, time limit configurable, timeout reminder `defaults.timeout_reminder` off by default (#304); unfinished Git steps are listed (#309); credential-guard state is recorded per attempt (#305; the credential guard itself is off by default, see below).

- Model busy: switch model, then vendor, instead of retrying the same model (#298, **default on**, can be turned off).

- Off by default: `routing.default = self_first` ([doc](self-first.md), #299); `lead.slim_context` (#300); credential deny rules for sub-agents (#297, **Claude side only**; Codex side has no effective deny rule, open issue #289); optional staging of resolved conflict files by ccx (#309); `defaults.timeout_reminder` (#304).

- Docs/diagnostics: the home and features pages list the "experimental, tested, not recommended" switches in one place with numbers and sources (#302); `CCX_NO_START_ARCHIVE=1` turns off the start-of-session archive (#310; `CCX_NO_AUTO_ARCHIVE` covers only the after-run archive); number hints (429/401) match as separate words, so UUIDs and hashes no longer read as rate-limit/login problems (#313).

- Tests/tools: tests wait for background maintenance children and the UI thread before cleaning up (#308, #312); read-only evaluation summary script `scripts/eval/unified_summary.py` (per-group successes, paired McNemar, any two groups in p4) (#315).

**Merged since (PRs #317–#333):** #317 STATUS; #319 relay desktop check via terminal `/hooks` or `~/.claude/settings.json` (#318); evaluation fixes #322 (`strength_retest --codex-home`), #323 (receipt `status=error` stops the group and is invalid in the summary), #328 (Codex unit TMP inside the workspace), #331 (runner timeout ends the whole process tree); pre-registration change log #324; #333 `[check] sensitivity = off|warn|escalate` (**off by default**, experimental): flags a `--check` that already passed before the change and, under `escalate` with cheap_first, treats it as unverified.

**Merged since (PRs #338–#342 and #344, follow-ups from the unified test):** #338 delegation guidance: write a check that fails before the change, with concrete inputs and expected outputs in the brief (#326; skill text, `--check` help and a hint when no `--check` is given, no behaviour change); #339 `[run] stall_minutes` (**off by default**, experimental): stop a sub-agent with no output for that long, receipt `timeout` + `stalled` (#330); #340 sub-agents in `--worktree` no longer commit, the receipt lists uncommitted files in `commit_state`, Codex sandbox not widened (#334); #341 `ccx run --base head|upstream` / `[worktree] base` (default `head`), warns before the run when the base is behind (#336); #342 eval scripts end the whole process tree on timeout via a shared `run_tree` (#332); #344 sub-agent output decoded from bytes, UTF-8 first, then the local code page, no replacement characters (#335; the garbling seen on 2026-11-14 was on the reading side: Python printing JSON through a pipe on Chinese Windows uses GBK).

**Merged since (PRs #352–#369).** In 0.7.0: #354 `ccx ui` shows a stalled run with its own text (#343); #357 release 0.7.0; #363 delegation guidance on the worktree base (#351); evaluation tooling #355/#358 (p4 cheap-first v2 arm, #346) and #356 `scripts/eval/round2_tasks.py` (#348). After the tag: #352 credential guard on the Codex side (**off by default**, experimental): a Codex permission profile with filesystem deny entries replaces ccx's `sandbox_mode`, bypassing arguments are refused before start, on Windows only the elevated sandbox is accepted; receipts count denied reads per attempt for both vendors without attributing them to the guard (#289); #361 the one-line receipt keeps a compact `commit_state` (#350); #364, #366, #368 evaluation-script follow-ups (#348, #345, #347); #369 the [second-round pre-registration](research/prereg/2026-11-16-round2.md) (design only, not run).

**Merged since (PRs #382–#409, 2026-11-17).** All unreleased; no default changed, effect of each still **Unknown**. *Evaluation scripts (do not start sub-agents; only #389, #390, #405 are read-only, the others change waiting, process-kill or clone/baseline behaviour):* `src/` on PYTHONPATH for p4 scoring and round-2 runs (#382, #385); cheap-first v2 summary (#386); B/C development-task selection (#387, #399); receipt false-positive count (#389), handover-overhead split (#390), offline ledger replay (#405); process-tree kill on timeout (#395, #408). *Merge paths:* `ccx autonomy merge` (#388) and `ccx q accept` (#401) merge the original run's branch for a resumed run and refuse a detached or switched-away worktree. *Tests and CI:* the stuck Ctrl+C test fixed at its root and CI test job `timeout-minutes: 90` (#393); wait for real process exit with the Job Object off (#394). *Automatic model choice (visibility only):* `ccx run --dry-run` prints the rung choice with reasons, ledger and receipt record `planned_first_rung` / `actual_first_rung` (#398). *Daily use and timing:* `ccx report --daily` one-page real-use record (#406); handover timing fields in run records and ledger (#409). *Evaluation records:* seven Chinese pre-registration summaries (#404); round-2 A-group task sets, 112 tasks, offline validation and SHA manifest (hash `c7bc6a6d…`; B/C not yet) (#407).

**Merged since (PRs #410–#439, 2026-11-17 to 11-18).** All unreleased; no default changed; the effect of every switch is **Unknown**. *Round-2 selection and leak checks:* selection environment fixed (#416; selection is still blocked by #442), embedded pip/setuptools copies in `ext-python` scanned (#422), clone cache keyed by owner/name (#423), the 10-minute pytest limit applied per repository, declared pytest plugins loaded explicitly with a deny list, tag-versioned stubs (#425); pre-registration change records (#421, #431); A-group task sets frozen (#407). *Merge paths:* `branch_landed` follows the worktree's current commit (#412) and recognises squash / cherry-pick / rebase landings (#420). *Tests:* `preflight.kill()` waits for the process to exit (#410). *Automatic model choice and routing:* cold-start table by task category, yielding fully when the user pins the choice (#426/#436, #437/#439; `routing.cold_start`, **off by default**, experimental); offline calibration script `routing_calibration.py` (#429/#432): the real ledger cannot yet give a threshold; `ccx ab` samples record the same size signals as delegated runs (#433/#438). *Cost-cutting switches (both **off by default**, experimental):* `[review] skip_when_clean` skips automatic review on a clean run, a set of mechanical conditions that must all hold, including sensitivity = sensitive (#427/#434); `[brief] slim` trims the sub-agent brief (#428/#435). *Relay:* packet `captured_at` and continue record `started_at` in UTC (#414/#419).

## STATUS.md as of 2026-10-26 (0.5.0), moved here on 2026-10-29

### Now

0.5.0 holds everything since 0.4.0 (PRs up to #104), grouped by theme in the CHANGELOG. What the measurements
say, each from a raw record:

| Result | Numbers | Source |
|---|---|---|
| Shared work context (`ccx run --context`) | right the first time 36/36 with it vs 7/36 without (McNemar p ≈ 4e-9), 0 vs 29 reworks, 63 % less spend in all; best case by design | [shared-context A/B](research/2026-10-25-shared-context-ab.md) |
| Project memory reaches the sub-agent | hidden test 9/9 with the note vs 0/9 without (Holm p = 0.016) | [seven-cores A/B](research/2026-10-24-seven-cores-ab.md) §2.5 |
| Hub memory (note only in the shared hub) | 9/9 vs 0/9 (McNemar p = 0.0039); control is round 1's arm, one note per hub | CHANGELOG 0.5.0 (PR #45); no separate report |
| Cheap model is near the ceiling (round 2) | 22 trap tasks, Codex luna low right 47/49; every "more right" gap below comes from one task (inventory), so none is significant | [round 2](research/2026-10-25-seven-cores-r2.md) |
| Review (round 2) | off 33/36, on 36/36 (p = 0.25), caught the real bug every time, +$0.004 a task; the old `--review auto` never fired (fixed in #103, real trigger rate not measured yet) | same, 4-C |
| Dividing the work (round 2) | one cheap model 12/14; plan → build → accept 14/14 at 38.7× the spend; draft + checked draft 14/14 at 20×; cheap model + cheap review gets the same at ~7 % of `ccx way`'s cost | same, 4-B |
| Parallel runs (round 2) | ten pieces: 1 run 68–83 s, 10 runs 29–31 s, but tokens 210k → 980k (~93k start-up per run): faster, not cheaper | same, §5 |
| Delegating (round 1) | the lead's tokens −32 % but total spend the same (ratio 1.02) | [seven-cores A/B](research/2026-10-24-seven-cores-ab.md) §2.2 |
| Routing (rounds 1–2) | no gain in round 1 (21/21 the fixed model); round 2 as right as fixed sonnet, its saving came from the test hub not knowing the quota | round 1 §2.3, round 2 4-D |
| More accurate with use | no evidence yet (everything was right, so nothing to learn from) | round 2 §6 |
| ccx vs Claude Code's own sub-agent (round 3) | harder, vaguer tasks, sonnet lead: all three arms 20/20 (ceiling again); cost per success self $0.045, built-in $0.069, ccx $0.071; ccx −25 % lead tokens vs built-in (p = 0.021) but same total (1.02) and 26 s slower; fresh short lead sessions only | [round 3](research/2026-10-25-r3.md) |
| Memory fixed cases (L5) | note used 15/24 with memory vs 2/24 without (p = 0.0002); one note never reached the brief (word splitting kept punctuation; fixed in #116) | same |
| Warm lanes (`--lanes`, off) | vs 10 parallel runs ~40 % cheaper but 2–3× slower; vs one run doing all 10 pieces 4–5× dearer: fewer runs is what saves | [warm lanes](research/2026-10-25-warm-lanes.md) |
| Cheap models on the raw request (round 4) | no lead, 15 tasks × 2: deepseek-flash 30/30, haiku 30/30, luna 26/30, sonnet 30/30 at ~10× the spend; review rescued luna's 4 failures (4 : 0, p = 0.125) | [round 4](research/2026-10-26-r4.md) |
| Long lead session (round 4) | ~110k tokens of history, 5 tasks: all 5/5; cost per success self $0.567, ccx $0.595, built-in $0.613; the lead makes 4–7 requests either way, each re-reading the history, so delegating small tasks does not save | same |
| Large tasks, real changes (round 5) | 10 tasks × 2: self 19/20 $0.211 per success, built-in 19/20 $0.155, ccx 17/20 $0.248, a cheap model alone 16/20 $0.054; ccx −176k lead tokens vs self (p = 0.002) but the same total, built-in $0.044 cheaper than ccx (p = 0.021); ccx's review raised issues in 10 units without raising correctness | [round 5](research/2026-10-26-r5.md) |
| Round 5 follow-up (#126–#129) | ccx as the skill now teaches it: 19/20 then 20/20 at $0.131 / $0.116 per success, beside builtin 17/20 at $0.202: the cheapest way to delegate with a lead and faster than builtin, still ~2.7× self's wall time; the lean lead recipe alone cut cost but also correctness (builtin2 17/20) | same, §7 |
| Memory search (L1 BM25) / suggested notes | relevant in top 3: 7 → 11 of 13; suggestion rules 13/30 → 22/30 (no longer held out), real hub 3/8 → 8/8 | #112, #113 |

So the default shape is **one cheap model plus another vendor's cheap review**; split or parallel only when speed
is wanted (the `project-manager` skill, #102). Running: the H11 week-long `ccx trial` (ends 2026-11-01). Since the
0.5.0 tag: `q resume` continues the killed run's session (#105); coordinator K4 autonomy levels (`ccx autonomy`,
default L1, #109), K5 work sent in from a private GitHub issue (`ccx intake`, #110), K6 the cross-project board with
confirmed buttons (#111); memory L1–L3 (#112, new switches off until the trial ends), L4 hook timeout, L6 cold start,
L7 `ccx skills stats` (#113); warm lanes (#114, off); round 3 (#115; L8 not worth doing: finding files is 1.9 % of
sub-agent tokens); brief word splitting fixed and a `recap` line at the end of `ccx run` output (#116).

### Next three

1. **Going public** (ask the person first): demo GIF, a public benchmark from the round-1/2/3 tasks, then the launch.
2. **After the trial (2026-11-01)**: read the H11 results; decide on `memory.by_kind` / `memory.start_scene`, cheap
   rung first for clear small tasks, review on for writes, a one-line result for the lead; J0 re-measure (no
   real runs 11/1–11/7).
3. **After round 5**: measure #130 (targeted tests, review beside the check) on ccx2's wall time (now 251–267 s vs
   self ~94 s); after the trial, the review `[must]` scope and `--bg` for large tasks become defaults. K7 waits for the
   desktop-pet project.

### How sure we are (short)

**real** = run on a real Windows machine with logged-in CLIs; **fake** = tests with fake CLIs only.

- **real**: delegation both ways, `--check`, review (rounds 1–2), `ccx way`, `ccx stop` → `ccx resume` and killed
  runs counted, archiving after a run, DeepSeek leading, a three-vendor `ccx discuss`, the board via
  `ccx say --resume`, shared work context A/B, project catalog scan, the plugin marketplace install (Claude Code,
  from a temporary config), `ccx ui` hiding tests, a 3-task `ccx batch` (#100), non-ASCII paths, no console pop-ups, Codex hooks on Windows (H7,
  #82 + #92), the queue killed and resumed, worktree delegation with `ccx undo`, a parallel 3-run batch (Codex +
  dsh), `--fork` (the forked run knew what only the lead's session held), `ccx say --now` and the per-turn hook in
  the interactive Codex CLI, dsh archiving queued while the app is open and written after it is quit.
- **fake only**: quota fallback, seats, Gemini CLI, a real quota stop.
- **not verified**: `ccx say --now` in the Codex desktop app's own window; the Codex rule from
  `ccx doctor --codex-rule`; the dsh app's own later writes after a queued archive; the Codex plugin from a GitHub address; own sub-agent limits
  live (F11 did not fire: no agent started sub-agents even when told to); the new `--review auto` trigger rate;
  a hook timeout in a real session; `ccx intake` against real GitHub; L2 auto-merge end to end; routing beyond the
  evaluation tasks.

## 0. STATUS.md as of 2026-10-24 (0.4.0), moved here on 2026-10-25

### Now

The order comes from the shared plan (proposals F–J, all approved). **J13** moved the lead-cost items first,
because nearly all spend is the lead re-reading its own conversation (sub-agents: $0.34 in 30 days; a median lead
turn re-reads ~220k tokens):

| Step | State |
|---|---|
| H13 verdicts without asking | ✅ PR #2 |
| H10 the lead's own context (`ccx lead`, per-turn hint) | ✅ PR #3 |
| H11 week-long comparison: the tool (`ccx trial`) | ✅ PR #5 — the week of data is collected by the eval session (PR #6, with J0, E8, F9) |
| J1 + J2 what a turn re-reads, where the cache broke (`ccx lead --breakdown`, `--cache`) | ✅ PR #8 |
| J3 long output cut down before the lead reads it (`ccx sum`) | ✅ PR #9 |
| J6 this page down to one page | ✅ PR #10 |
| J0 baseline, H11 first batch, E8 both ways, F9 on/off, J7 | ✅ PR #6 ([report](research/2026-10-24-h11-e8-f9-measurements.md)): lead median 352k tokens / $0.11 a request (7 days), ~55k fixed per request; delegating saved 1 lead request per small task only when the lead trusted the check; F9 started no sub-agents; J7 switch in, no overturn data yet |
| Fixes from that report: handoffs per file (parallel sessions), plan from a numbered list, the conversation's ccx runs in a handoff, saving measured or labelled a model, agent-delegate: don't re-run a passed check | ✅ PR #15 |
| J12 `ccx uninstall --apply` once for real, then back in (report 5c); fixed: line endings kept, the Codex block back in place, uninstall says how to reinstall the skills | ✅ PR #17 |
| J8–J10 official codex-plugin-cc, similar projects, name options (docs only, [landscape](research/landscape.md)) | ✅ PR #4; coexistence plan not implemented or tested; the name waits for the user |
| G1 `ccx ui` (read-only live page) + `ui.lang` | ✅ PR #7; `ccx stop` next (the adapters are in) |
| I1–I4 adapters per agent, vendor decides "another", fallback and reviewers from data | ✅ PR #11 — new interface: `ccx.agents.get(name)` → `Adapter` (build/parse, vendor, support, tested_version, capabilities()); `ccx.agents.vendor()`, `others()`; `ccx agents` lists them as JSON |
| J4 one step to a fresh conversation (`ccx fresh`) | ✅ PR #12 |
| J5 a model for the lead itself (`ccx lead --suggest`, a line in `ccx report`) | ✅ PR #13 |
| J11 `ccx/delegate.py` split by job, behaviour unchanged | ✅ PR #14 |
| F10–F14 own sub-agents: spend and quota limits, Agent tool for Claude, explicit "use sub-agents" for parts | ✅ PR #18 — limits not yet hit by a real run (sub-agents rarely start: PR #6) |
| H5–H6 + I6 shared memory in use: suggested notes the person accepts, this project first, usage counts, notes in the brief for tools without a start hook | ✅ PR #21 — suggestions are heuristic; **H7 waits for the user**: the first try (in a folder named `...\玩`) hit a crash on non-ASCII paths, fixed in PR #27; send "ok" again in a new Codex desktop conversation |
| `changes/<PR>.md` per PR instead of editing CHANGELOG/STATUS | ✅ PR #22 |
| H3–H4 + I7 `ccx discuss` (2–3 vendors propose / critique / judge, `ccx ui` shows it as a conversation) | ✅ PR #23 — one real discussion (Codex + Claude, agreed in 3 rounds, $0.28); with two vendors the proposer also judges |
| H8–H9 `ccx way` (three ways of working by risk; first-try and rework rates per kind of task) | ✅ PR #24 |
| DeepSeek as the fourth vendor (`dsh` adapter, DeepSeek through Codex), Kimi / GLM / Qwen / OpenRouter providers | ✅ PR #25 — through Claude Code and through Codex run for real; `dsh`, Gemini and the small vendors not run (not installed / no keys) |
| Fixes from the seven-cores real runs: `ccx task resume` restarts a step killed before its session began (#26); non-ASCII paths no longer crash (#27); `ccx doctor` checks a Codex lead's sandbox (#28) | ✅ #26, #27; #28 open — on Windows only `danger-full-access` lets a Codex lead hand work to Claude |
| Seven cores A/B on real CLIs (delegation, routing, review, memory; 3 rounds, $6 cap) | ⏳ running (session ccx-evals); round 1: delegating saves the lead 1 request in 3 but costs as much in total and is ~2.7× slower; routing no better than one fixed model; review cost ~34× with no gain in pass rate and passed one wrong solution |

### Next three

1. Finish the seven-cores A/B (rounds 2–3, memory group) and act on it: review and routing defaults, the "ccx says ok,
   hidden test fails" cases (the check is too weak when the visible tests miss a requirement).
2. J0 on real sessions (`scripts/eval/j0_baseline.py real --days 7`) a week after J1–J6, against the baseline in
   PR #6; spot-check 5 probable verdicts a week so J7 has an overturn rate.
3. Then: H7 (the user's check above), `ccx stop`, I5, H1–H2, H12, H14–H16, I8, a third vendor in a real `ccx discuss`,
   and the release.

### How sure we are (short)

**real** = run on a real Windows machine with logged-in CLIs; **fake** = tests with fake CLIs only.

- **real**: delegation both ways (read and write), `--check`, independent review, failure kinds, `--bg`, `ccx send`,
  auto-continue, `task resume` after a kill, memory on the Claude side, wiring (`sync --apply`), accounting and
  `ccx report`, DeepSeek as a provider, the E8 handover both ways (once each), `ccx lead --breakdown` / `--cache`, `ccx ui` (page and server in Edge on a hub of ccx runs on the fake CLIs,
  read-only once on the real hub; other browsers/OS not opened).
- **fake only**: worktrees, `ccx batch`, quota fallback to the other agent, the queue and seats, `--fork`, Gemini
  CLI, a real quota stop.
- **not calibrated**: routing priors (few real verdicts), the 10-minute checking window in `ccx trial`, the token
  estimates per part in `--breakdown` (the total is measured).

## 1. Where we are

Legend: **real** = verified on a real Windows machine with logged-in CLIs · **fake** = covered only by tests with
fake CLIs · **none** = not run anywhere yet.

| Area | What | Confidence |
|---|---|---|
| Delegation | `ccx run` Claude → Codex and Codex → Claude, JSON result, read-only and write mode | **real** (both directions; write runs in the F1 trial) |
| | `--check` re-run by ccx, read/write inferred from the brief, sub-agents told not to commit | **real** (F1 trial, 2026-10-24) |
| | worktrees, `ccx batch`, escalation, quota fallback to the other agent | fake |
| | auto-continue of sub-sessions, `--bg`, `ccx send` (waits while you type) | **real** (`--bg`, send, auto-continue); `--fork` fake |
| Review (F1) | another vendor's cheap model reviews the diff, one fix round | **real** (seeded bugs 9/9, false alarms 0/5, 1 real bug caught) |
| Failure kinds | `model`, `policy`, `auth` | **real** |
| Routing | public benchmarks merged per kind, total cost, quota by pace, human-minute difficulty | **real** data and quota readings; priors **uncalibrated** (2 real verdicts so far) |
| Queue / seats | `ccx q`, layered splits, `--seat` | fake |
| Checkpoint | `ccx task resume` after a killed run | **real** (2026-10-23); after a real quota stop: fake |
| Memory | layers, cursors, sources/supersedes/search, `ccx handoff` | Claude side **real**; Codex desktop not checked; `--from-transcript` built once from a real session (not a live handover) |
| Wiring | `ccx init` / `sync --apply` / `skills install --replace` / SessionStart hook | **real** (Codex hook output: desktop not checked) |
| | `ccx uninstall` | dry run **real**; apply not run |
| Accounting | sub-agent tokens + AE$, lead usage, archive, `ccx report` (+ `--publish`) | **real** |
| Adapters | Codex, Claude Code, DeepSeek (provider; 10/10 calibration tasks) | **real** |
| | Gemini CLI | none |
| Built-in sub-agents (F9) | on by default, ≤ 3, routed model, $2 cap | Codex `agents.*` keys: see the F9 note below |
| Packaging | wheel + clean-venv smoke, `install.ps1`, CI | **real**; CI not running since 2026-10-24 (Actions minutes, see 2) |

Measured on the real machine (second two-way test, tiny read-only task):
- Start-up context per request (`ccx selftest` + single-request probes, 2026-10-23): Codex 18.1k lean / 21.0k with
  the user's config; Claude haiku slim 13.6k write / 10.6k read. Written to `startup_tokens` (`d4c97fd`).
- Resumed Codex sessions used to be counted with their whole history (fixed in `2c0e637`): ledger rows before
  that over-count escalations and follow-ups.

## 2. Next steps, in order

### Now (2026-10-24, after v0.4.0): the unified order of proposals F10–F14, G, H, I
1 H13 verdicts without asking — ✅ PR #2 · 2 H10 keep the lead's context small — ✅ PR #3 · 3 H11 a week-long comparison — tool ✅ (`ccx trial`, `feat/h11-trial`), the week of data itself is being collected by the eval session (with the E8 two-way handover and F9 on/off checks) · (J13: J0–J3, J6 come first; J1–J2 ✅ PR #8, J3 ✅) · 4 I1–I4 adapters for
many vendors · 5 F10–F14 fewer limits on built-in sub-agents · 6 H5–H7 + I6 shared memory in use · 7 H3–H4 + I7
`ccx discuss` · 8 H8–H9 collaboration patterns · 9 G1 UI + `ccx stop` + `lang`, I5 more model sources · 10 H1–H2,
H12, H14–H16, I8, then the open-source release. Each step: a branch, tests, a PR in Chinese, CI green, merge.

### Before (2026-10-24, v0.4.0)
- **Real use with verdicts.** 34 real runs in the ledger, only 2 `ccx verify` verdicts. Routing calibration, the
  learned lead bias (E11), `refit` and the "how much was saved" report all wait on these. Run `ccx verify` after
  each delegated task; read `ccx report` after two weeks.
- **CI.** Jobs have not started since 2026-10-24 (GitHub: payments / spending limit; private-repo minutes, macOS
  10x). The workflow now runs a small set on push and the full matrix on tags/PRs/by hand (`cdfc13a`); it runs
  again once minutes reset or billing is sorted (the user's account). Unlimited once the repo is public.
- **E8 acceptance.** Hand over for real once each way (Claude → Codex, Codex → Claude); the new lead should say
  where things stand and what's next from the handoff alone.
- **F9.** Live check (2026-10-24, 4 runs, the same splittable task, luna/low): all done and checked, $0.0034–0.0057
  each; luna never started sub-agents, on or off, so there is nothing to compare yet. Found: codex-cli 0.164 offers
  its multi_agent v2 tools even with both features disabled, so `--no-subagents` now also says the rule in the
  brief (`0124e0a`). The `agents.*` keys were accepted without error; their effect is unseen (no child started).
- **Proposal G** (`ccx ui`, a local live view): mock-up first, for approval.
- **Open from the plan:** `lang` (en/zh) for the strings ccx injects; Gemini CLI never run live; `ccx uninstall
  --apply` never run; the Codex desktop side of the SessionStart hook (needs a new desktop conversation).
- Not pursued for now: Artificial Analysis (`AA_API_KEY`; the plugin stays in the hub, unused).

### Now (2026-10-23, approved in the shared doc: packaging → setup → split cli.py → clean-up → untried paths)
- **Packaging — done (`4ec0496`, CI `package` job green on 3 OS).** Plan was: keep `config/`, `skills/`, `hub-seed/` where they are (hub links point at
  `skills/`) and ship them as package data (`ccx._config`, `ccx._skills`, `ccx._hubseed`); one resolver uses the
  source tree when present, else `importlib.resources`; `python -m ccx` where `ccx.py` is missing; CI builds the
  wheel, installs it in a clean venv and runs `ccx --version` + a fake-CLI smoke run.
- **`ccx setup` — done.** Plan: a guided first run in `ccx/setup.py` (check tools/logins → hub → init → sync
  preview → apply on yes → doctor + /hooks reminder → optional selftest → first delegation command); asks before
  every change; not on a terminal and no `--yes` = shows the plan only. (This plan line was written after the
  work, not before — corrected here.)
- **Split `ccx/cli.py` — done.** Result: `cli.py` 32 lines; `ccx/commands/{common,delegation,memory,install,records}.py`. Every subcommand's `-h` is identical to before; only the order of the top-level command list changed (now grouped). Plan was: move command groups into `ccx/commands/` (run/route/batch, memory/project,
  sync/skills/setup, reporting, archive/handoff/task) with the parser built from per-module `register()`; `cli.py`
  keeps `main()` and shared helpers; no behaviour change — the full test suite and the installed-wheel smoke test
  must pass unchanged.
- **Clean-up before open source — done except the history squash.** `SECURITY.md` added (`976342c`); `docs/plan/` moved to the private repo `ai-personal` (copies checked byte for byte) and removed here; a scan for names, emails, user folders and local paths now finds nothing (LICENSE keeps the GitHub handle as copyright holder). Still in git history until the squash, which comes last and only after asking. Plan was: add `SECURITY.md` + `SECURITY.zh.md` (what the session-start
  hook runs, how inbox/web text is treated, what a writable sub-agent may touch and how to undo it, how to report a
  vulnerability); move `docs/plan/` (the only files with personal names and folders — 44 hits) out of this repo
  once the user picks where (the private repo `ai-personal` does not exist yet); squash the git history last, and
  only after asking.

- **Untried paths, run once for real — done.** Real runs on Windows: `--bg` (finished on luna/low); `ccx undo
  --apply` after a real write run (file restored with the user's uncommitted edit kept, new file moved aside);
  `ccx task resume` after killing a real run mid-way (same Codex session continued); `ccx report --publish` (committed;
  no push without a remote); `install.ps1` with and without pipx, and with output redirected. Fixed on the way:
  `task resume` now finds runs killed before they reached the ledger and keeps their model; `ccx show` says
  `running` instead of `error` while a run is going; `install.ps1` reports a failed pipx install (exit 1) and no
  longer aborts when its output is redirected. Gemini and DeepSeek still need a login / key. Plan was, each isolated from the real hub/pipx/repo: `--bg` on
  Windows (tiny read run on luna/low, detached, then `ccx show`); `ccx undo --apply` after a real write run in a
  scratch git repo; `ccx task resume` after killing a real run mid-way (`--task/--step`); `ccx report --publish`
  into a scratch local repo; `install.ps1` with temporary `PIPX_HOME`/`PIPX_BIN_DIR`/`CCX_HUB`/`CCX_CONFIG`.
  Gemini and DeepSeek stay for later (need a login / key).

- **GitHub look — done (2026-10-24; `9fd646b`, `9df8bbb`, `d7e7c10`).** README first screen, demo, architecture,
  FAQ; `site/` + sample dashboard + manual Pages workflow; CONTRIBUTING, code of conduct, issue forms, PR template,
  social preview; About text and topics set. GitHub community profile 100%. Left for the user: upload
  `docs/assets/social-preview.png` (Settings → Social preview; the API cannot), and after going public: enable Pages
  (source: GitHub Actions) and run the `website` workflow, turn on private vulnerability reporting, set the homepage
  field. The tests and release badges only show once the repo is public. Plan was: `docs/assets/` gets banner and
  architecture SVGs as light/dark pairs (`<picture>`, so GitHub's own theme decides, not the OS), a demo SVG generated
  by `scripts/make_demo.py` from a real fake-CLI session (re-runnable), and a 1280×640 social preview PNG; README.md /
  README.zh.md get the first screen, measured numbers, six features and an FAQ; `site/` (EN + ZH homepage, sample
  dashboard from `ccx report` on fake data) with a manual-only Pages workflow; CONTRIBUTING (EN/ZH), issue/PR
  templates, a short code of conduct, and the repo About text and topics. Checked on GitHub's own rendering
  (`gh api …/readme` HTML) and in the browser at desktop/phone width in both themes.
- **GitHub look — mock-ups (approved).** README first screen (SVG banner that shows the
  hand-off with a real run's numbers, badges, one-line value, three-command start, measured table) and a static docs
  homepage (no CDN, light/dark + toggle, phone width). Checked rendered at 1440×900 and 390×844 in both themes: no
  overflow, no text under 12 px, tap targets ≥ 32 px, visible keyboard focus. Not in the repo yet; the full set
  (demo animation, architecture SVGs, Pages, social preview, CONTRIBUTING, templates) follows approval.

- **Proposals E and F — approved 2026-10-24, in progress.** Order: step 0 read/write detection (approved
  10/23, missed) → E1 → E3 → E11 → E2 → E4 → E5 → E6 → F8 → F3 (+F2) → F1 → F9 → F7 → F4–F6, with E7 → E8 → E9 in
  between. Step 0 now: `ccx run`/`route`/`batch` infer read or write from the task text when `--mode` is not given
  (Chinese and English verbs; explicit `--mode` wins; unclear → write, said so), record `mode_source`; a read-only
  run whose sub-agent says it needs edits stops with `needs_write` for the lead to decide, no escalation. ✅ `71a3183`.
  E1 ✅ `ca4ced3`: weekly public benchmark data (Epoch AI, LMArena, models.dev) cached next to the routing state.
  E3 ✅ `2910f66`: abilities merged from those benchmarks per kind of work (`--kind`), local outcomes on top.
  F1 live trial (2026-10-24): seeded bugs 9/9 caught by the tightened brief, 0/5 false alarms (2 haiku reviews failed
  and now fall back to the next reviewer); 1 real bug caught in 4 real tasks, fixed in one round; $0.0017 (luna) –
  $0.0037 (haiku) per review. On diffs this small the lead saves only ~300–500 input tokens, about what a review
  costs: the gain is the caught bugs; it pays for itself in tokens from roughly 50+ changed lines.
  F1 ✅: independent review only when needed (`--review auto|on|off`): another vendor's cheap model reviews the diff
  when the task is visible/critical, the sub-agent is unsure, or its claims don't match the diff; one fix round.
  E8 ✅ (+ model fallback for formats the code can't read): `ccx handoff --from-transcript codex|claude` writes the handoff by code from the outgoing lead's newest
  session file (goal, its plan, recent messages, last conclusion, changed files, failed commands, git state,
  unfinished tasks; secrets masked, one page); a quota resume also hands over the cut-off session's state.
  E7 + E9 ✅ `b4740a6`: memory sources, replacement, checks, search, stale flags, a 600-token start-up cap; where memory goes.
  F6 ✅ `e08ce82`: `ccx send` waits while you are working in that Codex conversation, then holds the message.
  F4 + F5 ✅ `b1c26b4`: named seats (`--seat`), restore outcomes in `ccx q resume`.
  F9 ✅ `9383282`: built-in sub-agents on by default — one level, routed model, ≤ 3 at a time, counted, spend watchdog.
  F3 + F2 + F7 ✅ `c66d70d`: durable work queue (`ccx q`), roles left to the lead, layered splits through the queue.
  F8 ✅ `68bcd1b`: sub-agents check their own work; `--check CMD` is run again by ccx and a failure counts.
  E6 ✅ `27e6987`: DeepSeek flash at low / high / max by difficulty; v4-pro out of the ladder.
  E5 ✅ `de2a753`: quota by pace, projected to each window's reset; Claude read from runs and a tiny hourly probe.
  E4 ✅ `1e268ff`: total cost = money + quota shadow price + time + risk (replaces the 70% gate and quota weights).
  E2 ✅ `3731fcd`: local source plugins; the user's Artificial Analysis plugin sits in their hub, not used for now (user decision, 2026-10-24).
  E11 ✅ `78bce81`: difficulty in human minutes (`--minutes`), objective signals from the brief, learned lead bias, `refit`.
- **Proposal D — done (2026-10-24; `9b618d8`, `3175b80`).** First live run found that a provider run sent the
  caller's own Claude login to DeepSeek (401; fixed in `9b618d8`, checked against a local header-recording server).
  D1: 1.5k start-up tokens per request with `--bare`; tiny read $0.0009 flash / $0.005 v4-pro. D2: flash 10/10 on
  checkable repo tasks (b 1–5), $0.054 → theta 4.5 (low end of 4.3–6.8). D3–D5: own `deepseek` agent and rungs,
  escalation to Claude, offered only when every subscription is at ≥ 70% quota, off-peak half price, $1/day cap,
  own dashboard line. D6: guidance in `references/three-way.md`. Not verified live: escalation from DeepSeek to
  Claude (no task failed), v4-pro's ability, and the cap (tests only). The pointers added to task-routing's and
  agent-delegate's SKILL.md sit with the user's own uncommitted edits there.
- **Proposal C — done (2026-10-24; `3100e14`, `4a5f64c`, `839ba87`).** C1 measured: a Claude Code built-in
  sub-agent starts with 58.4k tokens (4.3× ccx's slim start), a Codex multi_agent child 22.2k; a tiny read cost $0.0083
  built-in vs $0.0029 / $0.0023 through ccx. C5: a Codex sub-agent's own children were missing from the ledger (59% of
  one run's cost) — now counted. C2: `ccx route … --lead` gives `choice` (self / builtin / delegate) with `--needs`
  and quota pressure. C3: `choice.how` and `ccx verify --builtin`. C4: no nested sub-agents unless
  `--allow-subagents`. Not verified live: that `--disallowed-tools Agent` removes the Agent tool from a forked Claude
  run (checked against `--help` only). Open: a pointer to `references/three-way.md` in agent-delegate's SKILL.md,
  which has edits of the user's not yet committed.
- **Proposal C (as proposed).** Choose among three ways for each
  piece: the lead itself, the lead's built-in sub-agent (Claude Code's Agent tool, Codex's multi_agent), or ccx to
  the other tool — with hard requirements (undo/worktree, other vendor, resume → ccx) and quota pressure. And a rule
  for nesting: ccx sub-agents don't start their own sub-agents by default. Facts found: a Claude sub-agent under
  ccx's slim start has no Agent tool (except with `--fork`); a Codex sub-agent has `multi_agent` on and can, and
  whether those children's tokens reach the ledger is unverified. No built-in sub-agent runs exist on this machine
  yet, so their start-up cost is unmeasured. Nothing implemented yet.

### P0 — correctness and trust (do first)

1. ~~Check the lead-usage magnitudes~~ — done 2026-10-23. `/status` shows no token totals, only the 7-day quota
   (2% used, matching ccx). Checked instead against quota % per window: AE$ per 1% stayed within $2.8–4.4 while
   raw tokens per 1% differed 14× (model mix), so no double counting is visible. `lead_to_sub_ratio` removed.
   Claude lead usage is not cross-checked yet (no quota % in its transcripts).
2. **First real `ccx sync`** — applied 2026-10-23; doctor all ok. Left:
   - Run the dry run and review every planned change.
   - `--apply` installs the Claude `settings.json` SessionStart hook, the Codex `config.toml` hook block (trust it
     once in `/hooks`), and the `agent-delegate` skill links.
   - Then check:
     - a new session on each side shows the memory delta, unfinished tasks and handoffs;
     - nothing else in either config changed;
     - `ccx uninstall --apply` removes exactly what was added.
   - On a hub with `external_sync`, skills/MCP stay with that script.
3. **Desktop apps as lead.** Claude Code desktop → Codex: **done 2026-10-23** (lead session recorded, luna/low in
   one attempt; a second task auto-continued the same Codex session and was counted as its growth only).
   Codex desktop → Claude: **done 2026-10-23** (message queued with `ccx send --thread`; the agent read the
   agent-delegate and task-routing skills, ran `ccx run` with the rubric → haiku/low, checked the answer and
   recorded `ccx verify --ok 1`; lead session = the desktop thread id). Not seen yet: the SessionStart hook's
   output in a new session — the shared memory is empty, so it has nothing to print.
   The two bugs found here (`send --list` needed a TTY, lead session ignored the caller) are fixed.
   Original item: Ask each desktop app's agent to run one `ccx run` (Codex desktop → Claude,
   Claude Code desktop → Codex). Verify:
   - the lead-session env var is present (`CODEX_THREAD_ID` / `CLAUDE_CODE_SESSION_ID`), so auto-continue works;
   - the sub-agent's sessions do not appear in, or are archived from, the apps' history.
4. ~~Windows read-only sandbox~~ — done (`94d1323`): the rejections came from ccx's own `--ignore-user-config`
   dropping `windows.sandbox`, not from read-only mode. Read-only stays the default for read tasks.

### P1 — make it pay off

5. **Calibrate with real work.** Use ccx for 1–2 weeks of real tasks, with `ccx verify` after each.
   - Then read `ccx report`: which rungs succeed, real cost per success, A/B rows, built-in sub-agent vs ccx.
   - Adjust only from data: priors in `skills/task-routing/data/priors.toml`, horizons in task-split.
6. ~~One copy of the skills~~ — done 2026-10-23 (`6d75a3c` keeps the backups out of the skills folder).
7. ~~Unavailable-model memory is 30 days~~ — done (`94d1323`): 7 days, dropped when the CLI version changes.
8. **Run the untried paths once for real:**
   - `--bg` on Windows;
   - ~~`ccx send` into a live Codex desktop thread~~ (works with `--thread`; `--list` needs a TTY);
   - `ccx task resume` after a real quota stop or a closed window;
   - `ccx undo --apply`;
   - `ccx report --publish` to the private usage repo;
   - Gemini CLI (needs a login);
   - the DeepSeek provider (needs a key);
   - `install.ps1` / pipx.
9. **Doc drift.** Re-checked against codex-cli 0.164.0 / Claude Code 2.1.309 on 2026-10-23 (`94d1323`). Repeat
   whenever a CLI updates: `--help` for the flags ccx uses, then `TESTED_VERSIONS` in `ccx/runners.py`.

### P2 — before v1.0 (open source)

10. Contributing guide + adapter template; a fake-data sample dashboard in `docs/`; issue templates.
11. Optional `lang` setting (en/zh) for the few strings ccx injects into sessions.
12. Version tags (could not be pushed from the cloud session); squash history into one clean commit before making
    the repo public; final check that no personal data is in any file.

## 3. Acceptance (from docs/DESIGN.md)

| # | Check | State |
|---|---|---|
| A1 | `ccx doctor` | ✅ all ok after `ccx sync --apply` |
| A2 | Claude → Codex | ✅ terminal and Claude Code desktop lead (auto-continue too) |
| A3 | Codex → Claude | ✅ terminal and Codex desktop lead (verified with `ccx verify`) |
| A4 | memory increments only | ✅ Claude Code new session; ⏳ Codex desktop |
| A5 | project layer shared | ⏳ hooks are in; not checked with a real inbox file |
| A6 | skills on both sides | ✅ `agent-delegate` + `task-*` linked into both (hub → repo) |
| A7 | MCP on both sides | ⏳ (hub's own sync already handles MCP; confirm) |
| A8 | dashboard | ✅ `ccx report` and `--publish` run on the machine |
| A9 | resume after interruption | ✅ a killed run resumed in the same session (2026-10-23) |
| A10 | quota fallback | ⏳ (only seen with fakes) |

## 4. Done recently

- 2026-10-24 J3: `ccx sum -- <command>` (tests, diffs, logs cut down by code; full output kept; `--ask` for a cheap model).
- 2026-10-24 J1 + J2: `ccx lead --breakdown` (what every turn re-reads, part by part, with advice) and `ccx lead --cache` (turns where the cache broke, the cause, the cost). Real numbers: this session 78.6k tokens a turn (built-in tools ~23k, skill list ~6k, browser MCP ~5.6k); the previous long session 5 breaks, ~$8.5 extra. I1–I4 done on `feat/i1-adapters` but held for J13.
- 2026-10-24 H11 tool: `ccx trial` (balanced halves, both measured the same way). Quick real E8 runs on this machine:
  Claude → Codex 2 of 3 right (gpt-6-luna/low once said read-only meant no shell — wording fixed), Codex → Claude
  (handover from a headless `codex exec` lead, `--session` needed) 1 of 1 right with haiku/low.

- 2026-10-23 `75c9e54` — start-up priors by mode; `8ea4e8e` — lead stays cheap when delegating, long handoffs summarised; `ce4195a` — `ccx repair` (4 runs, AE$ 0.0321 → 0.0162).
- 2026-10-23 `27b8bf3` — **v0.3.0** released (tag + GitHub release).
- 2026-10-23 `f42939e` — five small fixes: `send --list` without a TTY, lead session by caller, archive a shared session once, uninstall hub links + restore backups, `skills install` dry run by default.
- 2026-10-23 — desktop apps as lead, both directions (P0-3).
- 2026-10-23 `2c0e637` — resumed Codex usage counted as growth, not the session's running total; `d4c97fd` measured start-up priors.
- 2026-10-23 `bf5e1c8` — P0-1: Codex lead usage checked against the weekly quota; `lead_to_sub_ratio` removed.
- 2026-10-23 `6d75a3c` — `skills install --replace` backups kept outside the skills folder; hub `task-*` now link to the repo.
- 2026-10-23 `94d1323` — lean Codex start keeps the user's `windows.sandbox` (root cause of `policy`); unavailable-model marks 7 days + CLI version; flags checked on codex-cli 0.164.0.
- 2026-10-23 — first real `ccx sync --apply` (hooks + agent-delegate), doctor all ok.
- 2026-10-23 `92207a8` — `policy` failure kind: same-rung retry instead of escalation when the sandbox rejects a command.
- 2026-10-23 `8de20b3` — tests read UTF-8 explicitly (Chinese Windows / GBK locale).
- 2026-10-23 `e110a1c` v0.2.4 — unsupported-model swap, Codex usage from `total_token_usage` deltas, doctor JSON login.
- Earlier: see CHANGELOG.md.
