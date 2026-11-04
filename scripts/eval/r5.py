"""Round 5 (docs/research/2026-10-26-r5-plan.md): large tasks from this repository's own history.

Rounds 3-4 showed that on small tasks cheap models are right anyway and a lead makes as many requests whether it
does the work or hands it away. Here every task is a real change in the whole ccx code base (scripts/eval/tasks_r5.py),
so doing it takes many requests. Arms (the lead is a fresh headless Claude Code, sonnet medium, as in round 3):

  self     the lead does it itself
  builtin  the lead must hand the implementation to its built-in sub-agent (Agent tool, a haiku `worker`)
  ccx      the lead must hand it to `ccx run --tradeoff save --review on --context auto`
  direct   no lead: `ccx run` straight to Codex gpt-6-luna low with another vendor's cheap review on
  ccx2     opt-in (--arms ccx2): ccx as the agent-delegate skill now says, spelled out inline (verbatim brief, one
           call `--bg --wait 540` with show --wait as the fallback, default review, trust a passed check, no commit
           request); not in the default schedule
  ccx2-skill opt-in (--arms ccx2-skill, R7): the lead is only told to delegate through ccx as its agent-delegate
           skill says and must load that skill (no inline HOW); needs --claude-isolation ccx-home, a fresh Claude
           home holding ccx's marked block, hooks and skills only (scripts/eval/preflight.py)
  ccx2nc   opt-in (--arms ccx2nc, r6a): exactly ccx2 (the same lead, wording and command line), except that the
           unit's own hub has `[defaults] namecheck = "fail"` in its tiers.toml (asserted from the hub before the
           lead starts), so a sub-agent's change that uses an undefined name fails its run like a failed --check;
           ccx's own default stays "warn". Every row records the hub's mode (`namecheck_mode`) and each builder
           run's own (`ccx_namecheck`: mode, hits, climbs past a hit), counted per arm in the summary
           (`namecheck`), so ccx2 vs ccx2nc measures the change before / after
  ccx2uw   opt-in (--arms ccx2uw): exactly ccx2, only enabling delegate.user_words in the unit hub (asserted
           before launch). The lead's task message supplies original wording; rows record user_words_mode.
  ccx2daily, ccx2daily_nomem, ccx2daily_clean, ccx2daily_leantools
           opt-in (B3, docs/research/2026-10-30-b3-lean-switches-plan.md): exactly ccx2's lead, but the sub-agents
           start with the person's daily setup: Codex in a per-unit home (scripts/eval/daily_home.py) holding copies
           of their ~/.codex memories/, AGENTS.md and skills/ and of ~/.agents/skills, the login copied from the eval
           Codex home (never their auth, credentials, config.toml, sessions or logs), no CCX_CODEX_ISOLATE; Claude
           sub-agents with setting sources user,project,local and skills. On Windows every daily home has
           [windows] sandbox = "unelevated" (a fresh home has no elevated-sandbox secrets and its setup needs UAC;
           recorded as daily.windows_sandbox). Each variant writes one [subagent] switch
           into the unit hub's tiers.toml (read back before the lead starts): codex_memories = false, clean = true,
           codex_lean_tools = true. The eval Codex home gets nothing of the person's (only a login the unit
           refreshed is written back to it, daily_home.sync_login), so every other arm's checks stay as strict; the
           daily arms need --jobs 1. Rows carry `daily` (with the snapshot's sha256) and `sub_usage` (sub-agent
           tokens per class); their sub-agents' skills are recorded by the audit, not problems; summary applies the
           fixed B3 rule (`b3_rules`). `daily-check` builds one such home in a temp folder, lists it, removes it
  builtin2 opt-in (--arms builtin2): builtin's Agent-tool hand-off with ccx2's brief and acceptance wording, word
           for word (the worker reports check / files_changed / diffstat / status); not in the default schedule
  builtin2r opt-in (--arms builtin2r): builtin2 whose worker's own prompt also carries ccx's KEEP_TESTS and WIRING
           rules (imported from ccx/prompts.py), so ccx2 vs builtin2r tells ccx apart from those rules (fairness C5)
  fast, balanced, save, cheapest
           opt-in tier arms (whole-workflow tiers, docs/DECISIONS.md "tiers"): the unit's hub has the person's
           `policy.picked = <tier>` (set as `ccx config set` does: that is the person's choice the arm simulates) and
           the lead is told the person picked it. fast: the lead does it itself; balanced and save: the lead sizes the
           task with `ccx propose --minutes --files` on the person's request verbatim (the brief its run sends, so
           the run's own re-plan agrees) and follows its answer (authorized: run its `next` the ccx2 way, --bg +
           show --wait and ccx2's lean acceptance; self, or a run ccx refuses: do it itself). save is ccx2 through
           the tier path, and its run also carries --minutes / --files, so its model pick comes from that
           difficulty (ccx2's from the brief's keywords): rows keep each run's route (`ccx_routes`) to tell them apart.
           cheapest: no lead, the shipped cheapest tier's script run (CHEAPEST: --tradeoff save --review off, no
           explicit model, no estimate, the repository's existing suite as --check, ccx planning nothing: the
           explicit --tradeoff wins over the hub's pick) in a hub that picked cheapest, its result taken as it is,
           labelled may_be_wrong; unlike direct it has no review, no fixed gpt-6-luna low and no fixed --minutes 60.
           Each row records the tier, what `ccx propose` planned (band, mode, from the unit hub's ledger), the
           reference change's size (non-test code lines / files, and the band those files give), the mode that
           actually ran (ledger actual_mode; none = self), the misbanding (the lead's --files band vs the reference
           files' band, like with like; `misband_overall` keeps the planned band, words + minutes + files, against
           it, which leans over by construction) and whether ccx's --check passed (read on failures); the summary
           adds them per arm (`tiers`)

The lead is sonnet medium unless --lead-model / --lead-effort say otherwise; both are recorded in every row, in its
fingerprint and in the done-key, and a summary shows another lead's units as their own arm (`ccx2@opus-high`).
Likewise a lead that ran in a ccx home (--claude-isolation ccx-home, an arm that uses ccx: ccx's hooks and memory
block reach it) is its own arm (`ccx2@ccx-home`), never pooled with the same arm under flags.
--budget counts the spend of this tag's rows only (plus --extra-spent), not the whole results file.

The summary counts env_clean rows only (rows that are not, or from before the clean room, are left out and their
number printed, per arm too, `excluded_by_arm`; each paired comparison and the tier rule say how many shared units
they lost and on which side, `lost_pairs`, and a tier rule pass with a one-sided loss is Unknown; --include-unclean
counts them, never in the tier rule). Per arm it splits the spend into the lead's (lead_usd: the Claude lead's own
result cost, a builtin worker included) and ccx's (ccx_usd: the hub's runs), each also per success, and the same
for every arm into the lead's own work and the delegated work (lead_only_usd / sub_usd: ccx's sub-agents or the
builtin worker); a skill arm says how many of its leads loaded the skill (`skill_used`). A tag runs on one commit: `run` refuses to go on with a tag whose rows were made at another commit
(the fingerprint keeps `pinned_commit`; --pin-commit SHA also refuses any other HEAD). Every unit's row carries a
`timeline` (scripts/eval/r5_timeline.py, R8): seconds, $ and tokens per role and reason.

The summary pairs every two arms on the units they share (tag, round, task): McNemar exact p (Holm over the pairs),
task-level bootstrap 95% CIs for the cost-per-success and wall-median differences; per arm a Wilson CI, the right
count per round and, for units that used ccx, the wall per phase (sub-agent attempts, checks, reviews, fix rounds,
the lead waiting) from the ccx run records; with arms `balanced` and `save` both present, the tier decision rule
(its right-rate condition is paired: the task-bootstrap 95% CI of balanced's minus save's right answers, in tasks,
must have its lower end at -1 or above; otherwise it is Unknown, not a pass).

--dry-run prices the lead's part of each unit at its own model's list prices (PRICES: Opus vs Sonnet per token
class, weighted by the token mix of this file's measured Sonnet leads, or an assumed mix without them) and prints
the lead / ccx split per arm.

Every unit: the repository at the task commit's parent, with today's tests/conftest.py committed into it (old
commits' tests may predate per-test hubs, #73), a fresh throwaway hub (CCX_HUB, as round 3). The hidden test is the
commit's own test files, run in a throwaway HOME / CCX_HUB / CODEX_HOME / CLAUDE_CONFIG_DIR.

Clean environment (scripts/eval/preflight.py, after round 5h): `run` first checks the machine and refuses to start
when anything fails (another eval or pytest running, modified tracked files, no dedicated Codex home for arms that use
Codex, a work dir with foreign files, a canary lead that sees user-level instructions, ...); `--force-unclean` runs
anyway and every row records it. Each unit then gets its own clean room: an allow-listed environment, its own TMP,
git identity, CCX_CONFIG and DSH_HOME, Claude leads and sub-agents without the user's settings, hooks, CLAUDE.md and
auto-memory and with reads of the real homes denied (`--claude-isolation config-dir`: a fresh CLAUDE_CONFIG_DIR),
Codex in a dedicated CODEX_HOME with --ignore-user-config / --ignore-rules / memories off; everything it starts runs
in one Job Object and whatever survives the unit is listed, killed and logged. Every row carries `fingerprint`
(commit, task-file hash, CLI versions, isolation, concurrency, preflight result), `audit` (what its agents loaded and
which real paths their tool calls named), `leftovers` and `env_clean`. The CLI versions are checked again after
every unit; a change, a busy machine or a process that cannot be killed stops the run (unless --force-unclean,
which loses those rows to the rules; `--wait-quiet MINUTES` instead waits for a quiet machine before the checks and
between units, and the unit that overlapped other work stays not env_clean).
The work dir defaults to <temp>/<tag>, so two tags never share unit folders.

  python scripts/eval/r5.py run --rounds 1 --tasks waiting-evals --codex-home <eval codex home> --budget 3

  python scripts/eval/r5.py run --rounds 1 --tasks waiting-evals --budget 3      # the pilot
  python scripts/eval/r5.py run --rounds 2 --budget 40
  python scripts/eval/r5.py run --rounds 2 --arms ccx,ccx2 --tag r5b --budget 20  # old vs new lead guidance
  python scripts/eval/r5.py run --rounds 2 --arms ccx2,builtin2 --tag r5d --budget 25  # same wording, ccx vs Agent
  python scripts/eval/r5.py run --taskset holdout --rounds 3 --tag ho1 --budget 20   # the unseen hold-out set (C1)
  python scripts/eval/r5.py run --taskset holdout --rounds 3 --arms fast,balanced,save,ccx2,cheapest --tag ho2 \
      --lead-model opus --budget 70 --dry-run          # the schedule and its cost estimate, nothing run
  python scripts/eval/r5.py run --taskset holdout --rounds 3 --arms ccx2 --tag ho4 --lead-model auto --dry-run
      # lead model per task (ccx's lead.model_by_task rule, its own arm ccx2@auto-medium); compare with the
      # same tag under --lead-model opus and the default sonnet
  python scripts/eval/r5.py run --rounds 1 --arms ccx2,ccx2nc,ccx2@auto --tag r6a --budget 10 --dry-run
      # r6a: ccx2, ccx2 with namecheck fail and ccx2 with the lead model per task, interleaved in one invocation
      # (an `<arm>@auto` token is that arm with --lead-model auto for its units only: arm ccx2@auto-medium)
  python scripts/eval/r5.py run --taskset holdout --rounds 3 --arms ccx2,ccx2-skill --tag ho3 --budget 20 \
      --claude-isolation ccx-home      # skill vs inline wording (export CLAUDE_CODE_OAUTH_TOKEN yourself first)
  python scripts/eval/r5.py summary [--taskset holdout] [--include-unclean]
  python scripts/eval/r5_timeline.py summary [--taskset holdout] [--tag ho2]       # where the time went (R8)
  python scripts/eval/r5.py export docs/research/data/2026-10-26-r5.json

Hold-out (--taskset holdout, scripts/eval/tasks_holdout.py): 10 other past changes never used while tuning, for the
final claims, five of them from other open-source repositories (scripts/eval/ext_repo.py: before the canary, each is
cloned once into a temporary folder outside the work dir, from its URL or from a local copy given with
--ext-cache DIR, read into memory and removed; a unit gets the parent's tree as a fresh one-commit repository; the
copies are denied to its agents along with Claude's web tools, pip has no index, and the audit flags installing or
fetching packages; tests run with PYTHONPATH=src and the Python given with --ext-python, which must have the modules
the repository's tests need and not the library itself, and must not sit next to the --ext-cache copies). Its
results go to their own file, and every finished unit's repository, hub and lead stream leave the
work dir after scoring (redacted lead and ccx sub-agent streams are kept under the results artifacts), so a later round's agents cannot find
an earlier round's finished answer next to them. r5 keeps its old behaviour.

Polyglot (--taskset polyglot, scripts/eval/tasks_polyglot.py, P0-5): 30 Python exercises of aider's polyglot
benchmark (Exercism, MIT; chosen in polyglot_selection.json without looking at any solution), an outside benchmark
with a difficulty spread. It reuses the external path above (one clone before the canary, read into memory, removed;
copies and web denied; the audit flags the exercises' public homes), but a unit is an exercise, not a commit
(ext_repo.exercise_material): its repository holds only the solution stubs, the brief is the exercise's instructions
plus aider's kind of addendum, and the hidden test is the exercise's test files, run in a fresh folder that gets only
the solution files the agent left (score_exercise). Its default arms are self, ccx2 and direct (tasks_polyglot.ARMS):

  python scripts/eval/r5.py run --taskset polyglot --rounds 1 --tag pg1 --budget 12 --dry-run
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import random
import shutil
import re
import statistics
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import r2  # noqa: E402
import r3  # noqa: E402
import r4  # noqa: E402
import preflight as PF  # noqa: E402
import seven_ab as S  # noqa: E402
from common import ROOT, append_jsonl, archive_hub, ccx_verify, completion_cost_summary, git, read_jsonl  # noqa: E402
from ccx.prompts import KEEP_TESTS, WIRING  # noqa: E402
import ext_repo  # noqa: E402
import r5_timeline as TL  # noqa: E402
import harness_audit as HA  # noqa: E402
import daily_home as DH  # noqa: E402
import evidence_streams as ES  # noqa: E402
import tasks_holdout  # noqa: E402
import tasks_polyglot  # noqa: E402
import tasks_r5  # noqa: E402

# r5: the 10 tasks the loop was tuned on; holdout (scripts/eval/tasks_holdout.py): 10 others never used for tuning,
# for the final claims (backlog C1). r5 stays the default everywhere.
TASKSETS = {"r5": tasks_r5, "holdout": tasks_holdout, "polyglot": tasks_polyglot}
# a task set's default arms when --arms is not given (r5 and holdout: ARMS)
DEFAULT_ARMS = {"polyglot": tasks_polyglot.ARMS}
IDS = tasks_r5.IDS

OUT = ROOT / ".ccx" / "eval" / "r5"
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def by_id(task_id: str) -> dict:
    """A task of any task set (ids are unique across sets)."""
    for mod in TASKSETS.values():
        if task_id in mod.IDS:
            t = mod.by_id(task_id)
            if is_exercise(t) and _ext_key(t) in _EXT:       # an exercise's brief: its instructions, read at the start
                t = {**t, "brief": _EXT[_ext_key(t)]["brief"]}
            return t
    raise KeyError(f"unknown task: {task_id}")


def results_file(taskset: str) -> Path:
    """Where a task set's results go by default: r5 keeps its old file, the hold-out set has its own."""
    return OUT / ("results.jsonl" if taskset == "r5" else f"{taskset}-results.jsonl")


def pytest_args(task: dict) -> list[str]:
    """The hidden test files, minus the tests a task deselects (unrelated to it and flaky under load)."""
    out = list(task["tests"])
    for node in task.get("deselect") or ():
        out += ["--deselect", node]
    return out
ARMS = ("self", "builtin", "ccx", "direct")
CONFTEST = (ROOT / "tests" / "conftest.py").read_text(encoding="utf-8")
LEAD_PROMPT = """You are the lead agent on this repository: relayline, the `ccx` command (Python, standard library only;
see AGENTS.md). The full test suite takes about 7 minutes, so run the tests that matter for your change, e.g.
`python -m pytest -q tests/test_<area>.py`. The person asked:

{brief}

{how}

When the work is done and the relevant tests pass, end with one line: DONE: <what changed>."""
# A task of another repository (tasks_holdout.REPOS): same shape, that repository's own description. It is not
# installed; PYTHONPATH=src is set (relative, so it also works in a ccx worktree), so tests run from the root.
LEAD_PROMPT_EXT = """You are the lead agent on this repository: {name}. It is not installed, and nothing can be
installed (pip has no package index here): PYTHONPATH=src is set, so from the repository root
`python -m pytest -q tests/...` tests the code in src/. {note}Run the tests that matter for your change. The person
asked:

{brief}

{how}

When the work is done and the relevant tests pass, end with one line: DONE: <what changed>."""
# A polyglot exercise (tasks_polyglot): a folder with the solution stubs only; the brief is the exercise's own
# instructions (they say where the solution goes and that the tests are hidden).
LEAD_PROMPT_EXERCISE = """You are the lead agent on this repository: {name}. It is a folder with the files to
complete and nothing else. Nothing can be installed (pip has no package index here); `python -m pytest` works.
The person asked:

{brief}

{how}

When the work is done, end with one line: DONE: <what changed>."""
HOW_CCX = ("Do not edit files yourself: hand the implementation to a sub-agent through ccx. Run\n"
           "  {ccx} run --tradeoff save --review on --context auto --mode write --new --no-ab --label {label} "
           "--check \"<a pytest command for the relevant test files>\" \"<a brief that contains everything it needs>\"\n"
           "It prints one JSON object (run_id, ok, summary, check, review, ...). When it reports back, check the "
           "result (read the diff, run the tests); if something is wrong or missing, send it back with\n"
           "  {ccx} resume <run_id> \"<what to fix>\"")
# ccx2 (opt-in, `--arms ccx2`): the lead follows the agent-delegate skill's "Delegate cheaply" guidance written
# after round 5 (verbatim brief, --bg + show --wait, default review, trust a passed check, no commit request)
# The brief and acceptance guidance is shared word for word with builtin2, so the two differ only in how the work
# is handed away (ccx vs the Agent tool). LEAN_ACCEPT's {send_back} is filled per arm.
LEAN_BRIEF = ("The brief is the person's request above copied verbatim (do not re-word interfaces, names, strings or "
              "numbers), plus file paths you already know and the acceptance command; do not read the code base "
              "first to write it, and do not ask the sub-agent to commit.")
LEAN_ACCEPT = ("When the result's check passed and its files_changed / diffstat fit the request, accept it without "
               "re-running the tests or reading the full diff; only if the check failed or is missing, or the status "
               "is partial or blocked, look yourself and send it back with\n"
               "  {send_back}\n"
               "After accepting, commit the work yourself.")
# One call (A2, #147): `--bg --wait 540` starts the run and waits for it in the same call, so the lead makes one
# request less than `--bg` then `show --wait`. 540 s stays under the 600 s Bash limit the lead is told to set (at
# 600 the tool could be cut before ccx prints); a run still going then prints its run_id, and the fallback is the
# old wait. WAIT_ONE_CALL is shared by ccx2 and the tier arms so they are told it in the same words.
WAIT_SECONDS = 540
BASH_TIMEOUT_MS = 600000
WAIT_ONE_CALL = (f"Run it with the Bash tool's timeout set to {BASH_TIMEOUT_MS}: `--bg --wait {WAIT_SECONDS}` starts "
                 f"the run and waits up to {WAIT_SECONDS} s for it in the same call, then prints the final result. "
                 "If it is still running when that call returns (it prints the run_id and a running status "
                 "instead), wait with\n"
                 "  {ccx} show <run_id> --wait\n"
                 "and call that again while it says the run is still running (never resume a running run; do not "
                 "pipe ccx output through tail or head).")
HOW_CCX2 = ("Do not edit files yourself: hand the implementation to a sub-agent through ccx. Run\n"
            f"  {{ccx}} run --bg --wait {WAIT_SECONDS} --tradeoff save --context auto --mode write --new --no-ab "
            "--label {label} --check \"<a pytest command for the relevant test files>\" \"<brief>\"\n"
            + WAIT_ONE_CALL + " " + LEAN_BRIEF + " "
            + LEAN_ACCEPT.replace("{send_back}", "{ccx} resume <run_id> \"<what to fix>\""))
# ccx2-skill (opt-in, `--arms ccx2-skill`, R7): the lead is told only to delegate as its agent-delegate skill says
# and must load that skill; no command, flag or acceptance rule is given inline (HOW_CCX2 spells all of them out,
# so ccx2 measures the eval's wording, this arm what the shipped skill teaches). It needs a lead whose Claude home
# has the skill: `--claude-isolation ccx-home` (preflight.py), checked by cmd_run.
HOW_CCX2_SKILL = ("Do not edit files yourself: hand the implementation to a sub-agent through ccx. Load your "
                  "`agent-delegate` skill first (Skill tool) and follow what it says for how to start the run, wait "
                  "for it, check the result and send it back; the person has authorized this delegation. Do not "
                  "ask the sub-agent to commit; after accepting, commit the work yourself.")
# builtin2 (opt-in, `--arms builtin2`): builtin's Agent-tool hand-off with ccx2's lean brief and acceptance, so a
# ccx2 vs builtin win is not just the instruction. The worker runs the acceptance command itself and reports what a
# ccx result carries (check, files_changed, diffstat, status).
HOW_BUILTIN2 = ("Do not edit files yourself: hand the implementation to your sub-agent. Call the Agent tool with "
                "subagent_type `worker` and the brief, and tell the worker to run the acceptance command (a pytest "
                "command for the relevant test files) when it is done and to report its status (done, partial or "
                "blocked), that command's result line (the check), the files it changed (files_changed) and "
                "`git diff --shortstat` (diffstat). " + LEAN_BRIEF + " "
                + LEAN_ACCEPT.replace("{send_back}", "another Agent call to the worker, saying what to fix"))
# builtin2r (opt-in, `--arms builtin2r`): builtin2's lead wording, and a worker whose own prompt also carries the
# rules every ccx sub-agent gets (ccx/prompts.py, imported, not retyped): keep existing tests, test through the
# named entry point; and it is told to run the acceptance command (targeted tests while it works), as a ccx sub-agent
# with --check is, instead of the whole suite. ccx2 vs builtin2r then differs by ccx alone, not by these rules
# (fairness C5).
# The base worker prompt's "run the tests with `python -m pytest -q`" (the whole suite) would contradict WIRING's
# "run only the relevant test files, not the whole suite", so builtin2r's worker is told what a ccx sub-agent with
# --check is (SELFCHECK_CMD, in short): run the acceptance command it is given, targeted tests while it works.
WORKER_TESTS_BASE = "run the tests with `python -m pytest -q`"
WORKER_TESTS_R = ("run the acceptance command you are given (while you work, only the targeted tests touching your "
                  "change; the full acceptance command at most once, at the end)")
assert WORKER_TESTS_BASE in r3.WORKER["worker"]["prompt"]
WORKER_RULES = {"worker": {**r3.WORKER["worker"],
                           "prompt": r3.WORKER["worker"]["prompt"].replace(WORKER_TESTS_BASE, WORKER_TESTS_R)
                           + " Rules: " + KEEP_TESTS + " " + WIRING.rstrip()}}
