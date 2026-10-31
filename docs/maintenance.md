# Maintenance mode: picking ccx up again

English · [中文](maintenance.zh.md) · back to the [README](../README.md)

This page is for whoever comes back to ccx after a pause: a maintainer, a contributor, or a coding agent. It says
where the current state is written down, what is known to be wrong or unverified, which switches ship off and why,
and how to run an evaluation without fooling yourself.

## 1. Where to start

Read these in this order, and stop when you know enough for the task at hand:

| What | Where | Why |
|---|---|---|
| Rules for working in the repo | [AGENTS.md](../AGENTS.md) | tests before every commit, nothing personal, bilingual docs, one `changes/<PR>.md` per PR |
| Where things stand | [docs/STATUS.md](STATUS.md) (one page) | now, the next three items, how sure we are; older pages in [STATUS-archive.md](STATUS-archive.md) |
| What changed | [CHANGELOG.md](../CHANGELOG.md) and the notes in [changes/](../changes/) | `changes/*.md` are the PRs merged since the last release, not yet folded into the CHANGELOG |
| Why it is the way it is | [docs/DECISIONS.md](DECISIONS.md) | one row per real decision, newest first, with the evidence |
| What was measured | [docs/research/README.md](research/README.md) | one row per report: question, result, main limit |
| The previous session's notes | `.ccx/handoff.md` in your checkout, if it exists | local only, never in the repository |

Then run the tests once (`python -m pytest -q tests`); they never call a real agent CLI.

## 2. Known issues and unverified paths

The experimental ones are also marked where each feature is described. The full list is the "not verified" line
in [STATUS](STATUS.md).

| Issue | What is known | Where |
|---|---|---|
| Wall time | On the hold-out run ccx took about 3× the wall time of the lead doing the task itself (61 s vs 21 s median) | [hc1 report](research/2026-10-29-hc1-holdout.md) |
| Savings are narrow | About 30 % cheaper per success on 10 hold-out tasks, one lead model (Sonnet), Codex gpt-6-luna low as the sub-agent; about 15 % on the 5 external-repository tasks. Small tasks delegated from a long lead conversation did not save | [measured](measured.md), [round 4](research/2026-10-26-r4.md) |
| Routing priors | The difficulty → model odds are uncalibrated beyond the evaluation tasks | [features](features.md) |
| Experimental: Gemini CLI | Adapter written from its docs, tested with a stand-in; never run for real; sub-agent only | [faq](faq.md) |
| Experimental: a real quota stop | The fallback to the other tool is tested with stand-ins only | [features](features.md) |
| Experimental: macOS and Linux | CI only; every real run was on one Windows machine | [README](../README.md) |
| Experimental: Codex plugin from a GitHub address | Follows Codex's plugin docs, tested with a stand-in only | [install](install.md) |
| Experimental: `ccx intake` against real GitHub | Only against a stand-in `gh` | [intake](intake.md) |
| Not run live | `ccx say --now` in the Codex desktop app's window, the Codex rule from `ccx doctor --codex-rule`, the dsh app's own later writes after a queued archive, own sub-agent limits (F11), the `--review auto` trigger rate, a hook timeout in a real session, L2 auto-merge end to end | [STATUS](STATUS.md) |

## 3. Experimental switches: what ships off, and why

The defaults live in [config/tiers.toml](../config/tiers.toml); a person overrides any of them in
`<hub>/ccx/tiers.toml`. Only some keys can also be set with `ccx config set <section>.<key> <value>` (the last
column); the others are file-only, by design for `[subagent]` (no per-run flag). The rule for every one of them: it changes only after a before / after
measurement shows right answers do not drop, and the decision gets a row in [DECISIONS](DECISIONS.md).

