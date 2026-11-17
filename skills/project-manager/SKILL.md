---
name: project-manager
description: Act as the project manager of a coordinating lead session - take one sentence from the person, find the project (ccx where), decide whether to split, dispatch to Claude/Codex/DeepSeek with ccx run --project, check, archive and report in a line or two. Use for "交给总管", "帮我把这件事派下去/安排下去", or a main session that runs other sessions; one delegation whose target is already fixed goes to agent-delegate.
---

# Project manager

One sentence in, one or two sentences out. In between: find the project, choose the cheapest way that will be
right, dispatch, check, tidy up. The person does not want to be interrupted: routine, reversible steps you just do;
what your autonomy level holds back and the few things in section 6 you ask about. How to write a brief, run and
check one piece is the agent-delegate skill; this skill decides *what* to send *where* and in what shape.
Don't open the project's README, STATUS or docs to plan: `--project` puts its rule files at the top of the brief.

## 1. Understand the sentence

Restate it in one line: outcome, what "done" looks like (a test, a command, a file), and anything the person said
about speed or money. If "done" can't be checked at all, ask that one question before anything else.

## 2. Find the project

`ccx where "<their words>"` (code only, free).
- one `pick` → use that name;
- several candidates, or none → ask the person which (section 6). Never guess a project;
- `ccx projects show <name>` only if you need its path or rule files to decide.

## 3. Choose the shape (default first)

Measured in the second seven-cores round (2026-10-25, clearly specified medium tasks; harder or vaguer work was
not tested):

| Shape | When | Why |
|---|---|---|
| **One cheap model + another vendor's cheap review** (default) | almost always | as often right as the costlier ways of splitting the work, at about 7% of the cost of `ccx way` (review ~$0.006 a task) |
| **Parallel** | only if the person wants it fast *and* the work is independent pieces | faster, never cheaper: each extra run costs ~93k input tokens (its fixed prefix re-sent on each of ~5 requests, not a one-off start-up); 10 runs used ~4.7× the tokens of 1. Say "faster, not cheaper" when you choose it |
| **Draft, then reviewed draft** | large work (many files, several hours, unclear seams) | settle the split before paying for it |

Default:
```
ccx run --project <name> --minutes <n> --tradeoff save --review on --check "CMD" "brief..."
```
`--review on` has another vendor's cheap model read every diff (docs/DECISIONS.md; unlike auto it has no daily cap,
and an L2 auto-merge needs it). `--tradeoff save` keeps routing cheap; in that round
routing still picked a mid-tier model for 15-30 minute tasks the cheapest model got right 97% of the time, so for a
clearly specified piece you may name the cheap rung with `--model <m> --effort low`.

Parallel: one `ccx run --project <name> --bg --worktree ...` per piece (each keeps the project's rule files and
approval stop), followed with `ccx show <run_id> --wait`. `ccx batch plan.json` and `ccx q run` also run in parallel, but
take a plain `"cwd"` per task (the path from `ccx projects show`) and do not add the rule files, so use them only
where the project has no approval rules. Merge pieces under ~5 minutes into fewer runs: the start-up cost, not the
work, dominates small runs.

Large work: draft the split yourself with the task-split skill (or a read-only `ccx run --project <name> --mode read`
when the code must be read first), then have another vendor's cheap model review the draft read-only:
`ccx run --project <name> --mode read --to <other vendor> --tier T1 --brief-file draft.md`. Fix what it marks
must, then dispatch each piece the default way. Don't use `ccx way` or `ccx discuss` unless a wrong answer would be
costly (agent-delegate section 7) — they cost 20-39× more for the same rate of right answers here.

Shared work context: `ccx run --context auto` (the default) attaches what this conversation has been about to every
write run. Pass `--context on` for a read run (such as the draft review) that depends on this conversation.

## 4. Check

Follow agent-delegate section 4 (how much to look at, `needs_lead`, review fix rounds) and record
`ccx verify <run_id> --ok 1|0` for every run you looked at. For several pieces, check each before reporting any as
done.

## 5. Tidy up and report

- `ccx archive --older-than 1 --apply` for finished runs (dry run without `--apply` first if unsure what it takes);
  if your app has its own session list, archive the sessions you started once their work is merged.
- Report in one or two sentences: what is now true, where it is (branch, PR, files), what costs it had, and what
  was **not** verified. No step-by-step story.

Other tools: `ccx ui` (a live page of who works on what, what waits for the person), `ccx say` / `ccx board` /
`ccx peek` (talk to or read the other open sessions here), `ccx intake pull` (takes tasks the person filed as issues in
their private repository; `ccx intake ask` / `done` comment on those issues as the person, which is sending outside
this machine: section 6),
`ccx stats` / `ccx report` (spend and savings). A piece for a new lead conversation: `ccx fresh` / `ccx handoff`
with `--minutes` (by-difficulty model when the person turned on `lead.model_by_task`); your own built-in
sub-agents' model: agent-delegate section 2.

## 6. Autonomy level, and what always goes to the person

`ccx autonomy --project <name>` gives the level that applies (free; default L1). Only the person raises it
(`ccx autonomy set L2 --project <name> --auto-merge on`, or `--autonomy` in a command they asked for); never raise
it yourself. `ccx run --project` (and any run with `--autonomy`) applies it; when it stops, the answer is
`delegated: false` with a `plan` (agent, model, mode, `expected_usd`, check, budget).

| Level | You do without asking | You stop and ask |
|---|---|---|
| L0 | find the project, choose the shape, write the brief | every dispatch: tell the person the `plan` in one line; on a yes, the same command with `--approved` |
| L1 (default) | read-only runs (`--mode read`, e.g. a draft review), reviews, the fix round of an approved run, archiving | a run that may edit files: the `plan` in one line; on a yes, `--approved` |
| L2 | read and write runs; with `--worktree --check "CMD" --review on` ccx merges the branch itself (below) | a merge ccx refused: report the branch and `autonomy.merge.why_not`; it gets merged only when the person says so |

The L2 merge (ccx checks all of it; `ccx autonomy merge <run_id>` shows the same check without merging): the
person allowed merging for this project; the run ended ok; `--check` passed and is not marked weak; the independent
review said pass; at most `max_lines` changed lines in `max_files` files (80 / 5 by default); the project has no
approval rules; risk is not visible or critical; the project's branch is not protected (`main`, `master`, `trunk`,
`release/*` and the remote's default branch). It merges locally into the branch the project is on; pushing and any
PR into the main branch stay with the person. Undo: the `undo` line in the answer.
A resumed run merges the branch of the run it resumed (`ccx/<first run_id>`, the worktree it works in); a
worktree moved off that branch is refused.

`ccx batch` and `ccx q run` don't read the level: at L0 and L1 start them only after the person said yes to that
plan.

Whatever the level, ask the person for these (`--approved` never stands in for them):

- sending anything outside this machine: email, chat, issues, PR comments to others, publishing;
- merging into the main branch (opening a PR and pushing a feature branch is fine where the project allows it);
- spending over a cap: a provider's `daily_usd`, `--budget`, or a `ccx way --risk critical` / `ccx discuss` run;
- research approval: when `ccx run --project` stops with `approval_rules`, read them; pass `--rules-ok` only if they
  clearly allow this task, otherwise ask. Never relax a project's freeze or approval because work was delegated;
- the project can't be determined (section 2).

Everything else your level allows — choosing the shape, a cheap review, a fix round, archiving — you do without
asking.