# tier arms (opt-in, `--arms fast,balanced,save,cheapest`): the person picked the tier in the unit hub's settings
# (policy.picked); the lead is told so. fast never delegates, so its lead is not sent through ccx propose
TIER_PICKED = ("The person picked the tier `{tier}` in their own ccx settings (`policy.picked`): it decides who does "
               "each piece of work and pre-authorises what it delegates, so do not ask them anything about it.")
HOW_FAST = TIER_PICKED + " Under `fast` every piece is yours: do the work yourself."
# balanced / save: size the task with ccx propose and follow its answer; a delegated run is run and accepted the ccx2
# way (--bg + show --wait, LEAN_BRIEF, LEAN_ACCEPT). save vs ccx2 is not the tier path alone: save's run carries the
# lead's --minutes / --files, so its model pick comes from that difficulty (ccx2's run has neither and falls back to
# the brief's keywords), and the lead makes one more call (rows keep each run's route, `ccx_routes`).
# The proposal is made on the person's request verbatim, the text its run sends: `ccx run --proposal` re-plans the
# run's own brief (a tier's hard / uncertain rules), and a one-line paraphrase that drops a state-machine word
# (resume, kill, ...) would be authorised by propose and then refused by the run.
HOW_TIER = (TIER_PICKED + " Before you start, size the work and ask ccx, giving it the person's request above "
            "copied verbatim (the same text your brief starts with):\n"
            "  {ccx} propose --lead claude:{model}:{effort} --minutes <minutes a skilled engineer would need> "
            "--files <how many source files the change touches> \"<the person's request, verbatim>\"\n"
            "It prints one JSON object. If it says `authorized: true`, do not edit files yourself: run its `next` "
            "command once (`{ccx} run ...` with its --proposal and the same --minutes and --files), adding "
            f"`--bg --wait {WAIT_SECONDS} --context auto --mode write --new --no-ab --label {{label}} --check \"<a "
            "pytest command for the relevant test files>\"` and the brief. " + WAIT_ONE_CALL + " " + LEAN_BRIEF + " "
            + LEAN_ACCEPT.replace("{send_back}", "{ccx} resume <run_id> \"<what to fix>\"")
            + " If it says the tier has you do it (no `authorized: true`), do the work yourself. If `ccx run` "
            "refuses the proposal (it prints `ok: false` and an error instead of a run_id), do not propose again: "
            "do the work yourself.")


def ccx_lead_model(model: str) -> str:
    """The lead's model as ccx's --lead rung names it (claude:<alias>:<effort>): a full model id such as
    claude-opus-4-7 is not a rung ccx knows (`ccx propose` fails, and the tier lead would silently do it itself),
    so the family alias it names is passed; anything else as given."""
    m = str(model or "").lower()
    return next((x for x in ("opus", "sonnet", "haiku") if x in m), model)
# the whole-workflow tier arms (opt-in): named as the tiers, so tier_rule (balanced vs save) reads them
TIER_ARMS = ("fast", "balanced", "save", "cheapest")
TIER_LEAD_ARMS = ("balanced", "save")            # the lead sizes with ccx propose and follows its answer
SKILL_ARMS = PF.SKILL_ARMS                       # the lead loads the agent-delegate skill (needs ccx-home)
# namecheck arms (opt-in): ccx2 in a unit hub whose tiers.toml sets [defaults] namecheck to this mode
NAMECHECK_ARMS = {"ccx2nc": "fail"}
USER_WORDS_ARMS = ("ccx2uw",)  # opt-in: ccx2 wording/flags, only delegate.user_words differs
# daily-config arms (opt-in, B3 item 2; scripts/eval/daily_home.py): ccx2's lead and wording, but its sub-agents
# start with the person's everyday setup (Codex memories, AGENTS.md and skills copied into a per-unit Codex home whose
# login is the eval home's; Claude with the user settings layer and skills), and each variant turns one experimental
# [subagent] switch on in the unit hub's tiers.toml (a config overlay, the code is the same)
DAILY_ARMS = {"ccx2daily": {}, "ccx2daily_nomem": {"codex_memories": False}, "ccx2daily_clean": {"clean": True},
              "ccx2daily_leantools": {"codex_lean_tools": True}}
# leads that may hand work to ccx (session file, metrics)
CCX_ARMS = ("ccx", "ccx2", "ccx2small", *NAMECHECK_ARMS, *USER_WORDS_ARMS, *SKILL_ARMS, *TIER_LEAD_ARMS, *DAILY_ARMS)
BUILTIN_ARMS = PF.BUILTIN_ARMS
# not in ARMS: the default schedule (and old tags' done-keys) stay
OPT_IN_ARMS = ("ccx2", "ccx2small", "builtin2", "builtin2r", *TIER_ARMS, *SKILL_ARMS, *NAMECHECK_ARMS, *USER_WORDS_ARMS, *DAILY_ARMS)
DEFAULT_LEAD = (r3.LEAD_MODEL, r3.LEAD_EFFORT)
# --lead-model auto: each task's lead model from its difficulty by ccx's lead.model_by_task rule (ccx/leadmodel.py,
# this checkout's config/tiers.toml [lead] / [lead_by_task], never the hub's settings), so the next round can compare
# auto with fixed opus and fixed sonnet. Its units are their own arm (`ccx2@auto-medium`).
LEAD_AUTO = "auto"
# with both of these arms present the summary checks the tier decision rule (tier_rule)
TIER_RULE_ARMS = ("balanced", "save")
DIRECT = ["--to", "codex", "--model", "gpt-6-luna", "--effort", "low", "--review", "on", "--context", "off",
          "--no-escalate", "--no-fallback"]
# cheapest (opt-in): the shipped cheapest tier as a script / CI runs it (docs/DECISIONS.md, tiers: "only a script or
# CI calling `ccx run` itself"), in a hub whose person picked cheapest. Unlike DIRECT: no explicit model (the tier's
# delegated part picks it like save: --tradeoff save, as propose's `next` has it), no fixed --minutes (a script
# has nobody to size the task: ccx then makes no tier plan for the run, which changes nothing here since cheapest
# sends every band direct, and its model comes from the brief's keywords, as ccx2's does; a lead's cheapest run
# would carry its --minutes / --files and pick from that difficulty, like save's), --review off (nobody re-checks: its result is taken as it is, may_be_wrong), ccx's own escalation and
# fallback. --to codex: the other arms' delegated part goes from a Claude lead to Codex, and the eval's isolation
# prepares Codex for this arm (preflight CODEX_ARMS); --context off: no conversation to attach. Its --check is the
# repository's existing suite (suite_check), what a script or CI passes: it names no task's test file, so it gives the
# hidden test away no more than the repository itself does, and the shipped path's "take its --check result as it is"
# and save's climb on a failed ccx re-check both happen (ccx_check_passed is read like the lead arms'). Direct keeps
# no --check (the r5 plan). The explicit --tradeoff save wins over the hub's policy.picked (commands/common.resolve)
# and, unsized, the run gets no tier plan: ccx plans nothing for this arm, and its row's tier_plan says so
# (source "eval-script", ccx_planned false). policy.picked = cheapest is set so the hub is the person's setup.
CHEAPEST = ["--to", "codex", "--tradeoff", "save", "--review", "off", "--context", "off"]
SUITE = "python -m pytest -q tests"


def suite_check(task: dict) -> str:
    """The cheapest arm's --check: the task repository's whole existing suite (a hold-out repository's own `suite`
    when it has one). The same command for every task of a repository: this repository's known-flaky nodes (the
    union of all its tasks' deselects, dropped candidates too) are left out for every task alike, so it says
    nothing about any one task."""
    spec = ext_spec(task)
    if spec:
        return spec.get("suite") or SUITE
    flaky = sorted({n for mod in TASKSETS.values() for t in [*mod.T, *getattr(mod, "DROPPED", [])]
                    if not t.get("repo") for n in t.get("deselect") or ()})
    return " ".join([SUITE, *(f"--deselect {n}" for n in flaky)])


def no_lead_flags(arm: str) -> list[str]:
    """The ccx run flags of an arm without a lead (direct, cheapest)."""
    return CHEAPEST if arm == "cheapest" else DIRECT


def ext_spec(task: dict) -> dict | None:
    """The other repository a task belongs to (tasks_holdout.REPOS, tasks_polyglot.REPOS), or None for a task of
    this one."""
    if not task.get("repo"):
        return None
    return tasks_holdout.REPOS.get(task["repo"]) or tasks_polyglot.REPOS[task["repo"]]


def is_exercise(task: dict) -> bool:
    """A polyglot exercise (tasks_polyglot): a folder at a pinned commit, not a commit's change."""
    return task.get("kind") == "exercise"


def ext_cache(work: Path) -> Path:
    """Where a run keeps its clones of the other repositories (one per repository per work dir)."""
    return Path(work) / "ext-cache"


_FETCH = threading.Lock()
# (repo, commit, tests) -> ext_repo.material: what the units of an external task need, read once out of the clone.
# A run fills it before the first unit from a clone outside the work dir that it then removes (prepare_external).
_EXT: dict[tuple, dict] = {}


def ext_clone(task: dict, work: Path, source: str | Path | None = None, cache: Path | None = None) -> Path:
    """The cached clone of a task's repository, fetched on first use (one fetch at a time) and its sha checked."""
    with _FETCH:
        repo = ext_repo.fetch(task["repo"], ext_spec(task), Path(cache) if cache else ext_cache(work),
                              Path(source) if source else None)
        ext_repo.pin(repo, task["commit"])
    return repo


def _ext_key(task: dict) -> tuple:
    return (task["repo"], task["commit"], tuple(task["tests"]), task.get("dir") or "")


def ext_material(task: dict, work: Path | None = None, source: str | Path | None = None,
                 cache: Path | None = None) -> dict:
    """The task's material (ext_repo.material), read from its clone on first use: the clone in `cache`, else in the
    work dir's ext-cache (holdout_check; a run has always filled it before, from outside the work dir)."""
    key = _ext_key(task)
    if key not in _EXT and is_exercise(task):
        if cache is None:
            raise RuntimeError(f"{task['id']}: an exercise's material is read before the run (prepare_external), "
                               "never cloned into the work dir")
        with _FETCH:
            repo = ext_repo.fetch(task["repo"], ext_spec(task), Path(cache) if cache else ext_cache(work),
                                  Path(source) if source else None)
        m = ext_repo.exercise_material(repo, task["commit"], task["dir"], task["solution"], task["tests"])
        m["brief"] = tasks_polyglot.brief(task, m["docs"])
        with _FETCH:
            _EXT.setdefault(key, m)
    if key not in _EXT:
        repo = ext_clone(task, work, source, cache)
        m = ext_repo.material(repo, task["commit"], task["tests"])
        with _FETCH:
            _EXT.setdefault(key, m)
    return _EXT[key]


def make_repo(task: dict, dest: Path, work: Path | None = None, source: str | Path | None = None) -> None:
    """The repository at the commit's parent, today's conftest committed into it. A task of another repository:
    the parent's tree alone in a fresh repository (ext_repo.repo_from_tar), nothing of this one added."""
    r2._rmtree(dest)
    if ext_spec(task):
        ext_repo.repo_from_tar(ext_material(task, work or dest.parent, source)["tar"], ext_spec(task), dest)
        return
    dest.mkdir(parents=True)
    data = subprocess.run(["git", "archive", f"{task['commit']}^"], cwd=ROOT, capture_output=True, check=True).stdout
    tarfile.open(fileobj=io.BytesIO(data)).extractall(dest)
    (dest / "tests" / "conftest.py").write_text(CONFTEST, encoding="utf-8")
    git(dest, "init", "-q")
    git(dest, "add", "-A")
    git(dest, "commit", "-q", "-m", "start")


def ext_python(a=None) -> str:
    """The Python that runs another repository's tests (and that its agents find first on PATH)."""
    return str(getattr(a, "ext_python", "") or sys.executable)


def task_env(task: dict, env: dict, python: str | None = None) -> dict:
    """A unit's environment for its task: for another repository, PYTHONPATH=src and its Python first on PATH."""
    spec = ext_spec(task)
    if not spec:
        return env
    py = python or sys.executable
    return {**env, **ext_repo.run_env(spec), "PATH": str(Path(py).parent) + os.pathsep + env.get("PATH", "")}


def ext_note(spec: dict) -> str:
    """The repository's own remark for the lead prompt (e.g. a test file that needs plugins not installed)."""
    return f"{spec['note']} " if spec.get("note") else ""


# what the audit flags in an external unit's tool calls: the run's clone folder, installing or downloading packages,
# fetching from the code hosts or package index (the released library has the fix)
EXT_FLAGS = (r"ext-cache", r"\bpip3?(\.exe)?[\"']?\s+(install|download)\b", r"-m\s+pip\s+(install|download)\b",
             r"\b(curl|wget|invoke-webrequest|iwr|invoke-restmethod|irm|git\s+clone)\b[^\n]*"
             r"(github\.com|gitlab\.com|pypi\.org|pythonhosted\.org)")


def ext_guard(task: dict, a, work: Path) -> dict:
    """Unit fields for an external task: folders denied (the work dir's ext-cache, the --ext-cache copies), Claude's
    web tools denied, and the audit's flags (EXT_FLAGS, the repository's URL, the copies' folder by its last two
    names, so a relative path to it is flagged too)."""
    spec = ext_spec(task)
    if not spec:
        return {}
    hidden, flags = [ext_cache(work)], list(EXT_FLAGS) + list(spec.get("flags") or ())
    url = re.sub(r"^\w+://|\.git$", "", spec["url"]).lower()
    flags.append(re.escape(url))
    src = getattr(a, "ext_cache", "") or ""
    if src:
        sp = Path(src).expanduser()
        hidden.append(sp)
        flags.append(re.escape(f"{sp.parent.name}/{sp.name}".lower()))
    return {"hidden": tuple(hidden), "deny": ("WebFetch", "WebSearch"), "flags": tuple(flags)}


def iso_env(d: Path, python: str | None = None) -> dict:
    env = {k: v for k, v in PF.base_env().items() if not k.endswith(PF.ENV_KEEP_SUFFIX)
           and not k.startswith(("CCX_", "CLAUDE", "CODEX"))}
    env["PYTHONIOENCODING"] = "utf-8"
    env["PATH"] = str(Path(python or sys.executable).parent) + os.pathsep + env.get("PATH", "")
    env.update({"TMP": str(d / "tmp"), "TEMP": str(d / "tmp"), "TMPDIR": str(d / "tmp"), "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": str(d / "gitconfig")})
    (d / "tmp").mkdir(parents=True, exist_ok=True)
    (d / "gitconfig").write_text("[user]\n\tname = eval\n\temail = eval@example.invalid\n", encoding="utf-8")
    for var, sub in (("CCX_HUB", "hub"), ("CODEX_HOME", "codex-home"), ("CLAUDE_CONFIG_DIR", "claude-home"),
                     ("HOME", "home"), ("USERPROFILE", "home")):
        (d / sub).mkdir(parents=True, exist_ok=True)
        env[var] = str(d / sub)
    env["CCX_CONFIG"] = str(d / "user-config.toml")
    return env


def hidden(task: dict, work: Path, source: str | Path | None = None) -> dict[str, bytes]:
    """The commit's own test files: from this checkout, or from the cached clone of the task's repository."""
    if ext_spec(task):
        return ext_material(task, work, source)["tests"]
    return {t: subprocess.run(["git", "show", f"{task['commit']}:{t}"], cwd=ROOT, capture_output=True,
                              check=True).stdout for t in task["tests"]}


def score(repo: Path, task: dict, work: Path, job: PF.Job | None = None, python: str | None = None,
          source: str | Path | None = None) -> dict:
    """The commit's own test files (overwriting whatever the agent left in them), in throwaway homes. Another
    repository's: its test folder and test configuration put back from the parent first (ext_repo.
    restore_test_setup), no conftest of ours, its install-time stubs put back if gone, PYTHONPATH=src, `python`."""
    if is_exercise(task):
        return score_exercise(repo, task, work, job, python, source)
    spec = ext_spec(task)
    if spec:
        m = ext_material(task, work, source)
        ext_repo.restore_test_setup(repo, m["tar"], spec, keep=m["changed"])
    for t, body in hidden(task, work, source).items():
        (repo / t).parent.mkdir(parents=True, exist_ok=True)
        (repo / t).write_bytes(body)
    if spec:
        ext_repo.write_stubs(repo, spec)
    else:
        (repo / "tests" / "conftest.py").write_text(CONFTEST, encoding="utf-8")
    py = python or sys.executable
    iso = Path(tempfile.mkdtemp(prefix="r5iso-", dir=work))
    try:
        env = iso_env(iso, py)
        if spec:
            env.update(ext_repo.run_env(spec))
        color = ["--color=no"] if spec else []         # humanize's addopts asks for colour: keep the row's text plain
        out, err, rc, _left = PF.run([py, "-m", "pytest", "-q", "-p", "no:cacheprovider", *color,
                                      *pytest_args(task)], cwd=repo, env=env, timeout=900, job=job)
        full = ANSI.sub("", (out or "") + (f"\n--- stderr ---\n{err}" if err else ""))
        if rc == -9:
            return {"ok": False, "pytest": "timeout", "output": full, "failed": failed_ids(full)}
        tail = ANSI.sub("", (out.strip().splitlines() or [""])[-1])
        return {"ok": rc == 0, "pytest": tail[:200], "output": full, "failed": failed_ids(full)}
    finally:
        r2._rmtree(iso)


EXERCISE_TIMEOUT = 300     # s for an exercise's hidden tests (a search that never ends must not hold the run)
SUMMARY_COUNT = re.compile(r"(\d+) (passed|failed|errors?|skipped|xfailed|xpassed|deselected)\b")


def exercise_passed(rc: int, tail: str, n_tests: int | None) -> bool:
    """Right only when pytest's summary line shows every hidden test passed and nothing else: rc 0 alone is not
    enough (a solution that raises unittest.SkipTest or exits 0 at import would pass with no test run). With the
    exercise's test count known (the selection's `tests`), exactly that many must pass."""
    counts: dict[str, int] = {}
    for n, kind in SUMMARY_COUNT.findall(tail or ""):
        counts[kind.rstrip("s") if kind.startswith("error") else kind] = int(n)
    passed = counts.pop("passed", 0)
    return rc == 0 and passed > 0 and not any(counts.values()) and (n_tests is None or passed == n_tests)