| Key | Default | What turning it on does | Why it is off | `config set` |
|---|---|---|---|---|
| `defaults.focused_retry` | `false` | after a failed `--check`, the retry continues the same session with the failing command and its output | "fix only what fails" narrows what the retry re-checks, so it cannot be argued that right answers never drop; waits for a measured round (the motive: in r6a the old-style retries took a median 389 s) | yes |
| `defaults.namecheck` | `"warn"` | `"fail"` makes an undefined name in changed code fail the run | `warn` had 0 false alarms offline; `fail` waits for its before / after (r6a ran the `ccx2nc` arm; its result is not published yet) | no (`ccx run --namecheck` per run) |
| `lanes.default` | `0` | `ccx batch` / `ccx q run` continue a few warm sessions instead of one per piece | about 40 % cheaper than a fresh session per piece, but slower and still dearer than one run ([warm lanes](research/2026-10-25-warm-lanes.md)); to be decided by a confirmation run | yes |
| `memory.by_kind` | `false` | start-up brings only preferences and constraints; briefs bring matching pitfalls and facts | to be decided by a confirmation run; the H11 trial that was to decide it was voided on 2026-10-26 | yes |
| `memory.start_scene` | `false` | start-up also brings the project's scene block | same as above | yes |
| `review.context` | `false` | the review brief also gets the code around the change | replay of round 5: about half the time and output, but caught the known bug 11 of 28 times instead of 19 | no |
| `review.must_needs_repro` | `false` | with ccx's check passed, a review `[must]` without a `repro:` becomes a `[should]` (`"downgrade"`) or is first settled by a stronger reviewer (`"confirm"`) | r5 10 tasks x 1 round (off / downgrade / confirm), plus a replay of the 27 recorded review_failed units and seeded real bugs | no |
| `review.fix_rereview` | `"full"` | `"focus"` re-reviews a fix against the first review's problems | timing decides it: a median 2.4 s saved against a 10 s bar (missed `[must]` 24 vs 21 of 33, one pass each, not told apart from noise) | no |
| `review.cache_ttl` | `""` | sets a Claude reviewer's prompt-cache lifetime (`"5m"` / `"1h"`) | not A/B-tested | no |
| `routing.small_self` | `false` | `ccx route` / `ccx propose` advise doing a task of at most `routing.small_self_files` (1) source files yourself instead of delegating it (`ccx run` unchanged) | replay of r5 + hold-out: no task lost, wall -14 %, cost +5 % with the reference change's file count; the lead's own estimate needs the hold-out round (self / ccx2 / ccx2+small_self) | yes |
| `escalate.on_self_checked` | `"review"` (**ships on, not yet measured**) | a run whose check passed only on tests the sub-agent wrote or changed is always reviewed against the task text (`"rung"`: one stronger rung redoes it first; `"off"`: the label `ok_self_checked` only) | the exception to the rule above, decided in [DECISIONS](DECISIONS.md) 2026-10-31: the label is only a more honest class, and pg1 showed the old default let 18 of 18 such passes through; a review that finds problems can now end a run `review_failed` (exit 2) that used to exit 0. The before / after is a ccx2 rerun of pg1 | yes |
| `lead.model_by_task` | `false` | a new lead conversation picks its model by task difficulty | thresholds are provisional until `scripts/eval/r5.py --lead-model auto` is compared with fixed models | yes |
| `subagent.codex_memories` | `true` | `false` turns Codex memories off for sub-agents | B3: changes only after the before / after against the person's daily setup ([plan](research/2026-10-30-b3-lean-switches-plan.md)) | no |
| `subagent.clean` | `false` | sub-agents start without the person's skills and user settings | same B3 measurement; may lose right answers that personal skills bring | no |
| `subagent.codex_lean_tools` | `false` | write runs on Codex lose web search, image generation and goals | same B3 measurement | no |
| `policy.picked` | `""` | pre-authorizes delegation by tier, without proposing first | a person's own choice, never a default | yes |

Empty by design rather than experimental (set with `ccx config set`): `board.github` and `intake.github` (nothing
touches the network until you name a private repository of yours), `report.publish_dir`, `projects.roots`.

## 4. How to run an evaluation

Evaluations spend real money and their numbers end up in the README, so the rules are strict.

1. **Write the plan first.** A new `docs/research/<date>-<name>-plan.md` (and `.zh.md`) with the question, arms,
   tasks, the decision rule and the budget, committed before the run. Deviations are written down afterwards, not
   hidden.