def score_exercise(repo: Path, task: dict, work: Path, job: PF.Job | None = None, python: str | None = None,
                   source: str | Path | None = None) -> dict:
    """A polyglot exercise's hidden tests: a fresh folder gets the solution files the agent left (only those: its own
    tests, conftest.py or pytest settings never apply), the exercise's test files and a pytest.ini of its own (so
    pytest looks for no configuration above it), and pytest runs there in throwaway homes. A missing solution file
    is a failure, not an error."""
    py = python or sys.executable
    iso = Path(tempfile.mkdtemp(prefix="r5iso-", dir=work))
    try:
        dest = iso / "score"
        dest.mkdir()
        missing = [f for f in task["solution"] if not (repo / f).is_file()]
        for f in task["solution"]:
            if (repo / f).is_file():
                (dest / f).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(repo / f, dest / f)
        for t, body in hidden(task, work, source).items():
            (dest / t).parent.mkdir(parents=True, exist_ok=True)
            (dest / t).write_bytes(body)
        (dest / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
        if missing:
            return {"ok": False, "pytest": f"missing solution file(s): {', '.join(missing)}", "output": "",
                    "failed": []}
        env = {**iso_env(iso, py), **ext_repo.run_env(ext_spec(task)), "PYTHONNOUSERSITE": "1"}
        out, err, rc, _left = PF.run([py, "-s", "-m", "pytest", "-q", "-p", "no:cacheprovider", "--color=no",
                                      *task["tests"]], cwd=dest, env=env, timeout=EXERCISE_TIMEOUT, job=job)
        full = ANSI.sub("", (out or "") + (f"\n--- stderr ---\n{err}" if err else ""))
        if rc == -9:
            return {"ok": False, "pytest": "timeout", "output": full, "failed": failed_ids(full)}
        tail = ANSI.sub("", (out.strip().splitlines() or [""])[-1])
        return {"ok": exercise_passed(rc, tail, task.get("n_tests")), "pytest": tail[:200], "output": full,
                "failed": failed_ids(full)}
    finally:
        r2._rmtree(iso)


FAILED_LINE = re.compile(r"^(?:FAILED|ERROR) (\S+)", re.M)


def failed_ids(output: str, limit: int = 100) -> list[str]:
    """The failing test ids of a pytest run, from its short summary (`FAILED path::test - ...`, `ERROR path`)."""
    out = []
    for m in FAILED_LINE.finditer(output or ""):
        if m.group(1) not in out:
            out.append(m.group(1))
    return out[:limit]


ARTIFACT_MAX = 5_000_000      # bytes kept of one artifact file


def final_diff(repo: Path) -> str | None:
    """Everything the unit changed since the start commit, committed or not, new files included (before scoring: the
    hidden tests are not in it)."""
    if not (Path(repo) / ".git").exists():
        return None
    start = (git(repo, "rev-list", "--max-parents=0", "HEAD").split() or [None])[0]
    if not start:
        return None
    git(repo, "add", "-A", "-N")
    # bytes, not git()'s text mode: universal newlines would drop the \r of CRLF lines and the patch would not apply
    out = subprocess.run(["git", "diff", "--binary", start], cwd=repo, capture_output=True).stdout
    return out.decode("utf-8", errors="surrogateescape")


def _minutes(v: str) -> float:
    try:
        x = float(v)
    except ValueError:
        x = -1.0
    if not 0 < x <= 24 * 60:
        raise argparse.ArgumentTypeError("minutes: more than 0, at most 1440")
    return x


def run_artifacts_dir(out: Path, stamp: str | None = None) -> tuple[str, Path]:
    """This invocation's evidence folder, created here so no other run gets it: <results>-artifacts/<UTC start>Z/ (a
    taken name gets a suffix), so the folders of an aborted run never mix with this one's. Rows from before keep
    theirs flat in <results>-artifacts/ (no `artifacts.run`)."""
    stamp = stamp or time.strftime("%Y%m%d-%H%M%SZ", time.gmtime())
    base = Path(out).parent / f"{Path(out).stem}-artifacts"
    base.mkdir(parents=True, exist_ok=True)
    run, n = stamp, 1
    while True:
        try:
            (base / run).mkdir()
            return run, base / run
        except FileExistsError:
            n += 1
            run = f"{stamp}-{n}"


QUIET_POLL_S = 30


QUIET_CHECKS = 2           # after a busy spell, this many quiet checks in a row (QUIET_POLL_S apart) count as quiet


def _busy_now(ours: list[str] | None = None) -> list[str] | None:
    """Other heavy work on this machine (preflight.busy), or None when the processes cannot be listed."""
    procs = PF.snapshot()
    if procs is None:
        return None
    return PF.busy(procs, ours=ours, exclude=PF.job_pids_all())


def wait_quiet(minutes: float, sleep=time.sleep, now=time.monotonic, busy=None) -> bool:
    """Wait until no other heavy work runs on this machine (preflight.busy: another eval, a pytest, `ccx run`,
    `claude -p`, `codex exec`), checking every QUIET_POLL_S seconds, at most `minutes`. A machine quiet at the first
    look is quiet at once; after a busy spell it takes QUIET_CHECKS quiet checks in a row (another session's tests
    come and go). True: quiet. False: still busy, or the processes cannot be listed (`busy` returns None: waiting
    would not help, the preflight reports it). A unit that runs while another session's tests run is not env_clean;
    --force-unclean would run on anyway and lose those rows to the rules."""
    busy = busy or _busy_now
    end = now() + minutes * 60
    found = busy()
    if found is None:
        print("[wait-quiet] cannot list processes: not waiting", flush=True)
        return False
    if not found:
        return True
    print(f"[wait-quiet] {len(found)} other heavy process(es), e.g. {found[0][:120]}; waiting up to {minutes:g} min",
          flush=True)
    quiet = 0
    while now() < end:
        sleep(min(QUIET_POLL_S, max(0.0, end - now())))
        found = busy()
        if found is None:
            print("[wait-quiet] cannot list processes: not waiting", flush=True)
            return False
        quiet = 0 if found else quiet + 1
        if quiet >= QUIET_CHECKS:
            print("[wait-quiet] quiet: going on", flush=True)
            return True
    print(f"[wait-quiet] still busy after {minutes:g} min", flush=True)
    return False


def keep_artifacts(dest: Path, row: dict, sc: dict | None, diff: str | None) -> None:
    """A unit that was not right (and every polyglot exercise unit): its failing hidden test ids in the row
    (`hidden_failed`, empty for a right one) and, under dest, the full hidden pytest output and its final diff, written
    before the unit's folders are cleaned (`artifacts`: where)."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    kept = []
    if sc is not None:
        row["hidden_failed"] = sc.get("failed") or []
        (dest / "hidden-pytest.txt").write_text((sc.get("output") or "")[:ARTIFACT_MAX], encoding="utf-8",
                                                newline="")
        kept.append("hidden-pytest.txt")
    if diff is not None:
        # newline="": git's exact bytes back (write_text would turn every \n into \r\n on Windows)
        (dest / "final.diff").write_text(diff[:ARTIFACT_MAX], encoding="utf-8", errors="surrogateescape", newline="")
        kept.append("final.diff")
    if kept:
        row["artifacts"] = {"dir": dest.name, "files": kept}


def changed(repo: Path) -> dict:
    """What changed since the start commit, committed or not (leads follow AGENTS.md and commit their work)."""
    start = git(repo, "rev-list", "--max-parents=0", "HEAD").split()[0]
    git(repo, "add", "-A", "-N")
    files = [x for x in git(repo, "diff", "--name-only", start).splitlines() if x.strip()]
    return {"files_changed": len(files), "diffstat": git(repo, "diff", "--shortstat", start).strip(),
            "commits": len(git(repo, "rev-list", f"{start}..HEAD").split())}


def lead_how(arm: str, label: str, lead: tuple[str, str] = DEFAULT_LEAD) -> str:
    """What the lead is told about how to do the work, per arm (`lead`: its own model and effort, which a tier arm's
    lead passes to ccx propose as --lead)."""
    if arm == "ccx":
        return HOW_CCX.format(ccx=r3.CCX_CMD, label=label)
    if arm == "ccx2small":
        return (HOW_CCX2.format(ccx=r3.CCX_CMD, label=label) +
                " If ccx returns state=small_self, implement and check the task yourself, then commit it; "
                "do not retry with --force.")
    if arm == "ccx2" or arm in NAMECHECK_ARMS or arm in USER_WORDS_ARMS or arm in DAILY_ARMS:   # same lead
        return HOW_CCX2.format(ccx=r3.CCX_CMD, label=label)
    if arm in SKILL_ARMS:
        return HOW_CCX2_SKILL
    if arm in ("builtin2", "builtin2r"):          # builtin2r: the same lead wording, the rules are in the worker
        return HOW_BUILTIN2
    if arm == "fast":
        return HOW_FAST.format(tier=arm)
    if arm in TIER_LEAD_ARMS:
        return HOW_TIER.format(tier=arm, ccx=r3.CCX_CMD, label=label, model=ccx_lead_model(lead[0]), effort=lead[1])
    return r3.HOW[arm]


def lead_flags_arm(arm: str) -> str:
    """The round-3 arm whose lead command line (tools, agents, session file) this arm uses."""
    if arm == "fast":                             # the lead does it all itself: self's command line
        return "self"
    return "ccx" if arm in CCX_ARMS else "builtin" if arm in BUILTIN_ARMS else arm


def skill_argv(argv: list[str]) -> list[str]:
    """A lead command line that may load skills: no --disable-slash-commands (Claude Code 2.1.309: it "disables all
    skills and commands") and the Skill tool added to --tools and --allowed-tools."""
    out = [x for x in argv if x != "--disable-slash-commands"]
    for flag, sep in (("--tools", ","), ("--allowed-tools", " ")):
        if flag in out:
            i = out.index(flag) + 1
            if "Skill" not in out[i].replace(",", " ").split():
                out[i] = out[i] + sep + "Skill"
    return out


def worker_agents(arm: str) -> dict | None:
    """The --agents definition for a builtin arm's lead (None: r3.WORKER, as before)."""
    return WORKER_RULES if arm == "builtin2r" else None


# ccx straight from the command line: no Claude lead, --lead-model changes nothing (cheapest: the shipped cheapest
# tier's script run, CHEAPEST, in a hub whose person picked cheapest)
NO_LEAD_ARMS = ("direct", "cheapest")


def has_lead(arm: str) -> bool:
    return arm not in NO_LEAD_ARMS


def lead_of(r: dict) -> tuple[str, str]:
    """A unit's or row's lead (model, effort); rows from before --lead-model had the default. An arm without a lead
    (direct) always counts as the default, whatever a row carries, so its units and rows keep one key, folder, label
    and summary arm under any --lead-model (they are not re-run, and they pool and pair as one arm)."""
    if not has_lead(r.get("arm") or ""):
        return DEFAULT_LEAD
    return (r.get("lead_model") or DEFAULT_LEAD[0], r.get("lead_effort") or DEFAULT_LEAD[1])


CCX_HOME_SUFFIX = "@ccx-home"


def in_ccx_home(r: dict) -> bool:
    """Whether a unit's or row's lead ran in a ccx home (--claude-isolation ccx-home and an arm in CCX_ARMS: ccx's
    hooks and CLAUDE.md block reached the lead, so it was told more than the same arm under flags). Units carry
    `ccx_home`; rows from before the field: their fingerprint's isolation says so."""
    if "ccx_home" in r:
        return bool(r["ccx_home"])
    return ((r.get("fingerprint") or {}).get("isolation") or {}).get("claude_home") == "ccx"


def is_auto(r: dict) -> bool:
    """A unit or row whose lead model was picked per task (--lead-model auto): its own arm, whatever it picked."""
    return r.get("lead_pick") == LEAD_AUTO and has_lead(r.get("arm") or "")


def _lead_suffix(r: dict) -> str:
    m, e = lead_of(r)
    if is_auto(r):                       # never pooled with the fixed sonnet / opus arms it picks between
        return "@" + re.sub(r"[^\w.-]", "_", f"{LEAD_AUTO}-{e}")
    return "" if (m, e) == DEFAULT_LEAD else "@" + re.sub(r"[^\w.-]", "_", f"{m}-{e}")


def _arm_suffix(r: dict) -> str:
    """The lead's suffix, then `@ccx-home` for a lead in a ccx home."""
    return _lead_suffix(r) + (CCX_HOME_SUFFIX if in_ccx_home(r) else "")


def arm_of(r: dict) -> str:
    """The arm a summary counts a row under: its arm, plus its lead when not the default (`ccx2@opus-high`) and
    `@ccx-home` when its lead ran in a ccx home (`ccx2@ccx-home`, `ccx2@opus-high@ccx-home`), so units with
    different leads, or leads told different things, are never pooled or paired as one arm."""
    return f"{r['arm']}{_arm_suffix(r)}"


def done_key(r: dict) -> tuple:
    """What makes a unit done: tag, round, task, arm, the lead (old rows: the default lead, so they still match) and,
    for a lead in a ccx home, that (a ccx2 unit done under flags does not stand for one in a ccx home). An auto unit
    keys on 'auto' and its effort, never on the model it picked: a rule changed between invocations under one tag
    must not re-run a done task into the same arm under the other pick."""
    lead = (LEAD_AUTO, lead_of(r)[1]) if is_auto(r) else lead_of(r)
    return (r.get("tag"), r.get("round"), r.get("task"), r.get("arm"), *lead) + \
        ((LEAD_AUTO,) if is_auto(r) else ()) + (("ccx-home",) if in_ccx_home(r) else ())


def unit_key(u: dict) -> str:
    """The unit's folder / stream name in the work dir (the old name for the default lead outside a ccx home)."""
    return f"{u['round']}-{u['task']}-{u['arm']}{_arm_suffix(u)}"


def unit_how(u: dict, task: dict) -> str:
    """lead_how for one unit. A polyglot exercise has no test files for a delegating lead's --check to name, so its
    sub-agent writes one of its own (tasks_polyglot.CHECK_EXERCISE), and the long instructions go by --brief-file."""
    how = lead_how(u["arm"], u["label"], lead_of(u))
    if is_exercise(task):
        how = how.replace(tasks_polyglot.CHECK_PLACEHOLDER, tasks_polyglot.CHECK_EXERCISE)
        if "--check" in how:
            how += " " + tasks_polyglot.BRIEF_FILE
    return how


def lead_unit(u: dict, a, work: Path, repo: Path, hub: Path, iso: PF.Unit | None = None, env: dict | None = None,
              job: PF.Job | None = None) -> dict:
    task = by_id(u["task"])
    env = {**(env or PF.base_env()), "CCX_HUB": str(hub), "CCX_NO_QUOTA_PROBE": "1",
           "BASH_DEFAULT_TIMEOUT_MS": "900000", "BASH_MAX_TIMEOUT_MS": "1200000"}
    is_ccx, is_builtin = u["arm"] in CCX_ARMS, u["arm"] in BUILTIN_ARMS
    env = task_env(task, env, ext_python(a))
    how = unit_how(u, task)
    spec = ext_spec(task)
    prompt = (LEAD_PROMPT_EXERCISE.format(name=spec["name"], brief=task["brief"], how=how) if is_exercise(task)
              else LEAD_PROMPT_EXT.format(name=spec["name"], note=ext_note(spec), brief=task["brief"], how=how)
              if spec else LEAD_PROMPT.format(brief=task["brief"], how=how))
    t0 = time.time()
    # ccx2 / builtin2 need the same lead flags as ccx / builtin (a session file; the Agent tool and worker); the
    # clean-room flags (no user settings, hooks, CLAUDE.md, auto-memory; deny rules) come from preflight
    model, effort = lead_of(u)
    argv = r3.lead_argv(lead_flags_arm(u["arm"]), a.lead_budget, model, effort, worker_agents(u["arm"])) \
        + (PF.lead_flags(iso) if iso else [])
    if u["arm"] in SKILL_ARMS:
        argv = skill_argv(argv)
    out, _err, rc, _left = PF.run(argv, input=prompt, cwd=repo, env=env, timeout=a.timeout, job=job)
    wall = round(time.time() - t0, 1)
    (work / f"{unit_key(u)}.stream.jsonl").write_text(out, encoding="utf-8")
    fin = r3.last_result(out)
    lm = r3.lead_metrics(out)
    cost = r2.hub_cost(hub)
    by_model = r3.model_split(fin.get("modelUsage") or {})
    lead_usd = float(fin.get("total_cost_usd") or 0)
    sub_use = sub_usage(hub) if is_ccx else None
    row = {"rc": rc, "wall_s": wall, "subtype": fin.get("subtype"), "lead_usd": round(lead_usd, 6),
           "by_model_usd": by_model, "ccx_usd": cost["usd"], "ccx_review_usd": cost["review_usd"],
           "ccx_agents": cost["agents"], "ccx_run_ids": cost["run_ids"], "usd": round(lead_usd + cost["usd"], 6), **lm}
    row["sub_usd"] = round(sum(v for m, v in by_model.items() if r3.WORKER_MODEL in m), 6) if is_builtin \
        else cost["usd"]
    row["lead_only_usd"] = round(row["usd"] - row["sub_usd"], 6)
    if sub_use is not None:
        row["sub_usage"] = sub_use
    ccx_runs = len([x for x in cost["run_ids"] if not str(x).startswith("review")])
    row["delegated"] = bool(lm["agent_calls"]) if is_builtin else bool(cost["run_ids"]) \
        if is_ccx else None
    row["rework"] = max(0, lm["agent_calls"] - 1) if is_builtin else \
        (lm["ccx_resumes"] + max(0, lm["ccx_runs"] - 1)) if is_ccx else 0
    row["ccx_ledger_rows"] = ccx_runs
    if is_ccx:
        row["context_attached"] = sum((hub / "ccx" / "runs" / str(rid) / "shared-context.md").exists()
                                      for rid in cost["run_ids"])
        if cost["run_ids"]:
            row["phases"] = phase_wall(hub, cost["run_ids"], wall)
    ls = TL.lead_stream(out)
    row["lead_usage"] = ls["usage"]               # per token class: what --dry-run prices another lead model with
    if u["arm"] in SKILL_ARMS:
        row["skills_used"] = ls["skills"]
        row["skill_used"] = "agent-delegate" in ls["skills"]
    row["timeline"] = TL.unit_timeline(hub, cost["run_ids"], out, wall, row.get("phases"),
                                       worker_usd=row["sub_usd"] if is_builtin else None)
    return row


def sub_usage(hub: Path) -> dict:
    """What ccx's sub-agents read and wrote in this unit, per token class, from the hub's ledger (read before the hub
    goes): `input` (uncached), `cached`, `output` of the work runs, `prompt` = input + cached (what the B3 rule
    compares: memories, skills and tool definitions are prompt), the same for ccx's reviews apart (`review_*`), and
    how many runs. `requests` / `review_requests`: the model requests of those runs' own conversations (helpers and
    Codex sub-sessions not counted, as ccx/reqstats.py records them), summed over the runs whose ledger row says
    (`requests_runs` / `review_requests_runs` of them; None when none does: ccx before it recorded them)."""
    from ccx import ledger as _ledger
    out = {"input": 0, "cached": 0, "output": 0, "runs": 0, "review_input": 0, "review_cached": 0,
           "review_output": 0, "reviews": 0}
    req = {"": [0, 0], "review_": [0, 0]}
    for r in _ledger.rows(r2.Paths(hub)):
        if r.get("type"):
            continue
        u = r.get("usage") or {}
        pre = "review_" if str(r.get("label") or "").startswith("review:") else ""
        for k in ("input", "cached", "output"):
            out[pre + k] += int(u.get(k, 0) or 0)
        out["reviews" if pre else "runs"] += 1
        n = r.get("requests")
        if isinstance(n, int) and not isinstance(n, bool) and n >= 0:
            req[pre][0] += n
            req[pre][1] += 1
    out["prompt"] = out["input"] + out["cached"]
    for pre, (n, k) in req.items():
        out[pre + "requests"] = n if k else None
        out[pre + "requests_runs"] = k
    return out


def sub_req_text(su: dict | None) -> str:
    """The sub-agents' requests for the run log: "8 (2/4 runs)" when not every run said."""
    su = su or {}
    if su.get("requests") is None:
        return "None"
    k, n = su.get("requests_runs") or 0, su.get("runs") or 0
    return str(su["requests"]) + (f" ({k}/{n} runs)" if k != n else "")


def namecheck_stats(rows: list[dict]) -> dict | None:
    """Per arm: the namecheck modes its unit hubs ran (`namecheck_mode`, rows before r6a have none: left out), how
    many builder runs the check saw, how many had hits and how many of those it failed (mode fail). None: no row
    says."""
    modes: dict[str, int] = {}
    runs = hit = failed = climbs = 0
    for r in rows:
        if r.get("namecheck_mode"):
            modes[r["namecheck_mode"]] = modes.get(r["namecheck_mode"], 0) + 1
        for x in r.get("ccx_namecheck") or []:
            runs += 1
            climbs += int(x.get("climbs") or 0)
            if x.get("hits"):
                hit += 1
                failed += x.get("mode") == "fail"
    if not modes and not runs:
        return None
    # runs_with_hits / runs_failed_by_it: the run's last attempt; climbs_by_it: earlier attempts it failed and ccx
    # climbed past (the extra escalation fail mode costs; compare with ccx_routes / rungs per arm)
    return {"modes": modes, "runs": runs, "runs_with_hits": hit, "runs_failed_by_it": failed,
            "climbs_by_it": climbs}


PHASES = ("sub_s", "check_s", "review_s", "fix_s", "overlap_s", "lead_wait_s", "lead_active_s")


def phase_wall(hub: Path, run_ids: list, wall_s: float | None = None) -> dict:
    """Where a unit's ccx time went, from its run records (run.json): the sub-agent's attempts (sub_s, n_attempts),
    ccx's acceptance checks (check_s), the reviews (review_s: the `review:<id>` runs), the fix rounds after a review
    (fix_s: a run with review_of, its attempts and its check) and, with the lead's wall, the lead waiting on ccx
    (lead_wait_s, an estimate: ccx runs block the lead, or it waits with show --wait) and the rest (lead_active_s).
    Checks count every run of ccx's check: the final one (record["check"]) and those of earlier rungs that failed
    and climbed (an attempt's check_seconds). ccx runs a run's review while its final check runs, so lead_wait_s
    counts that time once (overlap_s: the shorter of the two, per run with both) and is at most the wall. A review
    started alongside an earlier rung's check and stopped when that check failed (a `review:<id>` run that is not
    the linked one) overlaps those failed checks the same way. Records
    that cannot be read are counted in `missing`."""
    sub = check = review = fix = overlap = 0.0
    n_att = n_rev = n_fix = missing = 0
    ids, seen = list(dict.fromkeys(str(x) for x in run_ids)), set()
    recs: dict[str, dict] = {}
    while ids:
        rid = ids.pop(0)
        if rid in seen:
            continue
        seen.add(rid)
        rec = r2.record(hub, rid)
        if not rec:
            missing += 1
            continue
        recs[rid] = rec
        rv = (rec.get("review") or {}).get("run_id")
        if rv and str(rv) not in seen:          # a review not in the ledger list is still counted
            ids.append(str(rv))

    def secs(rec: dict) -> float:
        return sum(float(x.get("seconds") or 0) for x in rec.get("attempts") or [])

    def is_review(rec: dict) -> bool:
        return str(rec.get("label") or "").startswith("review:")

    by_parent: dict[str, list[tuple[str, dict]]] = {}
    for rid, rec in recs.items():
        if is_review(rec):
            by_parent.setdefault(str(rec["label"])[len("review:"):], []).append((rid, rec))

    for rid, rec in recs.items():
        if is_review(rec):
            review, n_rev = review + secs(rec), n_rev + 1
            continue
        final = (rec.get("check") or {}).get("seconds")
        early = sum(float(x.get("check_seconds") or 0) for x in rec.get("attempts") or [])
        c = float(final or 0) + early
        linked = str((rec.get("review") or {}).get("run_id"))
        rv = recs.get(linked)
        if final and rv and is_review(rv):      # the review ran alongside the final check
            overlap += min(float(final), secs(rv))
        # reviews stopped when an earlier rung's check failed ran alongside those checks
        stopped = sum(secs(x) for xid, x in by_parent.get(str(rid), []) if xid != linked)
        if early and stopped:
            overlap += min(early, stopped)
        if rec.get("review_of"):
            fix, n_fix = fix + secs(rec) + c, n_fix + 1
        else:
            sub, check, n_att = sub + secs(rec), check + c, n_att + len(rec.get("attempts") or [])
    out = {"sub_s": round(sub, 1), "check_s": round(check, 1), "review_s": round(review, 1), "fix_s": round(fix, 1),
           "overlap_s": round(overlap, 1), "n_attempts": n_att, "n_reviews": n_rev, "n_fix_rounds": n_fix,
           "missing": missing}
    if wall_s is not None:
        wait = min(float(wall_s), sub + check + review + fix - overlap)
        out.update(lead_wait_s=round(wait, 1), lead_active_s=round(float(wall_s) - wait, 1))
    return out


def direct_unit(u: dict, a, repo: Path, hub: Path, env: dict | None = None, job: PF.Job | None = None) -> dict:
    task = by_id(u["task"])
    # direct keeps its fixed --minutes 60; cheapest's script has nobody to size the task, so it gives no estimate
    # cheapest's script passes the repository's suite as its --check (suite_check); direct has none
    est = ["--check", suite_check(task)] if u["arm"] == "cheapest" else ["--minutes", "60"]
    argv = ["run", "--mode", "write", "--new", "--no-ab", "--force", "--label", u["label"], *est,
            *no_lead_flags(u["arm"]), task["brief"]]
    t0 = time.time()
    env = task_env(task, {**(env or PF.base_env()), "CCX_HUB": str(hub)}, ext_python(a))
    out, err, rc, _left = PF.run([sys.executable, str(ROOT / "ccx.py"), *argv], cwd=repo, env=env,
                                 timeout=a.timeout, job=job)
    res, err = r2.S._last_json(out), ("timeout" if rc == -9 else err[-400:])
    cost = r2.hub_cost(hub)
    rec = r2.record(hub, res.get("run_id"))
    row = {"rc": rc, "wall_s": round(time.time() - t0, 1), "usd": cost["usd"], "ccx_usd": cost["usd"],
           "ccx_review_usd": cost["review_usd"], "ccx_run_ids": cost["run_ids"], "model": res.get("model"),
           "status": res.get("status"), "kind": res.get("kind", rec.get("kind")), "ccx_ok": res.get("ok"),
           "verdicts": [v.get("verdict") for v in (rec.get("first_review"), rec.get("review")) if v],
           "stderr": err if rc else ""}
    if cost["run_ids"]:
        row["phases"] = phase_wall(hub, cost["run_ids"])          # no lead: nothing waits
    row["timeline"] = TL.unit_timeline(hub, cost["run_ids"], "", row["wall_s"])
    return row


# ------------------------------------------------------------------ tier arms: the hub setting and what each row keeps

def set_picked(hub: Path, tier: str, env: dict | None = None) -> str:
    """The person's choice the tier arm simulates: `ccx config set policy.picked <tier>` in the unit's hub (ccx's own
    command, so the setting is written exactly as the person's would be). Returns what the hub now picks."""
    r = subprocess.run([sys.executable, str(ROOT / "ccx.py"), "config", "set", "policy.picked", tier], cwd=ROOT,
                       env={**(env or r2.env_for(hub)), "CCX_HUB": str(hub)}, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=120)
    if r.returncode:
        raise RuntimeError(f"ccx config set policy.picked {tier} failed: {(r.stderr or r.stdout)[-300:]}")
    from ccx.config import load_config
    from ccx.commands.common import picked_tier
    got = picked_tier(load_config(r2.Paths(hub)))
    if got != tier:
        raise RuntimeError(f"the unit hub picks {got!r} after setting policy.picked {tier}")
    return got


def set_small(hub: Path) -> dict:
    """Opt-in only: write the unit overlay and assert ccx resolves both switches before launch."""
    from ccx.config import load_config
    f = r2.Paths(hub).user_tiers
    with f.open("a", encoding="utf-8", newline="") as stream:
        stream.write("\n[routing]\nsmall_self_run = true\nstrict_escalate = true\n")
    got = load_config(r2.Paths(hub)).get("routing") or {}
    want = {"small_self_run": True, "strict_escalate": True}
    if any(got.get(k) is not v for k, v in want.items()):
        raise RuntimeError("ccx2small routing switches were not applied")
    return want


def set_namecheck(hub: Path, mode: str) -> str:
    """A namecheck arm's unit hub: `[defaults] namecheck = "<mode>"` written into the hub's own tiers.toml (the
    hand-edited overrides file r2.make_hub writes, ccx's `[defaults] namecheck` setting), then read back the way ccx
    reads it (load_config + namecheck.mode). Raises unless the hub now runs with `mode`; returns it."""
    f = r2.Paths(hub).user_tiers
    text = f.read_text(encoding="utf-8") if f.exists() else ""
    line = f'namecheck = "{mode}"\n'
    text = re.sub(r"(?m)^namecheck[ \t]*=.*(?:\n|\Z)", "", text)     # an earlier setting (a TOML key only once)
    if re.search(r"(?m)^\[defaults\][ \t]*$", text):
        text = re.sub(r"(?m)^\[defaults\][ \t]*(?:\n|\Z)", lambda m: m.group(0).rstrip("\n") + "\n" + line, text,
                      count=1)
    else:
        text = text + ("" if not text or text.endswith("\n") else "\n") + "[defaults]\n" + line
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text, encoding="utf-8")
    got = hub_namecheck(hub)
    if got != mode:
        raise RuntimeError(f"the unit hub runs namecheck {got!r} after setting [defaults] namecheck = {mode!r}")
    return got


def hub_user_words(hub: Path, enable: bool = False) -> bool:
    """Set only the unit hub's opt-in, then assert the effective config before launch."""
    from ccx.config import load_config
    p = r2.Paths(hub)
    if enable:
        f = p.user_tiers
        text = f.read_text(encoding="utf-8") if f.exists() else ""
        text = re.sub(r"(?m)^user_words[ \t]*=.*(?:\n|\Z)", "", text)
        line = "user_words = true\n"
        if re.search(r"(?m)^\[delegate\][ \t]*$", text):
            text = re.sub(r"(?m)^\[delegate\][ \t]*(?:\n|\Z)",
                          lambda m: m.group(0).rstrip("\n") + "\n" + line, text, count=1)
        else:
            text += ("" if not text or text.endswith("\n") else "\n") + "[delegate]\n" + line
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")
    got = (load_config(p).get("delegate") or {}).get("user_words", False)
    if enable and got is not True:
        raise RuntimeError("unit hub did not enable delegate.user_words")
    return got


def daily_sources(a, frozen: bool = True) -> tuple[Path, Path]:
    """The person's own Codex home and ~/.agents a daily arm copies from (--daily-codex-source / --daily-agents-source;
    default ~/.codex and ~/.agents). Once `run` froze them (freeze_daily), every unit copies from that frozen
    snapshot instead (frozen=False: the person's own folders even then)."""
    snap = getattr(a, "daily_frozen", None) if frozen else None
    if snap:
        return Path(snap["codex"]), Path(snap["agents"])
    codex = getattr(a, "daily_codex_source", "") or str(Path.home() / ".codex")
    agents = getattr(a, "daily_agents_source", "") or str(Path.home() / ".agents")
    return Path(codex).expanduser(), Path(agents).expanduser()


DAILY_SNAPSHOT = "daily-snapshot"


def freeze_daily(a, dest: Path) -> dict:
    """Copy the person's daily setup ONCE per `run` invocation into dest (codex/: memories, AGENTS.md, skills and a
    config.toml holding only the settings a daily home takes from theirs, the kept ones and the memory settings;
    agents/: ~/.agents/skills), with daily_home's filters. Every daily unit of the invocation then copies from this
    snapshot (daily_sources), so a rewrite of the person's real memories in the middle of a run cannot give the two
    units of a pair different setups. Returns where it is and its sha256 (names and bytes); a.daily_frozen is set."""
    codex_src, agents_src = daily_sources(a, frozen=False)
    dest = Path(dest)
    r2._rmtree(dest)
    codex, agents = dest / "codex", dest / "agents"
    codex.mkdir(parents=True)
    agents.mkdir(parents=True)
    stats: dict = {}
    copied = [f"codex:{n}" for n in DH.DAILY_COPY if DH._copy(codex_src / n, codex / n, stats)]
    copied += [f"agents:{n}" for n in DH.AGENTS_COPY if DH._copy(agents_src / n, agents / n, stats)]
    # only what build() reads from the person's config.toml, written so it reads back the same (no sandbox override:
    # build() adds that per unit)
    (codex / "config.toml").write_text(DH.config_toml(PF.codex_kept_toml(codex_src), (),
                                                      DH.memory_settings(codex_src), platform="frozen"),
                                       encoding="utf-8")
    bad = DH.found_never(codex, allow=("config.toml",)) + [f"agents/{x}" for x in DH.found_never(agents)]
    if bad:
        raise RuntimeError(f"the frozen daily snapshot holds what must never be copied: {bad[:5]}")
    info = {"codex": str(codex), "agents": str(agents), "copied": copied, "sha256": DH.tree_sha256([codex, agents],
                                                                                                   skip=()),
            "frozen_at": round(time.time(), 1), "sources": [str(codex_src), str(agents_src)]}
    a.daily_frozen = info
    return info


def set_daily(iso: PF.Unit, hub: Path, env: dict, arm: str, a) -> tuple[dict, dict]:
    """A daily arm's unit: its own Codex home and HOME (daily_home.build, in the unit's x- folder), its environment
    (daily_home.unit_env) and its [subagent] overlay written into the unit hub's tiers.toml, read back the way ccx
    reads it. Raises unless the hub now runs with exactly the arm's switches. Returns (info, env)."""
    if not iso.codex_home:
        raise RuntimeError(f"arm {arm} needs --codex-home: its Codex login comes from the eval Codex home")
    codex_src, agents_src = daily_sources(a)
    info = DH.build(iso.x, iso.codex_home, codex_src, agents_src, kept=PF.codex_kept_toml(codex_src),
                    features_off=PF.CODEX_FEATURES_OFF)
    over = DH.overlay_toml(DAILY_ARMS[arm])
    if over:
        f = r2.Paths(hub).user_tiers
        text = f.read_text(encoding="utf-8") if f.exists() else ""
        if re.search(r"(?m)^\[subagent\][ \t]*$", text):
            raise RuntimeError("the unit hub's tiers.toml already has a [subagent] table")
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text + ("" if not text or text.endswith("\n") else "\n") + over, encoding="utf-8")
    from ccx.config import SUBAGENT_SWITCHES, load_config, subagent_switches
    got = subagent_switches(load_config(r2.Paths(hub)))
    want = {**SUBAGENT_SWITCHES, **DAILY_ARMS[arm]}
    if got != want:
        raise RuntimeError(f"the unit hub runs [subagent] {got} instead of {want}")
    info["switches"] = got
    snap = getattr(a, "daily_frozen", None)
    info["snapshot"] = ({"frozen": True, "sha256": snap["sha256"], "frozen_at": snap["frozen_at"]} if snap
                        else {"frozen": False})
    return info, DH.unit_env(env, info)


def daily_plan_lines(arms: list[str], a) -> list[str]:
    """What --dry-run says about the daily arms it would run (nothing is copied or written)."""
    daily = [x for x in arms if x in DAILY_ARMS]
    if not daily:
        return []
    codex_src, agents_src = daily_sources(a)
    out = [f"[dry] daily arms copy {', '.join(DH.DAILY_COPY)} from {codex_src} and "
           f"{', '.join(DH.AGENTS_COPY)} from {agents_src} into a per-unit home (never auth, credentials, "
           "config.toml, sessions or logs); the Codex login is the eval Codex home's; Claude sub-agents load "
           f"setting sources {DH.DAILY_CLAUDE_SOURCES}"]
    if DH.windows_sandbox():
        out.append(f"[dry] daily homes on Windows: [windows] sandbox = \"{DH.windows_sandbox()}\" (all daily arms; "
                   "a fresh home cannot use the elevated sandbox without UAC)")
    out += [f"[dry]   {x}: [subagent] {DAILY_ARMS[x] or '(none: the daily baseline)'}" for x in daily]
    if not getattr(a, "codex_home", ""):
        out.append("[dry] note: the daily arms need --codex-home (their login comes from it)")
    return out


def cmd_daily_check(a) -> int:
    """Build one daily home in a temporary folder from --codex-home and the person's sources, print what it holds
    (names only) and remove it: the self-test of the daily arms, with nothing started."""
    if not a.codex_home:
        print("daily-check needs --codex-home (the eval Codex home whose login the daily home copies)")
        return 2
    codex_src, agents_src = daily_sources(a)
    tmp = Path(tempfile.mkdtemp(prefix="ccx-daily-"))
    try:
        info = DH.build(tmp, Path(PF.codex_home_arg(a.codex_home)), codex_src, agents_src,
                        kept=PF.codex_kept_toml(codex_src), features_off=PF.CODEX_FEATURES_OFF)
        names = sorted(p.relative_to(tmp).as_posix() for p in tmp.rglob("*") if p.is_file())
        print(json.dumps({"copied": info["copied"], "files": info["files"], "auth": info["auth"],
                          "memory_settings": info["memory_settings"], "features_off": info["features_off"],
                          "windows_sandbox": info.get("windows_sandbox"),
                          "top": sorted({"/".join(n.split("/")[:2]) for n in names})}, indent=1))
        print("daily-check: ok (removed)")
        return 0
    except RuntimeError as e:
        print(f"daily-check: {e}")
        return 3
    finally:
        r2._rmtree(tmp)


def hub_namecheck(hub: Path) -> str:
    """The namecheck mode a ccx run in this hub gets without a --namecheck flag (ccx's own resolution)."""
    from ccx import namecheck
    from ccx.config import load_config
    return namecheck.mode(None, load_config(r2.Paths(hub)))


def ccx_namecheck(hub: Path, run_ids: list) -> list[dict]:
    """The namecheck each builder run of a unit actually ran with (reviews left out; its record's `namecheck`:
    mode and number of hits on the last attempt; a run without one, a read-only or `off` run, is left out).
    `climbs`: attempts whose namecheck hit failed them in fail mode with a rung left, so ccx climbed (the
    record's last `namecheck` does not show these: a clean next rung overwrites it). `final_fail`: the run ended
    on a namecheck failure. `attempts_hit`: attempts whose namecheck had hits (records before r6a: None)."""
    out = []
    for rid in run_ids or []:
        rec = r2.record(hub, rid)
        if not rec or str(rec.get("label") or "").startswith("review:"):
            continue
        nc = rec.get("namecheck")
        if isinstance(nc, dict):
            att = [a for a in rec.get("attempts") or [] if isinstance(a, dict)]
            per = [a["namecheck"] for a in att if isinstance(a.get("namecheck"), dict)]
            chk = rec.get("check") if isinstance(rec.get("check"), dict) else {}
            out.append({"run": rid, "mode": nc.get("mode"), "hits": len(nc.get("hits") or []),
                        "climbs": sum(a.get("kind") == "check_failed" and a.get("check_reason") == "namecheck"
                                      for a in att),
                        "final_fail": chk.get("reason") == "namecheck",
                        "attempts_hit": sum(bool(x.get("hits")) for x in per) if per else None})
    return out


def switches_applied(hub: Path, run_ids: list, want: dict | None = None) -> dict:
    """What the [subagent] switches did at run level in this unit, from each ccx run's run.json: its
    `subagent_switches` (what ccx resolved and handed to the sub-agent), its mode, the CLIs its attempts ran on and,
    for Codex attempts, the memory / web_search / image_generation flags those switches add (delegate.py and
    agents/codex.py: memories off on every Codex rung; lean tools on write runs only). ccx's run.json does not record
    the CLI's argv, so the flags are derived from the recorded switches, not read back (`argv_recorded` False).
    `want`: the switches the arm set; `match` says whether every run that recorded them ran with them."""
    from ccx.agents.codex import MEMORIES_OFF
    runs = []
    for rid in run_ids or []:
        rec = r2.record(hub, rid)
        if not rec:
            runs.append({"run": rid, "record": "missing"})
            continue
        sw = rec.get("subagent_switches") if isinstance(rec.get("subagent_switches"), dict) else None
        agents = sorted({str(a.get("agent")) for a in rec.get("attempts") or [] if isinstance(a, dict)})
        one = {"run": rid, "review": str(rec.get("label") or "").startswith("review:"), "mode": rec.get("mode"),
               "agents": agents, "provider": rec.get("provider"), "subagent_switches": sw}
        if sw is not None and "codex" in agents:
            lean = bool(sw.get("codex_lean_tools")) and rec.get("mode") != "read"
            one["codex_flags"] = {"memories_off": " ".join(MEMORIES_OFF) if sw.get("codex_memories") is False else None,
                                  "web_search_off": lean, "image_generation_off": lean, "goals_off": lean,
                                  "apps_plugins_off": lean and not rec.get("provider")}
        runs.append(one)
    seen = [r["subagent_switches"] for r in runs if r.get("subagent_switches") is not None]
    out = {"runs": runs, "argv_recorded": False,
           "note": "run.json records subagent_switches, not the CLI argv: codex_flags are derived from them"}
    if want is not None:
        from ccx.config import SUBAGENT_SWITCHES
        full = {**SUBAGENT_SWITCHES, **want}
        out["want"] = full
        out["match"] = (all(x == full for x in seen) if seen else None)
    return out


_TR = []


def task_routing():
    """skills/task-routing/scripts/task_routing.py of this checkout (size_band, merged_policy), loaded once."""
    if not _TR:
        import importlib.util
        f = ROOT / "skills" / "task-routing" / "scripts" / "task_routing.py"
        spec = importlib.util.spec_from_file_location("r5_task_routing", f)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _TR.append(mod)
    return _TR[0]


def shipped_policy() -> dict:
    """config/tiers.toml [policy] of this checkout (the shipped bands and tier rules)."""
    import tomllib
    with open(ROOT / "config" / "tiers.toml", "rb") as f:
        return tomllib.load(f).get("policy") or {}


_REF: dict[str, dict | None] = {}


def ref_size(task: dict) -> dict | None:
    """The reference change's size, counted as tasks_holdout counts it (non-test .py / .toml lines and files): the
    hold-out tasks carry it, an r5 task's is read from this checkout's history (None when the commit is not there,
    e.g. a shallow clone). `band`: the band those files give under the shipped [policy.bands] (files are the one
    signal a reference change has; the lines are kept for another cut)."""
    tid = task["id"]
    if tid not in _REF:
        if task.get("size") is not None and task.get("files") is not None:
            lines, files = int(task["size"]), int(task["files"])
        elif ext_spec(task):
            lines = files = None
        else:
            try:
                ch = ext_repo.ref_change(ROOT, task["commit"])
                lines, files = ch["size"], len(ch["files"])
            except Exception:  # noqa: BLE001 — no history here: unknown, not a failed unit
                lines = files = None
        if files is None:
            _REF[tid] = None
        else:
            band = task_routing().size_band("", None, files, shipped_policy())["band"]
            _REF[tid] = {"lines": lines, "files": files, "band": band}
    return _REF[tid]


BANDS = ("small", "medium", "large")


def band_minutes(policy: dict | None = None) -> dict:
    """Minutes standing for each size band under [policy.bands]: half the medium floor, the geometric middle of
    medium, twice the large floor (15 / 45 shipped: 7.5, 26, 90 minutes, b 2.9 / 4.7 / 6.5)."""
    bands = (policy if policy is not None else shipped_policy()).get("bands") or {}
    lo, hi = float(bands.get("medium_minutes", 15)), float(bands.get("large_minutes", 45))
    return {"small": lo / 2, "medium": (lo * hi) ** 0.5, "large": hi * 2}


def task_difficulty(task: dict) -> tuple[float | None, str]:
    """(b, where it came from) for --lead-model auto: a task's own `minutes` when it has one (an estimate made before
    the run, as a person would give ccx fresh --minutes), else the reference change's size band in minutes
    (band_minutes) — an oracle stand-in: the band comes from the answer's size, which a real estimate does not see,
    so auto's result is an upper bound on what the rule gives with real estimates. None when neither is known."""
    tr = task_routing()
    if task.get("minutes"):
        return round(tr.b_from_minutes(float(task["minutes"])), 2), "minutes"
    ref = ref_size(task)
    if not ref or ref.get("band") not in BANDS:
        return None, "unknown"
    return round(tr.b_from_minutes(band_minutes()[ref["band"]]), 2), f"ref band {ref['band']}"


def auto_lead(task: dict) -> dict:
    """The lead fields of one auto unit: lead_model by ccx's rule (leadmodel.pick, forced on, this checkout's
    config), lead_pick auto, lead_b, lead_band (easy / hard; unknown difficulty: the strong lead, never cheaper)."""
    import tomllib
    from ccx import leadmodel
    with open(ROOT / "config" / "tiers.toml", "rb") as f:
        cfg = tomllib.load(f)
    b, src = task_difficulty(task)
    ch = leadmodel.pick(cfg, "claude", b, task.get("risk"), force=True)
    strong = str((cfg.get("lead") or {}).get("claude") or "opus")
    return {"lead_model": ch["model"] if ch else strong, "lead_pick": LEAD_AUTO, "lead_b": b,
            "lead_band": ch["band"] if ch else "unknown", "lead_b_from": src}


def misband(planned: str | None, ref: str | None) -> str | None:
    """Planned band vs the reference change's: same | under (planned smaller) | over; None when either is unknown."""
    if planned not in BANDS or ref not in BANDS:
        return None
    d = BANDS.index(planned) - BANDS.index(ref)
    return "same" if d == 0 else "under" if d < 0 else "over"


def hub_rows(hub: Path) -> list[dict]:
    return r2.ledger.rows(r2.Paths(hub))


def ccx_check_reason(hub: Path, run_ids: list) -> str | None:
    """"namecheck" when the unit's last sub-agent run's check is namecheck's stand-in (mode fail: the acceptance
    command did not run), else None. Such a False is not "the --check caught it": check_passed_on_fail leaves
    it out."""
    last = None
    for rid in run_ids or []:
        rec = r2.record(hub, rid)
        if str(rec.get("label") or "").startswith("review:"):
            continue
        if isinstance(rec.get("check"), dict) and "passed" in rec["check"]:
            last = rec["check"].get("reason") or None
    return last


def ccx_check_passed(hub: Path, run_ids: list) -> bool | None:
    """Whether ccx's --check passed on the unit's last sub-agent run (reviews left out); None: no run had a check.
    Read on a failed unit, it says whether the check let a wrong result through."""
    last = None
    for rid in run_ids or []:
        rec = r2.record(hub, rid)
        if str(rec.get("label") or "").startswith("review:"):
            continue
        if isinstance(rec.get("check"), dict) and "passed" in rec["check"]:
            last = bool(rec["check"]["passed"])
    return last


def files_band(files) -> str | None:
    """The band a file count alone gives under the shipped [policy.bands] (None without a count)."""
    if not files:
        return None
    return task_routing().size_band("", None, int(files), shipped_policy())["band"]


def ccx_routes(hub: Path, run_ids: list) -> list[dict]:
    """How each builder run of a unit picked its model (reviews left out): the route's source (task-routing from a
    rubric / --minutes difficulty, keywords, tier, explicit), its difficulty b and the rung it ran. save's run
    carries the lead's --minutes / --files and ccx2's does not, so this tells their model picks apart."""
    out = []
    for rid in run_ids or []:
        rec = r2.record(hub, rid)
        if not rec or str(rec.get("label") or "").startswith("review:"):
            continue
        rt = rec.get("route") or {}
        att = (rec.get("attempts") or [{}])[0]
        out.append({"source": rt.get("source"), "b": rt.get("b"), "rung": rt.get("rung") or att.get("rung"),
                    "model": att.get("model"), "effort": att.get("effort")})
    return out


def tier_fields(arm: str, hub: Path, task: dict) -> dict:
    """What a tier arm's row keeps: the tier, what was planned (the first `ccx propose` row in the unit hub's ledger:
    band, mode, authorized; cheapest: the tier's rule, direct, the script's run unsized; fast: self,
    never proposed), the reference size, the mode that ran (the ledger runs' actual_mode, none = self) and the
    misbanding, only for a band the lead proposed: `misband` compares like with like, the band of the lead's --files
    against the band of the reference change's files (a reference change has no minutes or brief words of its own);
    `misband_overall` keeps the planned band (the largest of the brief's words, --minutes and --files) against the
    same files band, which leans over by construction (any --minutes >= 15 makes it at least medium)."""
    rows = hub_rows(hub)
    props = [r for r in rows if r.get("type") == "proposal"]
    runs = [r for r in rows if not r.get("type") and not str(r.get("label") or "").startswith("review:")]
    if props:
        p = props[0]
        plan = {"source": "propose", "tier": p.get("policy_tier"), "band": p.get("band"),
                "mode": p.get("planned_mode"), "authorized": bool(p.get("preauthorized")),
                "explicit": bool(p.get("tier_explicit")), "estimate_minutes": p.get("estimate_minutes"),
                "estimate_files": p.get("estimate_files"), "n_proposals": len(props)}
    elif arm == "cheapest":
        # the script gives no --minutes / --files, so ccx sizes nothing (a run without a difficulty gets no tier
        # plan: no policy_tier on its row). The plan is the eval script's, from the tier's rule (direct for every
        # band), not one ccx made: source eval-script, ccx_planned false
        r = runs[0] if runs else {}
        plan = {"source": "eval-script", "tier": "cheapest", "band": r.get("band"), "mode": "direct", "sized": False,
                "ccx_planned": False, "run_policy_tier": r.get("policy_tier")}
    elif arm == "fast":
        plan = {"source": "tier", "tier": "fast", "band": None, "mode": "self"}
    else:
        plan = {"source": "none", "tier": arm, "band": None, "mode": None, "n_proposals": 0}
    modes = sorted({str(r.get("actual_mode") or "ccx2") for r in runs})
    ref = ref_size(task)
    proposed = plan["source"] == "propose"
    ref_band = (ref or {}).get("band")
    out = {"tier": arm, "tier_plan": plan, "ref_size": ref, "actual_mode": "+".join(modes) if modes else "self",
           "misband": misband(files_band(plan.get("estimate_files")), ref_band) if proposed else None,
           "misband_overall": misband(plan.get("band"), ref_band) if proposed else None}
    # cheapest has no lead to follow its plan or not (the script always runs it): None, not a trivial yes
    out["followed_plan"] = None if not plan.get("mode") or arm == "cheapest" else plan["mode"] == out["actual_mode"]
    if arm == "cheapest":
        out["may_be_wrong"] = True
    return out


def bookkeeping(row: dict, arm: str, hub: Path, task: dict) -> None:
    """The tier fields, ccx's --check result and the runs' routes, added to a unit's row after its agents ran. An
    error here is kept in the row (`bookkeeping_error`) and the unit is still scored: its lead and sub-agent are
    already paid for, so a failed read of metadata must not throw the hidden-test result away."""
    try:
        if arm == "ccx2small":
            decisions = [r for r in hub_rows(hub) if r.get("type") == "small_self_run"]
            row["small_self_run"] = {"applied": bool(decisions), "decisions": decisions}
        if arm in TIER_ARMS:
            row.update(tier_fields(arm, hub, task))
        if row.get("ccx_run_ids"):
            row["ccx_check_passed"] = ccx_check_passed(hub, row["ccx_run_ids"])
            if ccx_check_reason(hub, row["ccx_run_ids"]):
                row["ccx_check_reason"] = ccx_check_reason(hub, row["ccx_run_ids"])
            row["ccx_routes"] = ccx_routes(hub, row["ccx_run_ids"])
            row["ccx_namecheck"] = ccx_namecheck(hub, row["ccx_run_ids"])
    except Exception as e:  # noqa: BLE001 — metadata only; the score below still runs
        row["bookkeeping_error"] = f"{type(e).__name__}: {e}"[:400]


def must_telemetry(row: dict, hub: Path, repo: Path) -> None:
    """Record-only (backlog build item 11): every [must] of the unit's reviews with its categories (in-diff /
    out-of-diff / exception-only / test-only, harness_audit.must_categories), read before the hub is removed. Changes
    nothing in ccx or in how the unit is scored; an error is kept in the row."""
    try:
        if row.get("ccx_run_ids"):
            row["must_categories"] = HA.unit_must_categories(hub, repo, row["ccx_run_ids"])
    except Exception as e:  # noqa: BLE001 — telemetry only
        row["must_categories_error"] = f"{type(e).__name__}: {e}"[:300]