2. **Price it without running it.** `python scripts/eval/r5.py run ... --dry-run` prints the schedule and its cost.
3. **Use the clean room.** `scripts/eval/r5.py` builds every unit from zero (fresh repo copy, hub, agent homes, a
   settings file with the person's hooks and memory off; see `scripts/eval/preflight.py`) and refuses to start
   without it (`--force-unclean` overrides that, and the rows say so). Pin the commit you measure (`--pin-commit`).
4. **Keep the machine quiet.** While a timed run is going, don't run the full test suite or other heavy jobs on the
   same machine. Start it so that its log says when it ended, e.g. `python scripts/eval/r5.py run ... > run.log 2>&1;
   echo exit=$? >> run.log`.
5. **Summarize with the script, not by hand.** `python scripts/eval/r5.py summary --tag <tag>` counts clean rows
   only and pairs arms on shared units; `scripts/eval/r5_timeline.py` shows where the time went.
6. **Publish what you found, including what went against ccx.** A report in `docs/research/` with its limits, a row
   in [research/README.md](research/README.md), scrubbed data via `r5.py export docs/research/data/<file>.json`
   (check it for local paths: `tests/test_repo_hygiene.py` flags any drive path in that folder).

Examples (adapted from the script's own help):

```bash
python scripts/eval/r5.py run --taskset holdout --rounds 3 --arms ccx2 --tag ho4 --dry-run
python scripts/eval/r5.py run --rounds 2 --arms ccx2,builtin2 --tag r5d --budget 25
python scripts/eval/r5.py summary --taskset holdout
```

The hold-out tasks (`scripts/eval/tasks_holdout.py`) were kept apart for final claims. The file is in the public
repository, so they are no longer a hold-out set; a new claim needs new unseen tasks.

### Known structural limit: evaluation and development share one machine and one account

The evaluations of late October 2026 ran on the machine the development sessions use, under the same login and
quota. That is not a bug a flag can fix: it is how the work is set up. On 2026-10-30 one evaluation round (B3, its r5
half) failed to start four times, and the fifth start ran to the end (80 units, $10.01) but could not count:

1. **The checkout moved.** The run used a `git worktree` of the main repository. When the desktop app made a
   worktree for a new session, it switched the main checkout and removed the evaluation's worktree, so the run
   stopped after its first unit. Evaluation checkouts are now separate `git clone`s.
2. **The script was gone.** The start script lived in a session's notes folder. Archiving its parent session also
   archived that session and deleted the folder. Scripts a run needs now live in the project.
3. **The machine was busy.** Another project's test run, seen between units, stopped the run (the clean-room check).
4. **The quota ran out.** Started again with `--force-unclean`, the run shared one usage limit with the development
   sessions. Once the limit was reached, every unit failed in a second at $0 and was thrown away, and when the
   session that had started the run ended, the run died with it.
5. **The whole round was unclean.** At the fifth start another session was running tests. `--force-unclean` let the
   start check pass, so all 80 rows were marked not clean and the round was left out of its decision rule (see the
   [B3 report](research/2026-10-31-b3-lean-switches.md)).

What helps on one machine:

- the evaluation checkout is its own clone;
- scripts are kept in the repository;
- the log ends with `exit=` (step 4);
- `--wait-quiet <minutes>` (in `scripts/eval/r5.py` since #201): before the start checks and between units, wait up
  to that long for no other heavy process. A unit that still overlapped other work stays not clean, so it shows
  in the rows instead of hiding;
- don't start with `--force-unclean`: it only turns a busy start into a round that does not count.

None of these makes the numbers safe from other work on the same machine.

**The move:**

1. Run evaluations on a second machine or in a cloud session, with a login of its own, so their quota is separate.
2. Use a fresh clone at a pinned commit (`--pin-commit`), with nothing else running there.
3. Start the run from that machine's own shell, not from a development session.
4. Copy back only the results file, the log and the summary when it ends.

Until then, treat a round started next to other sessions as supplementary, as the B3 report does.

## 5. Releasing

1. `python scripts/collect_changes.py` previews the CHANGELOG entry from `changes/*.md`; with `--version X.Y.Z
   --title "..." --apply` it writes it and removes the notes.
2. Bump the version in `ccx/__init__.py`, `pyproject.toml`, `.claude-plugin/plugin.json` and
   `.codex-plugin/plugin.json`; update [STATUS](STATUS.md) (one page, both languages).
3. Tag `vX.Y.Z`; the full CI matrix runs on tags. Publishing (GitHub release, PyPI) is the maintainer's decision.
4. PyPI, once the maintainer says yes (TestPyPI first; the package is `relayline`, the command `ccx`):
   - On the release tag (steps 2–3 done: a version number can be uploaded only once), with an empty `dist/`:
     `python -m pip install -U build twine`, then `python -m build` and `python -m twine check --strict dist/*`
     (CI's package job runs the same check).
   - Make an API token at https://test.pypi.org/manage/account/token/ (a TestPyPI account of its own, separate from
     pypi.org). Keep it out of the repository: in `~/.pypirc` (`%USERPROFILE%\.pypirc` on Windows) under
     `[testpypi]` with `username = __token__` and `password = <the token>`, or as `TWINE_USERNAME=__token__` and
     `TWINE_PASSWORD` in one shell only (PowerShell: `$env:TWINE_PASSWORD = "..."`). The first upload needs an
     account-wide token; afterwards replace it with one scoped to `relayline` and delete the wide one.
   - `python -m twine upload --repository testpypi dist/*`, then from a clean machine or venv:
     `pipx install --index-url https://test.pypi.org/simple/ relayline` (no dependencies, so no second index) and
     `ccx -h`.
   - pypi.org the same way with a pypi.org token and `--repository pypi` (or Trusted Publishing from GitHub Actions,
     which needs no stored token; that is a repository setting, the maintainer's call).