def unit_of(u: dict, a, work: Path) -> PF.Unit:
    key = unit_key(u)
    return PF.Unit(key=key, work=work, repo=work / key, hub=work / f"h-{key}", label=u["label"],
                   claude=a.claude_isolation, ccx_home=a.claude_isolation == "ccx-home" and u["arm"] in CCX_ARMS,
                   codex_home=Path(PF.codex_home_arg(a.codex_home)) if a.codex_home else None,
                   dsh=a.dsh_home, agents=tuple(r3.WORKER),
                   codex_workspace_tmp=getattr(a, "codex_workspace_tmp", False), **ext_guard(by_id(u["task"]), a, work))


def unit_models(u: dict, row: dict) -> dict:
    """The models this unit was meant to use, and the ones its streams and ledger show it did use."""
    model, effort = lead_of(u)
    out = {"lead": model, "lead_effort": effort, "builtin_worker": r3.WORKER_MODEL}      # direct: replaced below
    if u["arm"] == "builtin2r":
        out["worker_rules"] = "KEEP_TESTS+WIRING"
    if not has_lead(u["arm"]):                    # direct, cheapest: the ccx run flags
        out = {"direct": " ".join(no_lead_flags(u["arm"]))}
    if u["arm"] in TIER_ARMS:                     # the hub's policy.picked (the person's choice the arm simulates)
        out["tier_picked"] = u["arm"]
    if u["arm"] in NAMECHECK_ARMS:                # the hub's [defaults] namecheck
        out["namecheck"] = NAMECHECK_ARMS[u["arm"]]
    if u["arm"] in USER_WORDS_ARMS:
        out["user_words"] = True
    if u["arm"] in DAILY_ARMS:                    # the daily home and the hub's [subagent] overlay
        out["daily"] = {"subagent": DAILY_ARMS[u["arm"]], "claude_setting_sources": DH.DAILY_CLAUDE_SOURCES,
                        "sha256": (row.get("daily") or {}).get("sha256")}    # the snapshot of the copied setup
        sandbox = (row.get("daily") or {}).get("windows_sandbox")    # only what build() actually wrote
        if sandbox:                               # Windows: every daily home runs Codex's unelevated sandbox
            out["daily"]["windows_sandbox"] = sandbox
    seen = ((row.get("audit") or {}).get("init") or {}).get("model")
    if seen:
        out["lead_seen"] = seen
    if row.get("by_model_usd"):
        out["billed"] = sorted(row["by_model_usd"])
    return out


def run_unit(u: dict, a, work: Path) -> dict:
    """One unit in its clean room. Whatever happens inside, its leftovers are cleaned and recorded and the row
    carries the fingerprint (an error is a field of the row, not a lost row)."""
    task = by_id(u["task"])
    iso = unit_of(u, a, work)
    repo, hub = iso.repo, iso.hub
    rep = getattr(a, "preflight", None)
    stream = work / f"{iso.key}.stream.jsonl"
    stream.unlink(missing_ok=True)              # an earlier, unfinished try of this unit must not be audited
    row: dict = {**u}
    env = None
    sc, diff, scored = None, None, False
    before, job = PF.snapshot(), PF.Job()
    try:
        r2._rmtree(hub)
        # a task of another repository: its material was read before the first unit (prepare_external), from a
        # clone outside the work dir that is gone now; a unit never clones into the work dir itself
        xkw = {"work": work, "source": getattr(a, "ext_cache", None)} if ext_spec(task) else {}
        if xkw and _ext_key(task) not in _EXT:
            raise RuntimeError(f"{task['id']}: the other repository was not prepared before the run")
        make_repo(task, repo, **xkw)
        if ext_spec(task):
            row["ext"] = {"repo": task["repo"], "commit": task["commit"], "date": _EXT[_ext_key(task)]["date"],
                          **(getattr(a, "ext_info", None) or {"python": ext_python(a)})}
        hinfo = r3.make_hub(hub)
        hinfo["memory_empty"] = PF.hub_memory_empty(hub)
        row["hub"] = hinfo
        if u["arm"] == "ccx2small":
            hinfo["small_routing"] = set_small(hub)
        env = PF.prepare(iso)
        if u["arm"] in TIER_ARMS:                 # the person's choice the arm simulates, in the unit's own hub
            hinfo["picked"] = set_picked(hub, u["arm"], env)
        # the namecheck mode the unit's ccx runs get (ccx2nc: fail, set and asserted here; any other arm: what the
        # hub says, warn as shipped), in every row so before / after compare on the field, not on the arm name
        hinfo["namecheck"] = (set_namecheck(hub, NAMECHECK_ARMS[u["arm"]]) if u["arm"] in NAMECHECK_ARMS
                              else hub_namecheck(hub))
        row["namecheck_mode"] = hinfo["namecheck"]
        hinfo["user_words"] = hub_user_words(hub, u["arm"] in USER_WORDS_ARMS)
        row["user_words_mode"] = hinfo["user_words"]
        if u["arm"] in DAILY_ARMS:                # its own Codex home and HOME, and its [subagent] overlay
            row["daily"], env = set_daily(iso, hub, env, u["arm"], a)
        row.update(direct_unit(u, a, repo, hub, env, job) if not has_lead(u["arm"]) else
                   lead_unit(u, a, work, repo, hub, iso, env, job))
        row.update(changed(repo))
        try:
            diff = final_diff(repo)
        except Exception:  # noqa: BLE001 — an artifact only
            diff = None
        bookkeeping(row, u["arm"], hub, task)
        must_telemetry(row, hub, repo)
        try:                                      # what the [subagent] switches did, per ccx run (telemetry only)
            row["switches_applied"] = switches_applied(hub, row.get("ccx_run_ids") or [], DAILY_ARMS.get(u["arm"]))
        except Exception as e:  # noqa: BLE001
            row["switches_applied"] = {"error": f"{type(e).__name__}: {e}"[:300]}
        sc = score(repo, task, work, job, **({"python": ext_python(a), "source": xkw["source"]} if xkw else {}))
        scored = True
        row.update({**u, "ok": sc["ok"], "pytest": sc["pytest"], "hub": hinfo})
        if not sc["ok"]:
            row["hidden_failed"] = sc.get("failed") or []
        for rid in row.get("ccx_run_ids") or []:
            ccx_verify(rid, bool(sc["ok"]), f"eval-r2 hidden acceptance: {sc['pytest']}", hub=hub, env=env)
        row["archived_sessions"] = archive_hub(hub, env=env)
    except Exception as e:  # noqa: BLE001 — recorded in the row; the clean-up below still runs
        row.update({"ok": False, "error": f"{type(e).__name__}: {e}"[:400]})
        row.setdefault("usd", 0.0)
        row.setdefault("wall_s", 0)
    finally:
        try:
            row["audit"] = PF.audit(iso, stream.read_text(encoding="utf-8") if stream.exists() else "",
                                    daily=u["arm"] in DAILY_ARMS)
        except Exception as e:  # noqa: BLE001
            row["audit"] = {"clean": False, "problems": [f"audit failed: {type(e).__name__}: {e}"[:200]],
                            "session_ids": []}
        if row.get("daily") and iso is not None and iso.codex_home:
            # before the x- folder goes: a login the unit refreshed goes back to the eval home (daily_home.sync_login)
            try:
                row["daily"]["login"] = DH.sync_login(row["daily"], iso.codex_home)
            except OSError as e:
                row["daily"]["login"] = {"auth": "conflict", "note": f"not written back: {type(e).__name__}"}
            if row["daily"]["login"]["auth"] == "conflict":
                row["audit"]["clean"] = False
                row["audit"].setdefault("problems", []).append("daily login: " + row["daily"]["login"].get(
                    "note", "conflict"))
        art = getattr(a, "artifacts_dir", None)
        # before the clean-up: what the unit left and how it failed; an exercise keeps it even when right (one
        # small file: a solution that games the scoring process is then visible afterwards)
        if art and (not row.get("ok") or is_exercise(task)):
            try:
                if diff is None and not scored:    # it broke before scoring: the repo has no hidden tests in it yet
                    diff = final_diff(repo)
                keep_artifacts(Path(art) / f"{u.get('tag') or 'untagged'}-{iso.key}", row, sc, diff)
                if getattr(a, "artifacts_run", None) and "dir" in (row.get("artifacts") or {}):
                    row["artifacts"]["run"] = a.artifacts_run
            except Exception as e:  # noqa: BLE001
                row["artifacts"] = {"error": f"{type(e).__name__}: {e}"[:200]}
        fresh = u.get("taskset", "r5") != "r5"     # hold-out: nothing of a finished unit stays in the work dir
        # Keep the sub-agent streams before after_unit removes their hub, also on successful/aborted units.
        # A normal invocation supplies an invocation-specific artifacts_dir; library callers retain a fallback.
        dest = (Path(art) / f"{u.get('tag') or 'untagged'}-{iso.key}" if art else
                OUT / "streams" / str(u.get("tag") or "untagged") / iso.key)
        try:
            kept = ES.keep(dest / "streams", iso, stream, env)
            if kept:
                if getattr(a, "artifacts_run", None):
                    kept["run"] = a.artifacts_run
                row["streams"] = kept
            if fresh:
                stream.unlink(missing_ok=True)
        except Exception as e:  # noqa: BLE001 — evidence failure must not skip unit cleanup
            row["streams_error"] = type(e).__name__  # diagnostic only; preserve existing audit/scoring semantics
        row["leftovers"] = PF.after_unit(iso, before, job, row["audit"].get("session_ids") or [], keep_repo=not fresh)
        if "ext" in row and getattr(a, "ext_venv", None):
            # the Python that scores every unit is shared: something installed into it changes later units
            try:
                now = venv_state(ext_python(a))
            except Exception as e:  # noqa: BLE001
                now = f"unreadable: {type(e).__name__}"
            if now != a.ext_venv:
                row["ext"]["venv_changed"] = True
    if rep:
        row["fingerprint"] = PF.fingerprint(rep, iso, env, unit_models(u, row))
    return row


ARM_ORDERS = ("shuffle", "balanced")


def williams(n: int) -> list[list[int]]:
    """A Williams design over n arms (a balanced Latin square): first row 0, 1, n-1, 2, n-2, ..., each later row +1
    mod n; for an odd n the reversed rows are added too (2n rows). Over all its rows every arm takes every place
    equally often and every arm runs before every other arm in exactly half of the rows, so no switch's comparison
    with the baseline lines up with run order."""
    if n <= 0:
        return [[]]
    row0, lo, hi = [0], 1, n - 1
    while len(row0) < n:
        row0.append(lo)
        lo += 1
        if len(row0) < n:
            row0.append(hi)
            hi -= 1
    rows = [[(x + i) % n for x in row0] for i in range(n)]
    return rows + [r[::-1] for r in rows] if n % 2 else rows


def schedule(rounds: int, seed: int, tasks: list[str], arms: list[str], order: str = "shuffle") -> list[dict]:
    """Units in run order: per round the tasks shuffled (seeded), per task its arms one after another. `shuffle` (the
    default, every earlier run's schedule): the arms shuffled per task. `balanced`: the rows of a Williams design
    (williams) over one seeded arm order, taken in turn by the task's place in `tasks` and the round, so over every
    full cycle of rows each arm runs in each place equally often and before every other arm in half of the units
    (order_balance counts it); when the task count is a multiple of the rows, each round shifts by one so a task's
    rounds still differ. Rows say `arm_order` and `arm_pos`."""
    if order not in ARM_ORDERS:
        raise ValueError(f"unknown arm order {order!r} (known: {', '.join(ARM_ORDERS)})")
    base = list(arms)
    random.Random(f"{seed}:r5:arms").shuffle(base)
    rows = williams(len(base))
    shift = 1 if tasks and len(tasks) % len(rows) == 0 else 0
    out = []
    for rd in range(1, rounds + 1):
        rnd = random.Random(f"{seed}:r5:{rd}")
        ts = list(tasks)
        rnd.shuffle(ts)
        for t in ts:
            if order == "balanced":
                row = rows[((rd - 1) * (len(tasks) + shift) + tasks.index(t)) % len(rows)]
                arm_list = [base[j] for j in row]
                out += [{"exp": "r5", "round": rd, "task": t, "arm": arm, "arm_order": order, "arm_pos": i}
                        for i, arm in enumerate(arm_list)]
                continue
            arm_list = list(arms)
            rnd.shuffle(arm_list)
            out += [{"exp": "r5", "round": rd, "task": t, "arm": arm} for arm in arm_list]
    return out


def order_balance(units: list[dict], base: str) -> dict:
    """For every other arm: [units of a task and round where `base` ran before it, task-rounds with both]. A paired
    comparison against base is confounded with run order (drift, rate limits, provider cache) when this is far
    from half."""
    by: dict = {}
    for i, u in enumerate(units):
        by.setdefault((u["round"], u["task"]), {})[u["arm"]] = i
    out: dict = {}
    for g in by.values():
        if base not in g:
            continue
        for arm, i in g.items():
            if arm != base:
                c = out.setdefault(arm, [0, 0])
                c[0] += g[base] < i
                c[1] += 1
    return dict(sorted(out.items()))


def spent(f: Path, tag: str | None = None) -> float:
    """What the rows of a results file cost (only those of `tag` when given)."""
    return round(sum(r.get("usd") or 0 for r in read_jsonl(f) if tag is None or r.get("tag") == tag), 4)


def budget_spent(f: Path, tag: str, extra: float = 0.0) -> float:
    """What --budget is checked against: this tag's rows (earlier invocations of the same tag included, so going
    on with a tag does not get a fresh budget) plus --extra-spent; other tags in the same file do not count."""
    return round(spent(f, tag) + (extra or 0.0), 4)


def spend_line(f: Path, tag: str, extra: float, run_usd: float) -> str:
    """run (this invocation), tag (what the budget counts, with --extra-spent) and file totals."""
    return (f"run=${run_usd:.3f} tag=${budget_spent(f, tag, extra):.3f} file=${spent(f):.3f}")


def _py(python: str, code: str) -> str:
    """The output of a little code of ours run by `python` in isolated mode (nothing of the repositories)."""
    r = subprocess.run([python, "-I", "-c", code], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=120)
    if r.returncode:
        raise RuntimeError(f"{python} failed: {(r.stderr or '').strip()[-200:]}")
    return r.stdout.strip()


def missing_modules(python: str, names: list[str]) -> list[str]:
    """Which of these modules `python` cannot find (found, not imported: nothing of them is run)."""
    out = _py(python, "import importlib.util as u, json; print(json.dumps([n for n in %r if u.find_spec(n) is None]))"
              % (list(names),))
    return json.loads(out)


def python_info(python: str) -> dict:
    """The version of `python` and of its pytest (or None)."""
    out = _py(python, "import sys, json\ntry:\n    from importlib.metadata import version; p = version('pytest')\n"
                      "except Exception:\n    p = None\nprint(json.dumps(['%d.%d.%d' % sys.version_info[:3], p]))")
    v, p = json.loads(out)
    return {"python_version": v, "pytest": p}


def venv_state(python: str) -> str:
    """A fingerprint of what is installed for `python` (the names in its site-packages folders)."""
    out = _py(python, "import site, os, json\nds = site.getsitepackages() + [site.getusersitepackages()]\n"
                      "print(json.dumps(sorted(d + '|' + n for d in ds if os.path.isdir(d) for n in os.listdir(d))))")
    return hashlib.sha256(out.encode("utf-8")).hexdigest()


def _version(s: str | None) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", s or "")[:3])


def prepare_external(todo: list[dict], a, work: Path) -> list[str]:
    """Before the first unit (and before the paid canary): read every other repository the units need out of a
    clone made in a temporary folder outside the work dir, which is then removed (the fix is never on disk next to
    a unit), check each pinned sha, and check the Python for their tests: 3.11 or newer (ccx runs on it too, it is
    first on PATH), has the modules the tests need and a new enough pytest, does not have the library itself
    installed (its released code has the fix), and is not kept next to the --ext-cache copies (an agent sees its
    folder on PATH). Records that Python's versions and a fingerprint of what is installed in it on `a` (ext_info,
    ext_venv). Returns the problems (none: ready)."""
    tasks = {u["task"]: by_id(u["task"]) for u in todo}
    ext = [t for t in tasks.values() if ext_spec(t)]
    if not ext:
        return []
    probs = []
    tmp = Path(tempfile.mkdtemp(prefix="ccx-ext-"))
    try:
        for t in ext:
            try:
                ext_material(t, work, getattr(a, "ext_cache", None), cache=tmp)
            except Exception as e:  # noqa: BLE001 — reported, the run does not start
                probs.append(f"{t['id']}: {type(e).__name__}: {e}"[:300])
    finally:
        ext_repo._rmtree(tmp)
    py = ext_python(a)
    try:
        info = python_info(py)
    except Exception as e:  # noqa: BLE001
        return probs + [f"--ext-python {py} does not run: {e}"[:300]]
    a.ext_info = {"python": py, **info}
    if _version(info["python_version"]) < (3, 11):
        probs.append(f"{py} is Python {info['python_version']}: ccx runs on it in external units, it needs 3.11+")
    specs = {t["repo"]: ext_spec(t) for t in ext}
    needs = sorted({n for s in specs.values() for n in s.get("needs") or ()})
    gone = missing_modules(py, needs) if needs else []
    if gone:
        probs.append(f"{py} cannot import {', '.join(gone)} (the other repositories' tests need "
                     f"them): install them there or pass --ext-python")
    low = sorted({s["pytest_min"] for s in specs.values() if s.get("pytest_min")}, key=_version)
    if low and info["pytest"] and _version(info["pytest"]) < _version(low[-1]):
        probs.append(f"{py} has pytest {info['pytest']}; the other repositories' tests need {low[-1]} or newer")
    mods = sorted(s["module"] for s in specs.values() if s.get("module"))
    there = sorted(set(mods) - set(missing_modules(py, mods))) if mods else []
    if there:
        probs.append(f"{py} has {', '.join(there)} installed: its released code has the fix; use a Python without it")
    src = getattr(a, "ext_cache", "") or ""
    if src and any(is_exercise(t) for t in ext) and PF._inside(Path(work).resolve(),
                                                               Path(src).expanduser().resolve().parent):
        probs.append(f"the work dir {work} is in the folder that holds the --ext-cache copies ({Path(src).parent}): "
                     "a copy of the exercises (with their example solutions) would sit next to the units; keep "
                     "the copies elsewhere, or leave --ext-cache out (the run clones into a temporary folder)")
    if src and PF._inside(Path(py).parent, Path(src).expanduser().resolve().parent):
        probs.append(f"{py} is in the folder that holds the --ext-cache copies ({Path(src).parent}): an agent finds "
                     f"that folder on PATH; keep the Python somewhere else")
    try:
        a.ext_venv = venv_state(py)
    except Exception as e:  # noqa: BLE001
        probs.append(f"cannot list what {py} has installed: {e}"[:300])
    return probs


# ------------------------------------------------------------------ the dry-run planner's cost estimate

# measured $/unit with the default (sonnet medium) lead, mean over the r5 tags' rows (self r5; builtin r5, r5f;
# builtin2 r5d; ccx2 r5c-r5h; direct r5, r5c, r5e; ccx r5), and the lead's share of it (lead_only_usd / usd, median)
UNIT_USD = {"self": 0.20, "builtin": 0.17, "builtin2": 0.10, "builtin2r": 0.10, "ccx": 0.21, "ccx2": 0.12,
            "direct": 0.05}
LEAD_SHARE = {"self": 1.0, "builtin": 0.75, "builtin2": 0.73, "builtin2r": 0.73, "ccx": 0.72, "ccx2": 0.64,
              "direct": 0.0}
OPUS_LEAD = 1.7            # the old flat assumption (an Opus lead's part x1.7); unit_estimate's default ratio only
# List prices, $ per million tokens, of the lead models Claude Code's aliases name (opus = Claude Opus 5.5, sonnet =
# Claude Sonnet 5.5, the models round 5's streams show), from the Claude API model table cached 2026-10-06:
# input / output; cache reads; cache writes are 1.25x input (5-minute cache). Opus 5.5 costs twice Sonnet 5.5 per
# input, output and cache-write token but the same per cache read, so the ratio of a lead's cost depends on its mix.
PRICES = {"opus": {"input": 4.0, "output": 20.0, "cache_read": 0.20, "cache_write": 5.0},
          "sonnet": {"input": 2.0, "output": 10.0, "cache_read": 0.20, "cache_write": 2.5}}
TOKEN_CLASSES = {"input": "input_tokens", "output": "output_tokens", "cache_read": "cache_read_input_tokens",
                 "cache_write": "cache_creation_input_tokens"}
# The share of a Sonnet lead's $ per token class when the results file has no measured leads (one ccx2 row of r5h
# solved for its cache writes: lead_usd $0.0767 = 381 output, ~71k cache reads, ~23k cache writes): an assumption
LEAD_MIX_ASSUMED = {"input": 0.0, "output": 0.05, "cache_read": 0.19, "cache_write": 0.76}
PROPOSE_USD = 0.01         # one `ccx propose` call by the lead (design estimate)
# the measured arm a tier mode is estimated from (direct: the direct arm's mean, which paid a review and a fixed
# gpt-6-luna low that cheapest's run does not, so cheapest's estimate is rough, not a measurement of it)
TIER_MODE_ARM = {"self": "self", "ccx2": "ccx2", "direct": "direct"}


def planned_mode(arm: str, task: dict) -> str:
    """The mode a tier arm is expected to run a task in, for the estimate: the tier's rule for the band of the
    reference change's files (fallback: uncertain) and the brief's state-machine words, as tier_plan applies them."""
    tr = task_routing()
    pol = tr.merged_policy(shipped_policy())
    rules = pol.get(arm) or tr.DEFAULT_POLICY[arm]
    ref = ref_size(task)
    hard = tr.size_band(task.get("brief") or "", None, 0, shipped_policy())["hard"]
    if hard and "hard" in rules:
        return rules["hard"]
    if not ref:
        return rules.get("uncertain") or rules.get("large", "self")
    return rules.get(ref["band"], "self")


def model_family(model: str) -> str | None:
    """opus / sonnet / haiku from an alias or a full model id; None for anything else."""
    m = str(model or "").lower()
    return next((x for x in ("opus", "sonnet", "haiku") if x in m), None)


def mix_of(usage: dict, prices: dict) -> dict | None:
    """A lead's $ per token class (`usage`: its per-class token counts, TOKEN_CLASSES) as shares of its total."""
    usd = {k: int(usage.get(v) or 0) * prices[k] / 1e6 for k, v in TOKEN_CLASSES.items()}
    total = sum(usd.values())
    return {k: v / total for k, v in usd.items()} if total else None


def lead_mix(rows: list[dict]) -> tuple[dict, str]:
    """The token mix of the default (Sonnet) lead's $: the mean of its rows' mixes in this results file (rows with
    `lead_usage`, which r5 records from the lead's stream), else LEAD_MIX_ASSUMED. Returns (mix, where it is from)."""
    mixes = [m for r in rows if r.get("lead_usage") and has_lead(r.get("arm") or "")
             and model_family(lead_of(r)[0]) == "sonnet" for m in [mix_of(r["lead_usage"], PRICES["sonnet"])] if m]
    if not mixes:
        return dict(LEAD_MIX_ASSUMED), "assumed (no measured lead token mix in this results file)"
    return {k: round(sum(m[k] for m in mixes) / len(mixes), 4) for k in TOKEN_CLASSES}, \
        f"measured from {len(mixes)} sonnet-lead rows"


def lead_price_ratio(model: str, mix: dict | None = None, base: str = "sonnet") -> float | None:
    """What a lead of `model` costs per unit of work relative to the measured Sonnet lead, at list prices: each token
    class's price ratio weighted by the Sonnet lead's $ mix (the same tokens, priced at the other model). 1.0 for
    the base model; None for a model without a price (estimated at the base's then, and marked)."""
    fam = model_family(model)
    if fam == base:
        return 1.0
    if fam not in PRICES:
        return None
    mix = mix or LEAD_MIX_ASSUMED
    return round(sum(mix[k] * PRICES[fam][k] / PRICES[base][k] for k in TOKEN_CLASSES), 4)


def unit_split(u: dict, ratio: float | None = OPUS_LEAD) -> dict:
    """The estimate of one unit split into the lead's part and ccx's part, and the mode it stands for: the measured
    per-unit cost of its arm (a tier arm: of the mode it is expected to run in, plus one ccx propose for balanced /
    save, a lead's call) split by its measured lead share; the lead's part times `ratio` when the lead is not the
    measured Sonnet (its model's price ratio, lead_price_ratio; None: no price, kept at Sonnet's and marked `$?`).
    Arms without a measurement: ccx2's, marked `?`."""
    arm = u["arm"]
    if arm in TIER_ARMS:
        mode = "self" if arm == "fast" else planned_mode(arm, by_id(u["task"]))
        base = TIER_MODE_ARM.get(mode, "ccx2")
    else:
        mode, base = arm, arm if arm in UNIT_USD else "ccx2"
    usd, share = UNIT_USD[base], LEAD_SHARE[base]
    lead, ccx = usd * share, usd * (1 - share)
    other = has_lead(arm) and model_family(lead_of(u)[0]) != "sonnet"
    k = (ratio if ratio is not None else 1.0) if other else 1.0
    if arm in TIER_LEAD_ARMS:
        lead += PROPOSE_USD
    lead *= k
    tag = mode if arm in UNIT_USD or arm in TIER_ARMS else f"{mode}?"
    if other and ratio is None:
        tag += " $?"
    return {"lead": round(lead, 4), "ccx": round(ccx, 4), "usd": round(lead + ccx, 4), "mode": tag}


def unit_estimate(u: dict, ratio: float | None = OPUS_LEAD) -> tuple[float, str]:
    """(estimated $, the mode the estimate stands for) of one unit (unit_split's total)."""
    sp = unit_split(u, ratio)
    return sp["usd"], sp["mode"]


def plan_lines(todo: list[dict], budget: float, spent_usd: float, ratios: dict | None = None,
               mix_note: str = "") -> list[str]:
    """The dry-run planner: per arm units, $/unit and $ (the lead's and ccx's part), the total, and whether it fits
    what is left of the budget. `ratios`: lead model -> lead_price_ratio (default: the old flat OPUS_LEAD)."""
    by: dict[str, list] = {}
    for u in todo:
        r = (ratios or {}).get(lead_of(u)[0], OPUS_LEAD) if ratios is not None else OPUS_LEAD
        by.setdefault(arm_of(u), []).append(unit_split(u, r))
    out, total = [], 0.0
    for arm in arm_order(by):
        xs = by[arm]
        s, lead, ccx = (sum(x[k] for x in xs) for k in ("usd", "lead", "ccx"))
        total += s
        modes: dict[str, int] = {}
        for x in xs:
            modes[x["mode"]] = modes.get(x["mode"], 0) + 1
        out.append(f"[estimate] {arm:22} {len(xs):3} units  ~${s / len(xs):.3f}/unit  ~${s:.2f} (lead ~${lead:.2f}, "
                   f"ccx ~${ccx:.2f})  modes " + " ".join(f"{m}={n}" for m, n in sorted(modes.items())))
    left = round(budget - spent_usd, 4)
    out.append(f"[estimate] total ~${total:.2f} for {len(todo)} units; budget ${budget} with ${spent_usd:.2f} of this "
               f"tag spent leaves ${left:.2f}: " + ("fits" if total <= left else f"short by ~${total - left:.2f}"))
    if ratios:
        out.append("[estimate] lead prices: " + ", ".join(
            f"{m} x{r} of sonnet" if r is not None else f"{m}: no price (kept at sonnet's)" for m, r in ratios.items())
            + (f"; token mix {mix_note}" if mix_note else ""))
    out.append("[estimate] from measured r5 means with a sonnet lead, split by the measured lead share; another lead "
               "model's part repriced at its list prices (PRICES); a ? mode has no measurement and uses ccx2's; tier "
               "arms by the mode the shipped tier plans for each task's reference size, so misbanding moves the real "
               "cost")
    return out


def pin_check(rows: list[dict], tag: str, head: str, pin: str = "") -> tuple[str, list[str]]:
    """The one commit a tag (round) runs on: the commit of its rows already written (their fingerprint), else
    --pin-commit, else this checkout's HEAD. Problems: HEAD is not --pin-commit, the tag's rows were made at another
    commit than HEAD, or at more than one. A round that changes code half-way (say a PR merged into the eval checkout
    between invocations) would pool two versions as one arm. Returns (pinned commit, 12 chars; problems)."""
    head12 = (head or "")[:12]
    seen = sorted({str((r.get("fingerprint") or {}).get("commit") or "")[:12] for r in rows
                   if r.get("tag") == tag and (r.get("fingerprint") or {}).get("commit")})
    probs = []
    pin12 = (pin or "")[:12]
    if pin and not (head or "").startswith(pin):
        probs.append(f"this checkout is at {head12}, not the pinned commit {pin}")
    if len(seen) > 1:
        probs.append(f"tag {tag} already has rows from {len(seen)} commits: {', '.join(seen)}")
    if seen and head12 not in seen:
        probs.append(f"tag {tag} was run at {seen[0]}; this checkout is at {head12}")
    return (seen[0] if seen else pin12 or head12), probs


def arm_tokens(tokens: list[str], lead_model: str = "") -> list[str]:
    """--arms checked: each an arm (ARMS, OPT_IN_ARMS) or `<arm>@auto`, that arm with its lead model picked per task
    (--lead-model auto for its units only), so `ccx2,ccx2@auto` schedules and interleaves both in one invocation.
    Returns the arms themselves, each once (what preflight and the codex / skill checks see)."""
    known = (*ARMS, *OPT_IN_ARMS)
    bad, out = [], []
    for x in tokens:
        arm, at, pick = x.partition("@")
        if arm not in known or (at and pick != LEAD_AUTO):
            bad.append(x)
            continue
        if at and not has_lead(arm):
            raise SystemExit(f"{x}: arm {arm} has no lead to pick a model for")
        if at and lead_model == LEAD_AUTO:
            raise SystemExit(f"{x}: with --lead-model auto every lead arm is already auto; name the arm as {arm}")
        if arm not in out:
            out.append(arm)
    if bad:
        raise SystemExit(f"unknown arm(s): {', '.join(bad)} (known: {', '.join(known)}, or <arm>@{LEAD_AUTO})")
    dup = sorted({x for x in tokens if tokens.count(x) > 1})
    if dup:
        raise SystemExit(f"arm(s) named twice: {', '.join(dup)}")
    return out


def cmd_run(a) -> int:
    out = Path(a.out) if a.out else results_file(a.taskset)
    ids = TASKSETS[a.taskset].IDS
    tasks = a.tasks.split(",") if a.tasks else ids
    bad_t = [x for x in tasks if x not in ids]
    if bad_t:
        raise SystemExit(f"unknown task(s) in task set {a.taskset}: {', '.join(bad_t)} (known: {', '.join(ids)})")
    work = Path(a.workdir or (Path(tempfile.gettempdir()) / a.tag))
    tokens = a.arms.split(",") if a.arms else list(DEFAULT_ARMS.get(a.taskset, ARMS))
    arms = arm_tokens(tokens, a.lead_model or "")      # the arms themselves (an `<arm>@auto` token: its arm)
    skill = [x for x in arms if x in SKILL_ARMS]
    if skill and a.claude_isolation != "ccx-home" and not a.dry_run:
        raise SystemExit(f"arm {', '.join(skill)} needs --claude-isolation ccx-home: its lead must load the "
                         "agent-delegate skill from a Claude home that has ccx's install and nothing else (that "
                         "also needs CLAUDE_CODE_OAUTH_TOKEN, which you export yourself)")
    daily = [x for x in arms if x in DAILY_ARMS]
    if daily and a.jobs > 1 and not a.dry_run:
        # each daily unit runs on a copy of the eval home's login; a refresh rotates the token, and a copy taken by a
        # unit running at the same time would then hold a spent one (daily_home.sync_login)
        raise SystemExit(f"arm {', '.join(daily)} needs --jobs 1: its units share the eval Codex home's login")
    done = {done_key(r) for r in read_jsonl(out)}
    lead = {"lead_model": a.lead_model or DEFAULT_LEAD[0], "lead_effort": a.lead_effort or DEFAULT_LEAD[1]}
    auto = lead["lead_model"] == LEAD_AUTO
    todo = []
    for u in schedule(a.rounds, a.seed, tasks, tokens, getattr(a, "arm_order", "shuffle")):   # tokens: `x` and
        # `x@auto` interleave as two arms
        arm, _, pick = u["arm"].partition("@")
        u = {**u, "arm": arm, "tag": a.tag, "seed": a.seed, "taskset": a.taskset,
             **(lead if has_lead(arm) else {})}
        if (auto or pick == LEAD_AUTO) and has_lead(arm):
            u.update({"lead_model": LEAD_AUTO, **auto_lead(by_id(u["task"]))})
        if a.claude_isolation == "ccx-home" and u["arm"] in CCX_ARMS:
            u["ccx_home"] = True                  # its own arm (`@ccx-home`), key, folder and label
        u["label"] = f"eval-r5:{a.tag}:{u['round']}:{u['task']}:{u['arm']}{_arm_suffix(u)}"
        if done_key(u) not in done:
            todo.append(u)
    print(f"work dir: {work}  results: {out}  units: {len(todo)}  lead: {lead['lead_model']} "
          f"{lead['lead_effort']}", flush=True)
    if a.dry_run:
        mix, note = lead_mix(read_jsonl(out))
        ratios = {m: lead_price_ratio(m, mix) for m in sorted({lead_of(u)[0] for u in todo if has_lead(u["arm"])})}
        for u in todo:
            sp = unit_split(u, ratios.get(lead_of(u)[0], 1.0))
            picked = (f"; lead {u['lead_model']} ({u['lead_band']}, b {u['lead_b']} from {u['lead_b_from']})"
                      if is_auto(u) else "")
            print(f"[dry] {u['label']}  ~${sp['usd']:.3f} ({sp['mode']}; lead ~${sp['lead']:.3f}, "
                  f"ccx ~${sp['ccx']:.3f}{picked})")
        if any(is_auto(u) for u in todo):
            n: dict[str, int] = {}
            for u in todo:
                if is_auto(u):
                    n[u["lead_model"]] = n.get(u["lead_model"], 0) + 1
            print("[dry] lead auto picks: " + (", ".join(f"{m} x{k}" for m, k in sorted(n.items())) or "none"))
        for line in plan_lines(todo, a.budget, budget_spent(out, a.tag, a.extra_spent), ratios, note):
            print(line)
        if skill and a.claude_isolation != "ccx-home":
            print(f"[dry] note: {', '.join(skill)} needs --claude-isolation ccx-home to run")
        ob = order_balance(todo, B3_BASE)
        if ob:
            print("[dry] run order vs " + B3_BASE + " (base first / pairs): "
                  + ", ".join(f"{k} {v[0]}/{v[1]}" for k, v in ob.items()))
        for line in daily_plan_lines(arms, a):
            print(line)
        pinned, probs = pin_check(read_jsonl(out), a.tag, PF.commit_state()["commit"], a.pin_commit)
        for p in probs:
            print(f"[dry] commit: {p}")
        return 0
    pinned, pin_probs = pin_check(read_jsonl(out), a.tag, PF.commit_state()["commit"], a.pin_commit)
    for p in pin_probs:
        print(f"[commit] {p}", flush=True)
    if pin_probs and not a.force_unclean:
        print("not starting: one tag runs on one commit (finish it there, start a new --tag, or --force-unclean, "
              "which is recorded)", flush=True)
        return 3
    # the other repositories first: a bad --ext-python or copy must not cost the paid canary
    probs = prepare_external(todo, a, work)
    for p in probs:
        print(f"[external] {p}", flush=True)
    if probs:
        print("other repositories not ready: not starting", flush=True)
        return 3
    waited = None
    if getattr(a, "wait_quiet", 0):
        t0 = time.monotonic()
        quiet = wait_quiet(a.wait_quiet)           # still busy after it: the preflight below says so and stops
        waited = {"minutes": a.wait_quiet, "waited_s": round(time.monotonic() - t0), "quiet": quiet}
    rep = PF.run_checks(PF.options_from(a, arms, work, canary_on=not a.no_canary, start=True,
                                        tasks_file=Path(TASKSETS[a.taskset].__file__)))
    if waited:
        rep["wait_quiet"] = waited                 # in preflight.json: this run waited for a quiet machine
    for p in rep["problems"]:
        print(f"[preflight] {p}", flush=True)
    for w in rep.get("warnings") or []:          # not a problem, but the person must see it
        print(f"[preflight] *** {w} ***", flush=True)
    if not rep["ok"] and not a.force_unclean:
        print("preflight failed: not starting (fix the above, or --force-unclean to run anyway; it is recorded)",
              flush=True)
        return 3
    rep["lead"] = {"model": lead["lead_model"], "effort": lead["lead_effort"]}     # in every row's fingerprint
    per_arm = [x for x in tokens if "@" in x]
    if per_arm:                                    # `<arm>@auto` tokens: those units' lead was picked per task
        rep["lead"]["auto_arms"] = per_arm
    rep["pinned_commit"] = pinned
    if pin_probs:                                  # forced past a commit change: recorded, and no row is clean
        rep["pin_problems"] = pin_probs
        rep["result"] = "forced"
    work.mkdir(parents=True, exist_ok=True)
    (work / "preflight.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[preflight] {rep['result']}: commit {rep['commit'][:12]} cli {rep['cli']} codex {rep['codex']['mode']} "
          f"claude {rep['claude_isolation']} jobs {a.jobs} canary {rep['canary']}"
          + (f" codex canary {rep['codex_canary']}" if rep.get("codex_canary") else "")
          + (f" codex windows sandbox {rep['codex']['windows_sandbox']}" if rep["codex"].get("windows_sandbox") else ""),
          flush=True)
    a.preflight = rep
    # a unit that was not right keeps its evidence here, in a folder of this invocation's own (an aborted run's
    # folders stay apart; row["artifacts"]["run"] names it)
    a.artifacts_run, a.artifacts_dir = run_artifacts_dir(out)
    if daily:                                      # one snapshot of the person's setup for the whole invocation
        try:
            snap = freeze_daily(a, work / DAILY_SNAPSHOT)
        except (OSError, RuntimeError) as e:
            r2._rmtree(work / DAILY_SNAPSHOT)      # a half-made copy of the person's setup does not stay behind
            print(f"[daily] could not freeze the daily setup: {type(e).__name__}: {e}"[:400], flush=True)
            return 3
        rep["daily_snapshot"] = {k: snap[k] for k in ("sha256", "frozen_at", "copied")}
        (work / "preflight.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"[daily] froze the daily setup once for this run: sha256 {snap['sha256'][:12]} "
              f"({', '.join(snap['copied']) or 'nothing'})", flush=True)
    need_codex = any(x in PF.CODEX_ARMS for x in arms)
    ours = [PF._norm(work), PF._norm(f"eval-r5:{a.tag}:")]
    watch = PF.Watch(ours).start()
    lock, stop = threading.Lock(), threading.Event()
    run_usd = [0.0]                       # this invocation's own spend
    unit_runs: set = set()                # every ccx run id of this invocation's units (postflight attribution)

    def one(u):
        with lock:
            total = budget_spent(out, a.tag, a.extra_spent)
            if stop.is_set() or total >= a.budget:
                if not stop.is_set():
                    print(f"budget ${a.budget} reached (tag {a.tag}: ${total:.3f}): stopping", flush=True)
                stop.set()
                return
        try:
            row = run_unit(u, a, work)
        except Exception as e:  # noqa: BLE001 — one broken unit is recorded, the batch goes on
            row = {**u, "ok": False, "error": f"{type(e).__name__}: {e}"[:400], "usd": 0.0, "wall_s": 0}
        row["ts"] = time.time()
        if "fingerprint" not in row:
            row["fingerprint"] = PF.fingerprint(rep, None, None)
        between = PF.between_units(rep, need_codex, ours, watch.take())
        if between:
            row["between_units"] = between
        after = PF.codex_home_after(rep, need_codex)     # the eval Codex home after this unit
        if after is not None:
            row["codex_home_after"] = after
        row["env_clean"] = PF.env_clean(row, rep)
        why = list(between)
        if (row.get("ext") or {}).get("venv_changed"):
            row["env_clean"] = False
            why.append(f"something was installed into {ext_python(a)} during the unit (it scores every unit)")
        if (row.get("leftovers") or {}).get("unkilled"):
            why.append(f"processes that could not be killed: {row['leftovers']['unkilled']}")
        if why and not a.force_unclean:
            # --wait-quiet: when the only reason is other work on the machine, wait it out before the next unit (this
            # unit stays not env_clean; it is not run again under this tag) instead of stopping the run
            if (getattr(a, "wait_quiet", 0) and all(w.startswith("busy") for w in why)
                    and wait_quiet(a.wait_quiet, busy=lambda: _busy_now(ours))):
                print(f"[wait-quiet] {u['task']} {u['arm']} round {u['round']} ran while the machine was busy (not "
                      "env_clean); going on", flush=True)
            else:
                print(f"stopping: {'; '.join(why)[:400]}", flush=True)
                stop.set()
        with lock:
            append_jsonl(out, row)
            run_usd[0] += row.get("usd") or 0
            unit_runs.update(str(x) for x in row.get("ccx_run_ids") or [])
            print(f"r{u['round']} {u['task']:18} {u['arm']:8} ok={row.get('ok')} ${row.get('usd', 0):.4f} "
                  f"(lead ${row.get('lead_only_usd', 0) or 0:.4f}) req={row.get('lead_requests')} "
                  f"sub_req={sub_req_text(row.get('sub_usage'))} "
                  f"lead_tok={row.get('lead_tokens')} {row.get('wall_s')}s deleg={row.get('delegated')} "
                  f"files={row.get('files_changed')} clean={row['env_clean']} "
                  f"{spend_line(out, a.tag, a.extra_spent, run_usd[0])}", flush=True)

    # units of one task run one after another (arms in their shuffled order); --jobs tasks at a time
    groups: dict[tuple, list[dict]] = {}
    for u in todo:
        groups.setdefault((u["round"], u["task"]), []).append(u)
    try:
        with ThreadPoolExecutor(max_workers=a.jobs) as ex:
            list(ex.map(lambda us: [one(u) for u in us], groups.values()))
    finally:
        watch.close()
        if getattr(a, "daily_frozen", None):       # the person's setup does not stay in the work dir
            r2._rmtree(work / DAILY_SNAPSHOT)
    print(f"spent: {spend_line(out, a.tag, a.extra_spent, run_usd[0])} (budget ${a.budget} counts tag)", flush=True)
    # the person's own state, by size and count only: the hub ledger must not have grown, no Claude session folder
    # named after this work dir may be left in the real ~/.claude
    rep["real_state_after"] = post = PF.real_state(PF.real_paths(), work)
    rep["postflight"] = "same" if post == rep["real_state"] else "changed"
    (work / "preflight.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    if post.get("hub_ledger_bytes") != rep["real_state"].get("hub_ledger_bytes"):
        # which rows: a real session of the person's running at the same time, or one of this run's units
        att = ledger_attribution(PF.real_paths()["hub"] / "ccx" / "ledger.jsonl",
                                 int(rep["real_state"].get("hub_ledger_bytes") or 0), unit_runs, a.tag)
        rep["postflight_ledger"] = att
        (work / "preflight.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"[postflight] the real hub ledger gained {att.get('n', 0)} rows: {att.get('unit_runs', 0)} with a run "
              f"id of this run's units, {att.get('eval_labels', 0)} with this tag's label", flush=True)
        for r in att.get("rows") or []:
            print(f"[postflight]   type={r['type']} run_id={r['run_id']} ts={r['ts']} "
                  f"unit_run={'yes' if r['unit_run'] else 'no'}", flush=True)
    if post != rep["real_state"]:
        print(f"[postflight] the person's own state changed: {rep['real_state']} -> {post}", flush=True)
        return 4
    return 2 if stop.is_set() else 0


def ledger_attribution(led: Path, start: int, run_ids: set, tag: str = "", limit: int = 200) -> dict:
    """The rows the person's real hub ledger gained during a run (from byte `start`, its size before), each by type,
    run_id and ts only, and whether its run_id is one of this run's units' ccx_run_ids (`unit_run`: an eval leak) or
    its label one of this tag's (`eval_label`). Neither: most likely a real session of the person's running at the
    same time. The ledger only grows; a smaller file is read from its start and says so."""
    try:
        data = Path(led).read_bytes()
    except OSError as e:
        return {"rows": [], "error": f"{type(e).__name__}"}
    out: dict = {}
    if len(data) < start:
        out["note"] = "the ledger is smaller than before the run: read from its start"
        start = 0
    rows = []
    for line in data[start:].decode("utf-8", errors="replace").splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if not isinstance(r, dict):
            continue
        rid = r.get("run_id")
        rows.append({"type": r.get("type") or "run", "run_id": rid, "ts": r.get("ts"),
                     "unit_run": rid in run_ids,
                     "eval_label": bool(tag) and str(r.get("label") or "").startswith(f"eval-r5:{tag}:")})
    out.update({"rows": rows[:limit], "n": len(rows), "unit_runs": sum(r["unit_run"] for r in rows),
                "eval_labels": sum(r["eval_label"] for r in rows)})
    if len(rows) > limit:
        out["truncated"] = True
    return out


def wall_stats(rs: list[dict]) -> dict:
    """Right, spend and wall of some rows: median (as wall_med elsewhere: the upper middle), mean and p75 (nearest
    rank). The median alone hid the slow tail that the per-task routing analysis needed."""
    w = sorted(r.get("wall_s") or 0 for r in rs)
    ok = sum(bool(r.get("ok")) for r in rs)
    usd = sum(r.get("usd") or 0 for r in rs)
    return {"n": len(rs), "ok": ok, "usd": round(usd, 4), "cps": round(usd / ok, 4) if ok else None,
            "wall_med": w[len(w) // 2] if w else None, "wall_mean": round(sum(w) / len(w), 1) if w else None,
            "wall_p75": w[-(-3 * len(w) // 4) - 1] if w else None}


def round_key(rd) -> tuple:
    """Rounds in numeric order (2 before 10), anything else after them by its text, a missing one last."""
    return (rd is None, not isinstance(rd, int), rd if isinstance(rd, int) else 0, str(rd))


def ok_rate(ps: list[tuple[dict, dict]]) -> float | None:
    """The share of right rows (pairs of a row with itself, for task_boot)."""
    return round(sum(bool(x.get("ok")) for x, _ in ps) / len(ps), 4) if ps else None


def by_tag(rows: list[dict]) -> dict:
    """Per tag, per arm: wall_stats of its rows and of each round on its own, so different rounds (and the rounds
    of one tag) are never pooled without the split showing."""
    out: dict = {}
    for tag in sorted({str(r.get("tag")) for r in rows}):
        tr = [r for r in rows if str(r.get("tag")) == tag]
        for arm in arm_order(arm_of(r) for r in tr):
            ar = [r for r in tr if arm_of(r) == arm]
            rounds = {str(rd): wall_stats([r for r in ar if r.get("round") == rd])
                      for rd in sorted({r.get("round") for r in ar}, key=round_key)}
            out.setdefault(tag, {})[arm] = {**wall_stats(ar), "rounds": rounds}
    return out


def med_p75(xs: list[float]) -> dict:
    """Median (the upper middle, as wall_stats) and p75 (nearest rank) of some numbers."""
    w = sorted(xs)
    return {"med": w[len(w) // 2], "p75": w[-(-3 * len(w) // 4) - 1], "n": len(w)} if w else \
        {"med": None, "p75": None, "n": 0}


def arm_order(names) -> list[str]:
    """Arms in a stable order: the default ones, the opt-in ones, then any other (another lead: `ccx@opus-high`)."""
    known = [*ARMS, *OPT_IN_ARMS]
    base = lambda x: x.split("@", 1)[0]  # noqa: E731
    return sorted(set(names), key=lambda x: (known.index(base(x)) if base(x) in known else len(known), x))


def pair_units(rows: list[dict], A: str, B: str) -> list[tuple[dict, dict]]:
    """(A, B) rows of the same unit: tag, round, task (and rep, when rows have one); arms as arm_of names them."""
    by: dict = {}
    for r in rows:
        if "error" not in r:
            by.setdefault((str(r.get("tag")), r.get("round"), r.get("task"), r.get("rep")), {})[arm_of(r)] = r
    return [(d[A], d[B]) for _, d in sorted(by.items(), key=lambda kv: tuple(str(x) for x in kv[0]))
            if A in d and B in d]


def task_boot(ps: list[tuple[dict, dict]], stat, n: int = 4000, seed: int = 7,
              info: dict | None = None) -> tuple[float, float] | None:
    """Bootstrap 95% CI of stat(pairs), resampling tasks (the independent unit; a task's rounds go together).
    Resamples where the stat is undefined (None) are left out; `info`, when given, gets how many (dropped, of n)."""
    by: dict = {}
    for p in ps:
        by.setdefault(p[0]["task"], []).append(p)
    ts = sorted(by)
    if info is not None:
        info.update(n=0, dropped=0)
    if len(ts) < 2:
        return None
    rnd = random.Random(seed)
    vals = []
    for _ in range(n):
        v = stat([p for t in (rnd.choice(ts) for _ in ts) for p in by[t]])
        if v is not None:
            vals.append(v)
    if info is not None:
        info.update(n=n, dropped=n - len(vals))
    vals.sort()
    return (round(vals[int(0.025 * len(vals))], 4), round(vals[int(0.975 * len(vals)) - 1], 4)) if vals else None


def _med(xs) -> float | None:
    """The median as every wall_med of the summary takes it: the upper middle."""
    w = sorted(xs)
    return w[len(w) // 2] if w else None


def cps_diff(ps: list[tuple[dict, dict]]) -> float | None:
    """Cost per success of B minus that of A on these pairs (None when either has no success)."""
    a, b = r3.cps([x for x, _ in ps]), r3.cps([y for _, y in ps])
    return None if a is None or b is None else round(b - a, 5)


def wall_med_diff(ps: list[tuple[dict, dict]]) -> float | None:
    """Median wall (the upper middle, as wall_med) of B minus that of A on these pairs."""
    if not ps:
        return None
    return round(_med([y.get("wall_s") or 0 for _, y in ps]) - _med([x.get("wall_s") or 0 for x, _ in ps]), 1)


def task_sign(ps: list[tuple[dict, dict]]) -> tuple[int, int]:
    """Per task (the independent unit), which arm was right more often over its rounds: (tasks where A was, tasks
    where B was); ties are left out. Its exact sign test does not take a task's rounds as independent pairs."""
    by: dict = {}
    for x, y in ps:
        d = by.setdefault(x["task"], [0, 0])
        d[0] += bool(x.get("ok"))
        d[1] += bool(y.get("ok"))
    return sum(a > b for a, b in by.values()), sum(b > a for a, b in by.values())


def compare_pair(ps: list[tuple[dict, dict]], A: str, B: str) -> dict:
    """One arm pair on its shared units: right counts, McNemar exact p on the discordant units, the exact sign test
    over tasks (task_sign_p: the one to read when a task has several rounds, which McNemar counts as independent
    pairs), and B - A of cost per success and of the wall median with task-level bootstrap 95% CIs (resamples where
    an arm has no success are left out of the cost one, and counted)."""
    b = sum(bool(x.get("ok")) and not y.get("ok") for x, y in ps)
    c = sum(bool(y.get("ok")) and not x.get("ok") for x, y in ps)
    tb, tc = task_sign(ps)
    n_tasks = len({x["task"] for x, _ in ps})
    ci_info: dict = {}
    out = {"arms": [A, B], "units": len(ps), "tasks": n_tasks,
           "ok": {A: sum(bool(x.get("ok")) for x, _ in ps), B: sum(bool(y.get("ok")) for _, y in ps)},
           "discordant": {f"only_{A}": b, f"only_{B}": c}, "mcnemar_p": S.mcnemar_p(b, c),
           "task_sign": {f"more_{A}": tb, f"more_{B}": tc}, "task_sign_p": S.mcnemar_p(tb, tc),
           "diff_is": f"{B} - {A}",
           "cps": {A: r3.cps([x for x, _ in ps]), B: r3.cps([y for _, y in ps])},
           "cps_diff": cps_diff(ps), "cps_diff_ci": task_boot(ps, cps_diff, info=ci_info),
           "cps_diff_ci_dropped": ci_info.get("dropped", 0),
           "wall_med_diff": wall_med_diff(ps), "wall_med_diff_ci": task_boot(ps, wall_med_diff)}
    if len(ps) > n_tasks:
        out["mcnemar_note"] = (f"{len(ps)} units from {n_tasks} tasks: McNemar takes a task's rounds as independent "
                               "pairs (anti-conservative); task_sign_p does not")
    if out["cps_diff"] is None:
        none = [arm for arm, v in out["cps"].items() if v is None]
        out["cps_diff_note"] = f"no cost per success: {', '.join(none)} has no success on these units"
    elif ci_info.get("dropped"):
        out["cps_diff_note"] = (f"{ci_info['dropped']} of {ci_info['n']} resamples had an arm without a success and "
                                "were left out: the CI is conditional on both arms succeeding")
    return out


def paired_all(rows: list[dict], every: list[dict] | None = None) -> dict:
    """compare_pair for every two arms that share units, with Holm-adjusted McNemar and task sign p over those
    pairs. `every`: all rows before the clean ones were picked; each pair then says the pairs it lost to rows that
    are not env_clean, per side (lost_pairs), and notes it when that loss is one-sided."""
    arms = arm_order(arm_of(r) for r in rows if "error" not in r)
    out = {}
    for i, A in enumerate(arms):
        for B in arms[i + 1:]:
            ps = pair_units(rows, A, B)
            if ps:
                out[f"{A} vs {B}"] = compare_pair(ps, A, B)
                if every is not None:
                    lp = lost_pairs(every, A, B)
                    out[f"{A} vs {B}"]["lost_pairs"] = lp
                    if lp.get("note"):
                        out[f"{A} vs {B}"]["lost_pairs_note"] = lp["note"]
    for key in ("mcnemar_p", "task_sign_p"):
        for k, (_p, adj) in S.holm({k: v[key] for k, v in out.items()}).items():
            out[k][f"{key}_holm"] = adj
    return out


def clean_rows(rows: list[dict]) -> tuple[list[dict], dict]:
    """The rows a summary counts: env_clean is True (preflight.env_clean: a clean audit, no leftovers, a quiet machine,
    a passed preflight). Returns (those rows, how many were left out: `unclean` (env_clean False) and `env_unknown`
    (rows from before the clean room, without the field))."""
    keep = [r for r in rows if r.get("env_clean") is True]
    return keep, {"unclean": sum(r.get("env_clean") is False for r in rows),
                  "env_unknown": sum("env_clean" not in r or r.get("env_clean") is None for r in rows)}


def _excluded(r: dict) -> str | None:
    """Why clean_rows leaves a row out (unclean / env_unknown), or None when it counts."""
    if r.get("env_clean") is True:
        return None
    return "unclean" if r.get("env_clean") is False else "env_unknown"


def excluded_by_arm(rows: list[dict]) -> dict:
    """Per arm (arm_of), the rows clean_rows leaves out: {arm: {unclean, env_unknown, of}} for arms that lost any
    (`of`: the arm's rows before), so a one-sided loss shows next to the arm it changes."""
    out: dict = {}
    for r in rows:
        cell = out.setdefault(arm_of(r), {"unclean": 0, "env_unknown": 0, "of": 0})
        cell["of"] += 1
        why = _excluded(r)
        if why:
            cell[why] += 1
    return {a: c for a, c in out.items() if c["unclean"] or c["env_unknown"]}


def excluded_by_tag(rows: list[dict]) -> dict:
    """excluded_by_arm per tag."""
    out = {}
    for tag in sorted({str(r.get("tag")) for r in rows}):
        ex = excluded_by_arm([r for r in rows if str(r.get("tag")) == tag])
        if ex:
            out[tag] = ex
    return out


def lost_pairs(rows: list[dict], A: str, B: str) -> dict:
    """The units both arms ran (rows without an error) that a summary of clean rows cannot pair, because one side
    or both is not env_clean: how many, and per arm how many of them it made unclean. A loss that is not the same on
    both sides gets a note: the clean pairs left may no longer be like for like (one arm's harder units dropped)."""
    ps = pair_units(rows, A, B)
    lost = [(x, y) for x, y in ps if _excluded(x) or _excluded(y)]
    side = {A: sum(bool(_excluded(x)) for x, _ in lost), B: sum(bool(_excluded(y)) for _, y in lost)}
    out = {"lost": len(lost), "of": len(ps), "unclean_side": side}
    if lost:                                       # said even when even: the rule then stands on fewer pairs
        out["left_out"] = f"{len(lost)} of {len(ps)} shared pairs left out (not env_clean on one side or both)"
    if side[A] != side[B]:
        out["note"] = (f"one-sided loss: {side[A]} of {A}'s and {side[B]} of {B}'s rows on shared units were not "
                       "env_clean; the comparison counts only the pairs left and may be biased")
    return out


RIGHT_CI_FLOOR = -1.0     # the rule's right condition: the CI's lower end of balanced - save, in tasks


def right_diff_tasks(ps: list[tuple[dict, dict]], n_tasks: int | None = None) -> float | None:
    """B's right answers minus A's on these pairs, in tasks: the per-unit difference times the number of tasks (a
    task's rounds count as one task's worth), so -1 means one task's worth fewer right. `n_tasks`: the sample's
    task count, fixed while the bootstrap resamples tasks (a resample repeats some and drops others)."""
    if not ps:
        return None
    d = sum(bool(y.get("ok")) - bool(x.get("ok")) for x, y in ps)
    return round(d * (n_tasks or len({x["task"] for x, _ in ps})) / len(ps), 4)


def tier_rule(rows: list[dict], bal: str = TIER_RULE_ARMS[0], save: str = TIER_RULE_ARMS[1]) -> dict | None:
    """The tier decision rule on the clean units both arms share (env_clean only, whatever the summary counts):
    `balanced` is worth it over `save` when it is not less often right, its wall median is at most 60% of save's and
    its cost per success at most 1.5x save's. "Not less often right" is paired: the task-bootstrap 95% CI of
    balanced's minus save's right answers in tasks (right_diff_tasks) must have its lower end at RIGHT_CI_FLOOR (-1
    task) or above: pass; its upper end below it (clearly worse): fail; a CI across it, or no CI (fewer than two
    tasks), is Unknown, not a pass (ten tasks x three rounds cannot see a drop of one to three tasks). The floor is in
    tasks over the whole sample, so the CI of the summed difference widens with the number of tasks: with more tasks
    a pass is harder, and with ten any observed miss already gives Unknown (the condition reads as "no observed
    loss"). Each other condition: pass / fail (n/a when a cost per success is missing). Overall: fail when any
    condition fails, else unknown when the right condition is unknown, else n/a when one cannot be told, else pass;
    a pass whose shared units lost rows that are not env_clean unevenly (lost_pairs: more on one side) is Unknown
    too (`exclusion_note`). The wall median is the upper middle, as wall_med. None unless both arms have clean
    rows."""
    every = [r for r in rows if "error" not in r]
    rows, excluded = clean_rows(rows)
    ps = pair_units(rows, save, bal)
    if not ps:
        return None
    s_ok, b_ok = sum(bool(x.get("ok")) for x, _ in ps), sum(bool(y.get("ok")) for _, y in ps)
    s_w = _med([x.get("wall_s") or 0 for x, _ in ps])
    b_w = _med([y.get("wall_s") or 0 for _, y in ps])
    s_c, b_c = r3.cps([x for x, _ in ps]), r3.cps([y for _, y in ps])
    n_tasks = len({x["task"] for x, _ in ps})
    ci = task_boot(ps, lambda q: right_diff_tasks(q, n_tasks))
    pf = lambda v: "pass" if v else "fail"  # noqa: E731
    cond = {"right": {"rule": f"{bal} - {save} right answers, paired 95% CI lower end >= {RIGHT_CI_FLOOR:g} task",
                      "value": [b_ok, s_ok], "diff_tasks": right_diff_tasks(ps), "ci": ci,
                      "result": "unknown" if ci is None else "fail" if ci[1] < RIGHT_CI_FLOOR
                      else "unknown" if ci[0] < RIGHT_CI_FLOOR else "pass"},
            "wall": {"rule": f"{bal} wall median <= 60% of {save}'s", "value": [b_w, s_w],
                     "result": pf(b_w <= 0.6 * s_w)},
            "cps": {"rule": f"{bal} $/success <= 1.5x {save}'s", "value": [b_c, s_c],
                    "result": "n/a" if b_c is None or s_c is None else pf(b_c <= 1.5 * s_c)}}
    res = [c["result"] for c in cond.values()]
    lp = lost_pairs(every, save, bal)
    out = {"units": len(ps), "conditions": cond, "excluded_rows": excluded,
           "excluded_by_arm": {k: v for k, v in excluded_by_arm(every).items() if k in (bal, save)},
           "lost_pairs": lp,
           "result": "fail" if "fail" in res else "unknown" if "unknown" in res else "n/a" if "n/a" in res
           else "pass"}
    if lp.get("note"):
        out["exclusion_note"] = lp["note"]
        if out["result"] == "pass":
            out["result"] = "unknown"
    return out


B3_BASE = "ccx2daily"
B3_INPUT_DROP = 0.15          # the sub-agent's median prompt tokens per unit must be at least this much lower
# report-only paired token statistics (b3_paired); none of them changes the registered rule's result
B3_TOTAL_RATIO = 0.85         # token_effect "consistent" needs the arm's total prompt <= this share of the base's
B3_SHARE_LOWER = 0.6          # ... and the arm's prompt lower than the base's in at least this share of pairs
B3_BOOT_N = 2000              # pair-bootstrap resamples of the ratio of medians
B3_BOOT_SEED = 30             # fixed: the same rows give the same interval


def b3_median(xs) -> float | None:
    """The registered rule's median: the true median (statistics.median, the mean of the two middle values for an
    even count), not the upper middle the wall_med fields take."""
    xs = list(xs)
    return statistics.median(xs) if xs else None


def snapshot_of(r: dict) -> str | None:
    """The daily snapshot a row's unit ran on (daily.sha256 over the names and bytes of its copied setup)."""
    return (r.get("daily") or {}).get("sha256") if isinstance(r.get("daily"), dict) else None


def split_snapshots(ps: list[tuple[dict, dict]]) -> tuple[list[tuple[dict, dict]], list[dict]]:
    """(pairs whose two units ran on the same daily snapshot, or where a side does not say, and the pairs whose
    snapshots differ, by unit). A pair on two snapshots compares two different setups of the person's, not a switch:
    it is left out of the rule and of the paired statistics, both units together (b3_rule says how many)."""
    keep, split = [], []
    for x, y in ps:
        a, b = snapshot_of(x), snapshot_of(y)
        if a and b and a != b:
            split.append({"tag": x.get("tag"), "round": x.get("round"), "task": x.get("task"),
                          "base": a[:12], "arm": b[:12]})
        else:
            keep.append((x, y))
    return keep, split


def _rom(pa: list[float], pb: list[float]) -> float | None:
    """The ratio of medians arm / base (None when the base's median is 0 or there are no pairs)."""
    a = b3_median(pa)
    return b3_median(pb) / a if a else None


def b3_paired(pa: list[float], pb: list[float], n: int = B3_BOOT_N, seed: int = B3_BOOT_SEED,
              tasks: list[str] | None = None) -> dict:
    """Report-only paired statistics of the sub-agent prompt tokens (pa: the base's per pair, pb: the arm's, the same
    order): the share of pairs where the arm's is lower, the median of the per-pair ratio arm / base (pairs with a
    base of 0 left out), the total ratio, and two percentile 95% CIs of the ratio of medians (random.Random(seed), n
    resamples each): `ratio_of_medians_ci` resamples pairs as if independent, `ratio_of_medians_task_ci` resamples
    tasks with all their pairs (as task_boot; given `tasks`, one per pair), which is the honest one when a task has
    several rounds, since a task's rounds are correlated. `boot` says how many resamples had a base median of 0 and
    were dropped."""
    k = len(pa)
    if not k:
        return {"pairs": 0, "share_lower": None, "ratio_median": None, "total_ratio": None, "ratio_of_medians": None,
                "ratio_of_medians_ci": None, "ratio_of_medians_task_ci": None}
    ratios = [b / a for a, b in zip(pa, pb) if a]
    rom = _rom(pa, pb)
    ci, dropped = None, 0
    if k >= 2:
        rnd = random.Random(seed)
        vals = []
        for _ in range(n):
            idx = [rnd.randrange(k) for _ in range(k)]
            v = _rom([pa[i] for i in idx], [pb[i] for i in idx])
            if v is not None:
                vals.append(v)
        dropped = n - len(vals)
        vals.sort()
        if vals:
            ci = [round(vals[int(0.025 * len(vals))], 4), round(vals[int(0.975 * len(vals)) - 1], 4)]
    task_ci, tinfo = None, {"n": 0, "dropped": 0}
    if tasks is not None and len(tasks) == k:
        ps = [({"task": t, "a": a}, {"b": b}) for t, a, b in zip(tasks, pa, pb)]
        tci = task_boot(ps, lambda xs: _rom([x["a"] for x, _ in xs], [y["b"] for _, y in xs]) if xs else None,
                        n=n, seed=seed, info=tinfo)
        task_ci = list(tci) if tci else None
    return {"pairs": k, "share_lower": round(sum(b < a for a, b in zip(pa, pb)) / k, 4),
            "ratio_median": round(b3_median(ratios), 4) if ratios else None,
            "total_ratio": round(sum(pb) / sum(pa), 4) if sum(pa) else None,
            "ratio_of_medians": round(rom, 4) if rom is not None else None, "ratio_of_medians_ci": ci,
            "ratio_of_medians_task_ci": task_ci,
            "tasks": len(set(tasks)) if tasks is not None else None,
            "boot": {"n": n, "seed": seed, "dropped": dropped, "task_n": tinfo.get("n", 0),
                     "task_dropped": tinfo.get("dropped", 0)}}


B3_REGISTERED_PAIRS = 50   # the B3 plan's paired units per arm (hold-out 10 x 3 + r5 10 x 2); report-only


def b3_rule(rows: list[dict], arm: str, base: str = B3_BASE) -> dict | None:
    """The B3 decision rule fixed before any run (docs/research/2026-10-30-b3-lean-switches-plan.md), on the clean
    units both arms share: a switch's default changes only if right_B >= right_A (right not lower), at most 2 lost pairs (A right,
    B wrong), no task B got wrong in every round while A got it right at least once, and the sub-agent's median
    prompt tokens per unit (sub_usage.prompt: input + cached of ccx's work runs; the true median, b3_median) at least
    B3_INPUT_DROP lower. Any unclean pair lost on one side only (lost_pairs note), or a missing token count, makes it
    Unknown. Result pass / fail / unknown; None unless both arms have clean rows.

    Report-only, next to the rule (never changing `result`): `paired` (b3_paired) and `token_effect`: "consistent"
    only when the rule's token condition passes, the total ratio is <= B3_TOTAL_RATIO and the arm's prompt is lower in
    at least B3_SHARE_LOWER of the pairs; else "not shown". Pairs whose units ran on different daily snapshots are
    left out of the conditions and the statistics (`snapshot_mismatch` lists them) and, like an unclean pair lost on
    one side, turn a pass into Unknown; when every pair is split the rule is reported as Unknown on 0 pairs."""
    every = [r for r in rows if "error" not in r]
    clean, excluded = clean_rows(every)
    ps, split = split_snapshots(pair_units(clean, base, arm))
    if not ps and not split:
        return None
    a_ok, b_ok = sum(bool(x.get("ok")) for x, _ in ps), sum(bool(y.get("ok")) for _, y in ps)
    lost = sum(bool(x.get("ok")) and not y.get("ok") for x, y in ps)
    tasks: dict = {}
    for x, y in ps:
        t = tasks.setdefault(x["task"], {"a": 0, "b": 0, "n": 0})
        t["a"] += bool(x.get("ok"))
        t["b"] += bool(y.get("ok"))
        t["n"] += 1
    always_lost = sorted(k for k, t in tasks.items() if t["b"] == 0 and t["a"] > 0)
    pa = [(x.get("sub_usage") or {}).get("prompt") for x, _ in ps]
    pb = [(y.get("sub_usage") or {}).get("prompt") for _, y in ps]
    have = None not in pa and None not in pb
    ma, mb = (b3_median(pa), b3_median(pb)) if have else (None, None)
    pf = lambda v: "pass" if v else "fail"  # noqa: E731
    cond = {"right": {"rule": f"{arm} right >= {base} right", "value": [b_ok, a_ok], "result": pf(b_ok >= a_ok)},
            "lost_pairs": {"rule": f"at most 2 pairs {base} right, {arm} wrong", "value": lost,
                           "result": pf(lost <= 2)},
            "always_lost": {"rule": f"no task {arm} got wrong in every round that {base} got right once",
                            "value": always_lost, "result": pf(not always_lost)},
            "input": {"rule": f"{arm} sub-agent median prompt tokens <= {1 - B3_INPUT_DROP:.0%} of {base}'s",
                      "value": [mb, ma],
                      "result": "unknown" if not have or not ma else pf(mb <= (1 - B3_INPUT_DROP) * ma)}}
    res = [c["result"] for c in cond.values()]
    lp = lost_pairs(every, base, arm)
    out = {"units": len(ps), "tasks": len(tasks), "conditions": cond, "excluded_rows": excluded, "lost_pairs": lp,
           "result": "fail" if "fail" in res else "unknown" if "unknown" in res else "pass"}
    if len(ps) < B3_REGISTERED_PAIRS:
        # report-only (the result stays as the conditions give it): the plan registered B3_REGISTERED_PAIRS pairs per
        # arm; a result on fewer is on less than the measurement was planned for, which the reader must see
        out["registered"] = {"pairs": B3_REGISTERED_PAIRS, "counted": len(ps),
                             "note": f"registered {B3_REGISTERED_PAIRS} pairs, counted {len(ps)}: this result is on "
                                     f"fewer pairs than the B3 plan registered (both halves: summary --results "
                                     f"<a> <b> --tag <hold-out> --tag <r5>)"}
    if lp.get("note"):
        out["exclusion_note"] = lp["note"]
        if out["result"] == "pass":
            out["result"] = "unknown"
    if split:
        # conservative, as lost_pairs' exclusion_note: a left-out pair could have been a lost one, so a pass becomes
        # Unknown (a fail stays a fail)
        out["snapshot_mismatch"] = {"pairs": len(split), "units": split,
                                    "note": "left out of the rule's conditions and of the paired statistics: the two "
                                            "units ran on different snapshots of the person's daily setup; a pass "
                                            "becomes unknown"}
        if out["result"] == "pass":
            out["result"] = "unknown"
    paired = (b3_paired([float(v) for v in pa], [float(v) for v in pb], tasks=[x["task"] for x, _ in ps])
              if have else
              {"pairs": len(ps), "note": "a token count is missing: no paired statistics"})
    out["paired"] = paired
    consistent = (cond["input"]["result"] == "pass" and paired.get("total_ratio") is not None
                  and paired["total_ratio"] <= B3_TOTAL_RATIO and (paired.get("share_lower") or 0) >= B3_SHARE_LOWER)
    out["token_effect"] = "consistent" if consistent else "not shown"
    return out


def b3_rules(rows: list[dict]) -> dict:
    """b3_rule for every daily variant that shares clean units with the daily baseline."""
    arms = {arm_of(r) for r in rows if "error" not in r}
    out = {}
    if B3_BASE not in arms:
        return out
    for arm in DAILY_ARMS:
        if arm != B3_BASE and arm in arms:
            br = b3_rule(rows, arm)
            if br:
                out[f"{B3_BASE} vs {arm}"] = br
    return out


def b3_rule_lines(name: str, br: dict) -> list[str]:
    """One B3 rule as plain lines (cmd_summary prints them after the JSON, on stderr)."""
    c = br["conditions"]
    p = br.get("paired") or {}
    out = [f"!! b3 rule {name}: {br['registered']['note']}"] if br.get("registered") else []
    out += [f"b3 rule {name}: {br['result']} on {br['units']} pairs ({br['tasks']} tasks); right {c['right']['value']}, "
           f"lost {c['lost_pairs']['value']}, always lost {c['always_lost']['value'] or 'none'}, median prompt "
           f"{c['input']['value']} ({c['input']['result']})"]
    if p.get("pairs"):
        out.append(f"  paired (report only): lower in {p.get('share_lower')} of pairs, per-pair ratio median "
                   f"{p.get('ratio_median')}, total ratio {p.get('total_ratio')}, ratio of medians "
                   f"{p.get('ratio_of_medians')} 95% CI {p.get('ratio_of_medians_ci')} by pair, "
                   f"{p.get('ratio_of_medians_task_ci')} by task; token effect "
                   f"{br['token_effect']}")
    if br.get("snapshot_mismatch"):
        out.append(f"  {br['snapshot_mismatch']['pairs']} pairs on different daily snapshots left out (a pass "
                   "becomes unknown)")
    if br.get("exclusion_note"):
        out.append(f"  {br['exclusion_note']}")
    elif (br.get("lost_pairs") or {}).get("left_out"):
        out.append(f"  {br['lost_pairs']['left_out']}")
    return out


def tier_rule_lines(tr: dict | None) -> list[str]:
    """The tier decision rule as plain lines (cmd_summary prints them after the JSON, on stderr)."""
    if not tr:
        return []
    return [f"tier rule ({tr['units']} shared clean units): {tr['result']}"] + \
        [f"  {c['result']:7}  {c['rule']}: {c['value'][0]} vs {c['value'][1]}"
         + (f" (diff {c['diff_tasks']} tasks, CI {c['ci']})" if "ci" in c else "") for c in tr["conditions"].values()] \
        + ([f"  note     {tr['exclusion_note']}"] if tr.get("exclusion_note") else []) \
        + ([f"  note     {tr['lost_pairs']['left_out']}"]
           if (tr.get("lost_pairs") or {}).get("left_out") and not tr.get("exclusion_note") else [])


def tier_rules(rows: list[dict]) -> dict:
    """tier_rule for every lead that has both arms (`balanced` and `save`, or `balanced@opus-high` and
    `save@opus-high`): the same lead's arms only, never one lead's balanced against another's save."""
    arms = {arm_of(r) for r in rows if "error" not in r}
    out = {}
    for b in arm_order(arms):
        base, _, suf = b.partition("@")
        s = TIER_RULE_ARMS[1] + (f"@{suf}" if suf else "")
        if base == TIER_RULE_ARMS[0] and s in arms:
            tr = tier_rule(rows, b, s)
            if tr:
                out[f"{b} vs {s}"] = {**tr, "pair": f"{b} vs {s}"}   # which lead's arms, read on its own too
    return out


def _count(xs) -> dict:
    out: dict = {}
    for x in xs:
        out[str(x)] = out.get(str(x), 0) + 1
    return dict(sorted(out.items()))


def tier_summary(rows: list[dict]) -> dict | None:
    """Per tier arm (as arm_of names it): right, $/success, wall median / mean / p75 (wall_stats), the misbanding
    rate (`misband`: the lead's --files band vs the reference change's files band; `misband_overall`: the planned
    band vs that, which leans over by construction; each says its basis; under = planned smaller), how the runs
    picked their models (`route_sources`), the planned and the
    actual modes, how often the actual mode was the planned one, and on failed units how often ccx's --check had
    passed anyway. None without tier rows."""
    rows = [r for r in rows if "error" not in r and r.get("arm") in TIER_ARMS]
    if not rows:
        return None
    def mb_stats(xs: list, basis: str) -> dict:
        wrong = sum(m != "same" for m in xs)
        return {"basis": basis, "n": len(xs), "wrong": wrong, "rate": round(wrong / len(xs), 4) if xs else None,
                **{k: sum(m == k for m in xs) for k in ("under", "over")}}

    out = {}
    for arm in arm_order(arm_of(r) for r in rows):
        rs = [r for r in rows if arm_of(r) == arm]
        fails = [r for r in rs if not r.get("ok") and r.get("ccx_check_passed") is not None
                 and r.get("ccx_check_reason") != "namecheck"]   # namecheck's stand-in: the command never ran
        nc_fails = sum(not r.get("ok") and r.get("ccx_check_reason") == "namecheck" for r in rs)
        fol = [r["followed_plan"] for r in rs if r.get("followed_plan") is not None]
        routes = [x.get("source") for r in rs for x in r.get("ccx_routes") or []]
        out[arm] = {**wall_stats(rs), "right": f"{sum(bool(r.get('ok')) for r in rs)}/{len(rs)}",
                    "misband": mb_stats([r["misband"] for r in rs if r.get("misband")],
                                        "files: the lead's --files band vs the reference change's files band"),
                    "misband_overall": mb_stats(
                        [r["misband_overall"] for r in rs if r.get("misband_overall")],
                        "planned band (brief words, --minutes, --files) vs the reference files band: leans over by "
                        "construction"),
                    "route_sources": _count(routes) if routes else None,
                    "planned_modes": _count((r.get("tier_plan") or {}).get("mode") for r in rs),
                    # who planned it: propose (ccx), tier (fast's rule), eval-script (cheapest: ccx planned nothing)
                    "plan_sources": _count((r.get("tier_plan") or {}).get("source") for r in rs),
                    "actual_modes": _count(r.get("actual_mode") for r in rs),
                    "followed_plan": f"{sum(fol)}/{len(fol)}" if fol else None,
                    "check_passed_on_fail": f"{sum(bool(r['ccx_check_passed']) for r in fails)}/{len(fails)}"
                    if fails else None}
        if nc_fails:
            out[arm]["failed_on_namecheck"] = nc_fails      # wrong units whose last check was namecheck's
        if any(r.get("may_be_wrong") for r in rs):
            out[arm]["may_be_wrong"] = True
    return out


def phase_stats(rs: list[dict]) -> dict | None:
    """Median and p75 of each phase's wall (phase_wall) over the rows that carry one."""
    ph = [r["phases"] for r in rs if r.get("phases")]
    if not ph:
        return None
    return {k: med_p75([p[k] for p in ph if p.get(k) is not None]) for k in PHASES if any(k in p for p in ph)}


def summarize(rows: list[dict], include_unclean: bool = False) -> dict:
    """Per arm, per tag, paired and tier summaries of env_clean rows (`excluded_rows` says how many others were left
    out; include_unclean counts them everywhere except the tier rule, which always takes clean rows only)."""
    completion_and_cost = completion_cost_summary(
        rows, right=lambda r: r.get("ok") if isinstance(r.get("ok"), bool) and not r.get("error") else None,
        arm=arm_of)
    unclean = sum(r.get("env_clean") is False for r in rows if "error" not in r)
    unknown = sum("env_clean" not in r for r in rows if "error" not in r)    # rows from before the clean room
    tags = sorted({str(r.get("tag")) for r in rows})
    excluded, ex_arm, ex_tag = {"unclean": 0, "env_unknown": 0}, {}, {}
    every = [r for r in rows if "error" not in r]          # the tier rule picks its clean rows itself
    if not include_unclean:
        ex_arm, ex_tag = excluded_by_arm(rows), excluded_by_tag(rows)
        rows, excluded = clean_rows(rows)
    rows = [r for r in rows if "error" not in r]
    out = {}
    for arm in arm_order(arm_of(r) for r in rows):
        rs = [r for r in rows if arm_of(r) == arm]
        med = lambda k: sorted(r.get(k) or 0 for r in rs)[len(rs) // 2]  # noqa: E731
        ok = sum(bool(r.get("ok")) for r in rs)
        lead_usd = round(sum(r.get("lead_usd") or 0 for r in rs), 4)
        ccx_usd = round(sum(r.get("ccx_usd") or 0 for r in rs), 4)
        # who did the work, the same split for every arm: the lead itself, and whoever it delegated to (ccx's
        # sub-agents, or a builtin arm's Agent-tool worker, which lead_usd holds)
        only = round(sum(r.get("lead_only_usd") or 0 for r in rs), 4)
        sub = round(sum(r.get("sub_usd") or 0 for r in rs), 4)
        out[arm] = {"ok": ok, "n": len(rs), "usd": round(sum(r.get("usd") or 0 for r in rs), 4),
                    "cps": round(sum(r.get("usd") or 0 for r in rs) / ok, 4) if ok else None,
                    # whose spend: the lead's own (a builtin worker is inside it) and ccx's runs, each per success
                    "lead_usd": lead_usd, "ccx_usd": ccx_usd,
                    "lead_cps": round(lead_usd / ok, 4) if ok else None,
                    "ccx_cps": round(ccx_usd / ok, 4) if ok else None,
                    "lead_only_usd": only, "sub_usd": sub,
                    "lead_only_cps": round(only / ok, 4) if ok else None,
                    "sub_cps": round(sub / ok, 4) if ok else None,
                    "lead_only_usd_med": med("lead_only_usd"), "lead_tokens_med": med("lead_tokens"),
                    "lead_requests_med": med("lead_requests"), "wall_med": med("wall_s"),
                    **{k: v for k, v in wall_stats(rs).items() if k in ("wall_mean", "wall_p75")},
                    "wilson": S.wilson(ok, len(rs)),
                    # Wilson takes every row as an independent trial; a task's rounds are not: this one resamples
                    # tasks (task_boot), as the paired CIs do
                    "ok_rate_ci_tasks": task_boot([(r, r) for r in rs], ok_rate),
                    "ok_by_round": {str(rd): sum(bool(r.get("ok")) for r in rs if r.get("round") == rd)
                                    for rd in sorted({r.get("round") for r in rs}, key=round_key)}}
        n_tasks = len({r.get("task") for r in rs})
        if len(rs) > n_tasks:
            out[arm]["wilson_note"] = (f"{len(rs)} rows from {n_tasks} tasks: Wilson takes them as independent "
                                       "(too narrow); see ok_rate_ci_tasks")
        ph = phase_stats(rs)
        if ph:
            out[arm]["phases"] = ph
        if ex_arm.get(arm):
            out[arm]["excluded"] = ex_arm[arm]
        nc = namecheck_stats(rs)
        if nc:
            out[arm]["namecheck"] = nc
        if arm.split("@", 1)[0] in SKILL_ARMS:        # did the lead load the skill the arm is about
            used = [r.get("skill_used") for r in rs]
            out[arm]["skill_used"] = f"{sum(x is True for x in used)}/{len(rs)}"
            if not all(x is True for x in used):
                out[arm]["skill_used_note"] = (f"{sum(x is not True for x in used)} of {len(rs)} units: the lead "
                                               "did not load agent-delegate (the arm's protocol not followed)")
    res = {"completion_and_cost": completion_and_cost,
           "arms": out, "by_tag": by_tag(rows), "unclean_rows": unclean, "env_unknown_rows": unknown, "tags": tags,
           "counted": "all rows (--include-unclean)" if include_unclean else "env_clean rows only",
           "excluded_rows": excluded,
           "long_style": r4.summarize_long([{**r, "arm": arm_of(r)} for r in rows
                                            if arm_of(r) in r4.LONG_ARMS])["paired"],
           "paired": paired_all(rows, None if include_unclean else every)}
    if ex_arm:
        res["excluded_by_arm"] = ex_arm
        res["excluded_by_tag"] = ex_tag
    # the Codex Windows sandbox each row actually ran under: the rows without an error, clean or not (as batch.py),
    # whose arm starts Codex
    mix = PF.sandbox_mix(every)
    if mix:
        res["codex_windows_sandbox"] = mix
    b3 = b3_rules(every)
    if b3:
        res["b3_rules"] = b3
    trs = tier_rules(every)
    if trs:
        res["tier_rules"] = trs
        # the default lead's (#142's field), else the first other lead's in arm_order (sorted, so stable): the
        # confirmation run's lead is Opus. Its `pair` says which lead's arms it is
        res["tier_rule"] = trs.get(f"{TIER_RULE_ARMS[0]} vs {TIER_RULE_ARMS[1]}") or next(iter(trs.values()))
    ts = tier_summary(rows)
    if ts:
        res["tiers"] = ts
    if any(r.get("ext") for r in rows):
        # per code base, with each external task's commit date (results are reported per repository and by date:
        # a fix from before a model's training cutoff may be remembered)
        by: dict = {}
        for r in rows:
            e = r.get("ext") or {}
            cell = by.setdefault(e.get("repo") or "this repository", {}).setdefault(arm_of(r), {"ok": 0, "n": 0})
            cell["ok"] += bool(r.get("ok"))
            cell["n"] += 1
        res["by_repo"] = by
        res["ext_dates"] = {r["task"]: r["ext"].get("date") for r in rows if r.get("ext")}
    return res


def tagged(rows: list[dict], tag) -> list[dict]:
    """Rows of one tag (round), so rounds run under different conditions are never counted together; a list of tags
    keeps the rows of any of them (summary --tag a --tag b: two halves of one registered measurement)."""
    if not tag:
        return list(rows)
    tags = {tag} if isinstance(tag, str) else set(tag)
    return [r for r in rows if r.get("tag") in tags]


def summary_rows(a) -> list[dict]:
    """The rows a summary reads: --results files in the order given (default: the task set's results file), then
    --tag. A row read twice (the same file named twice) is counted once."""
    files = [Path(f) for f in (getattr(a, "results", None) or [])] or [results_file(a.taskset)]
    rows, seen = [], set()
    for f in files:
        for r in read_jsonl(f):
            key = json.dumps(r, sort_keys=True, ensure_ascii=False)
            if key not in seen:
                seen.add(key)
                rows.append(r)
    return tagged(rows, getattr(a, "tag", None))


def excluded_line(res: dict) -> str | None:
    ex = res.get("excluded_rows") or {}
    n = sum(ex.values())
    if not n:
        return None
    per = res.get("excluded_by_arm") or {}
    arms = ("; per arm: " + ", ".join(f"{a} {c['unclean'] + c['env_unknown']}/{c['of']}" for a, c in per.items())
            if per else "")
    return (f"left out {n} rows that are not env_clean ({ex.get('unclean', 0)} unclean, {ex.get('env_unknown', 0)} "
            f"from before the clean room){arms}; --include-unclean counts them (the tier and B3 rules never do)")


def cmd_summary(a) -> int:
    res = summarize(summary_rows(a), a.include_unclean)
    print(json.dumps(res, ensure_ascii=False, indent=1))
    line = excluded_line(res)
    if line:
        print(line, file=sys.stderr)
    note = (res.get("codex_windows_sandbox") or {}).get("note")
    if note:                                                  # rounds under different sandboxes: say so loudly
        print(f"*** {note} ***", file=sys.stderr)
    for name, tr in (res.get("tier_rules") or {}).items():   # stdout stays one JSON object
        for line in tier_rule_lines(tr):
            print(line if name == "balanced vs save" else line.replace("tier rule", f"tier rule {name}", 1),
                  file=sys.stderr)
    for name, br in (res.get("b3_rules") or {}).items():
        for line in b3_rule_lines(name, br):
            print(line, file=sys.stderr)
    return 0


def cmd_export(a) -> int:
    keep = ("tag", "taskset", "round", "task", "arm", "ok", "pytest", "rc", "wall_s", "usd", "lead_usd", "lead_only_usd",
            "sub_usd", "by_model_usd", "ccx_usd", "ccx_review_usd", "ccx_agents", "lead_requests", "lead_tokens",
            "lead_output_tokens", "lead_tools", "lead_edits", "agent_calls", "ccx_runs", "ccx_resumes", "rework",
            "delegated", "context_attached", "files_changed", "diffstat", "model", "status", "kind", "verdicts", "error",
            "env_clean", "fingerprint", "lead_model", "lead_effort", "lead_pick", "lead_b", "lead_band", "phases", "tier", "tier_plan", "ref_size",
            "actual_mode", "misband", "misband_overall", "followed_plan", "ccx_check_passed", "may_be_wrong",
            "ccx_routes", "bookkeeping_error", "lead_usage", "timeline", "skill_used", "skills_used",
            "namecheck_mode", "user_words_mode", "ccx_namecheck", "ccx_check_reason", "sub_usage", "switches_applied",
            "hidden_failed", "artifacts", "streams", "streams_error", "arm_order", "arm_pos", "small_self_run")
    rows = summary_rows(a)
    data = {"summary": summarize(rows, a.include_unclean),
            "rows": [r3.scrub({**{k: r[k] for k in keep if k in r},
                               **({"audit": {"problems": r["audit"].get("problems"),
                                             "n_path_hits": r["audit"].get("n_path_hits")}} if r.get("audit") else {})})
                     for r in rows]}
    Path(a.dest).write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {a.dest}: {len(rows)} rows")
    return 0


def daily_options(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("--daily-codex-source", default="", help="daily arms: the person's Codex home to copy memories, "
                    "AGENTS.md and skills from (default ~/.codex; auth, config, sessions and logs are never copied)")
    ap.add_argument("--daily-agents-source", default="", help="daily arms: the person's ~/.agents to copy skills/ "
                    "from (default ~/.agents)")


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--tag", default="r5")
    r.add_argument("--seed", type=int, default=53)
    r.add_argument("--rounds", type=int, default=2)
    r.add_argument("--taskset", choices=sorted(TASKSETS), default="r5",
                   help="r5 (default: the tasks the loop was tuned on), holdout (unseen, for final claims) or "
                        "polyglot (30 Exercism exercises of aider's polyglot benchmark; default arms self,ccx2,direct)")
    r.add_argument("--tasks", default="", help="comma-separated ids from the task set (default: all of it)")
    r.add_argument("--arms", default="")
    r.add_argument("--arm-order", choices=ARM_ORDERS, default="shuffle", help="shuffle (default, every earlier "
                   "run's schedule): the arms of a task in a seeded random order; balanced: a seeded Latin-square "
                   "rotation over task and round, so each arm runs first about equally often")
    r.add_argument("--budget", type=float, default=3.0,
                   help="stop before a new unit once this tag's rows (plus --extra-spent) reach $")
    r.add_argument("--extra-spent", type=float, default=0.0, help="$ spent elsewhere, counted against --budget")
    r.add_argument("--lead-model", default="", help=f"the lead's Claude model (default: {DEFAULT_LEAD[0]}), or "
                   "auto: each task's from its difficulty by ccx's lead.model_by_task rule (its own arm, @auto); "
                   "recorded in every row and its done-key")
    r.add_argument("--lead-effort", default="", help=f"the lead's effort (default: {DEFAULT_LEAD[1]})")
    r.add_argument("--jobs", type=int, default=2, help="tasks run at the same time")
    r.add_argument("--lead-budget", type=float, default=3.0, help="claude -p --max-budget-usd for one lead")
    r.add_argument("--out", default="")
    r.add_argument("--workdir", default="")
    r.add_argument("--timeout", type=int, default=2400)
    r.add_argument("--dry-run", action="store_true")
    r.add_argument("--pin-commit", default="", help="refuse to run unless this checkout is at this commit (a tag "
                   "is also refused at a commit other than its earlier rows')")
    r.add_argument("--no-canary", action="store_true",
                   help="skip the canaries: the one tiny real lead that checks the isolation and, when an arm starts "
                        "Codex, the one real Codex T1 request that must run a shell command")
    r.add_argument("--wait-quiet", type=_minutes, default=0, metavar="MINUTES", help="wait up to this long for "
                   "other heavy work on this machine (another eval, pytest, ccx run, claude -p, codex exec) to finish: "
                   "before the checks (still busy then, the preflight refuses as usual), and between units when that "
                   "work starts during a run (the unit it overlapped stays not env_clean and is not run again under "
                   "this tag; still busy then, the run stops). Unlike --force-unclean it never runs on a busy machine")
    r.add_argument("--ext-cache", default="", help="a folder with local copies (clones) of the other repositories "
                   "of the hold-out set, named after them, to clone from instead of their URLs")
    r.add_argument("--ext-python", default="", help="the Python that runs the other repositories' tests (needs "
                   "Python 3.11+, pytest and their test modules, e.g. freezegun, and not the libraries themselves; "
                   "keep it away from the --ext-cache folder; default: this one)")
    daily_options(r)
    PF.add_options(r)
    r.set_defaults(fn=cmd_run)
    dc = sub.add_parser("daily-check", help="build one daily-config home in a temporary folder, list it, remove it")
    dc.add_argument("--codex-home", default=os.environ.get("CCX_EVAL_CODEX_HOME", ""),
                    help="the eval Codex home whose login the daily home copies")
    daily_options(dc)
    dc.set_defaults(fn=cmd_daily_check)
    s = sub.add_parser("summary")
    s.add_argument("--tag", action="append", default=None, help="only this round's rows (default: all; the tags are "
                   "listed); give it again to keep several tags (two halves of one measurement)")
    s.add_argument("--results", nargs="+", default=None, help="results files to read together (default: the task "
                   "set's own); a row in two of them is counted once")
    s.add_argument("--taskset", choices=sorted(TASKSETS), default="r5")
    s.add_argument("--include-unclean", action="store_true", help="count rows that are not env_clean too in the "
                   "tables and pair statistics (the tier rule and the B3 rule still take clean rows only)")
    s.set_defaults(fn=cmd_summary)
    e = sub.add_parser("export")
    e.add_argument("dest")
    e.add_argument("--tag", action="append", default=None)
    e.add_argument("--results", nargs="+", default=None)
    e.add_argument("--taskset", choices=sorted(TASKSETS), default="r5")
    e.add_argument("--include-unclean", action="store_true", help="count rows that are not env_clean in the "
                   "summary section too (every row is exported either way)")
    e.set_defaults(fn=cmd_export)
    return ap


def main(argv=None) -> int:
    a = parser().parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
