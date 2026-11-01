# Install and commands

English · [中文](install.zh.md) · back to the [README](../README.md)

## Install

**Requirements:**
- Python 3.11+ (standard library only).
- `codex` and `claude` CLIs, both logged in. `dsh` (DeepSeek Harness) optional; `gemini` optional and only as a
  sub-agent (adapter written from its docs, not run for real).

**Without a clone** (the skills and config ship inside the package):

```bash
pipx install git+https://github.com/SUPERD6/relayline
ccx setup        # guided: hub, wiring, health check; asks before each change
ccx run --to codex --mode read "Summarise README.md in three lines for a new user: what this project does, how to install it, and the first command to try"
```

The last line is your first delegation (the same one README and `ccx setup` suggest). Step by step instead of
`ccx setup`: `ccx init --hub <your hub path>`, `ccx sync`, `ccx sync --apply`, `ccx doctor`. The hub is one folder
of your own for shared memory, skills and the record of every run. Once this machine has a hub, `ccx init --hub`
with another folder stops and shows the one in use; add `--force` to switch (the old hub's files stay where they
are). The same goes for a `--snapshot` / `--external-sync` that would replace a different `layout.toml`.

No pipx? A virtual environment of its own does the same:

```bash
python3 -m venv ~/.relayline && ~/.relayline/bin/python -m pip install git+https://github.com/SUPERD6/relayline
```

```powershell
python -m venv "$env:USERPROFILE\.relayline"; & "$env:USERPROFILE\.relayline\Scripts\python.exe" -m pip install git+https://github.com/SUPERD6/relayline
```

Then run `ccx` from that environment's `bin` (Windows: `Scripts`) folder, or link just `ccx` into a folder on your
PATH (putting the whole folder on PATH also puts its `python` and `pip` first).

**From the plugin marketplace** (the repository is its own marketplace, `relayline`):

```bash
claude plugin install relayline --marketplace SUPERD6/relayline     # Claude Code 2.1.275+, one step
# older Claude Code: claude plugin marketplace add SUPERD6/relayline && claude plugin install relayline@relayline
codex plugin marketplace add SUPERD6/relayline && codex plugin add relayline@relayline   # Codex 0.164, experimental
```

The Claude Code install ran for real (from a temporary config). The Codex install from a GitHub address is
**experimental**: it follows Codex's plugin docs; the tests check only the plugin manifest, the install command
itself has never run.

- **Claude Code** gets the five skills (as `relayline:agent-delegate`, `relayline:task-routing`, `relayline:task-split`,
  `relayline:task-checkpoint`, `relayline:project-manager`) and ccx's two hooks: the start-of-session shared-memory
  delta and the per-turn board / shared-document line. The hooks run the copy of ccx inside the plugin (`bin/ccx`, through `sh`; on Windows that is
  the Git Bash Claude Code uses for hooks), so they need Python 3.11+ but no separate install. Before `ccx init` they
  print nothing.
- **Codex** gets the five skills only. Its hooks stay with `ccx sync` (plugin hooks in Codex must be trusted by
  hand and are not offered here).
- **DeepSeek Harness (`dsh`)** has no plugin marketplace or skill install yet (its README, read 2026-10-25); `ccx sync`
  writes its lead instructions as before when `dsh` is on PATH. A `dsh` found only inside the installed desktop
  app is not connected by default; sync mentions it once as optional (put it on PATH, then `ccx sync` again).
- **Still install ccx itself** (`pipx install git+https://github.com/SUPERD6/relayline`, then `ccx init` or
  `ccx setup`) to delegate from a terminal or from Codex. `ccx doctor` says so when the plugin is enabled but ccx is
  not installed on its own.
- **No double wiring:** where the plugin is enabled, `ccx sync` leaves the Claude hooks and the five skills to it and
  takes out the copies it wrote earlier (`ccx:` hooks in `settings.json`, links in the tools' `skills/` folders);
  Codex's hook block stays. `ccx doctor` warns if a hook is still there twice.

**From a clone** (to develop, or to let `git pull` upgrade the skills linked into your hub):

```powershell
git clone https://github.com/SUPERD6/relayline
cd relayline
.\install.ps1 -Hub <your hub path>      # Windows; macOS/Linux (experimental, CI only): ./install.sh <hub path>
```

**The install script:**
- Runs `pipx install --editable .` if pipx is there, so `ccx` is on your PATH. Otherwise it tells you to add `bin/`
  to PATH.
- Runs `ccx init`, which only creates files and never changes existing ones. When this machine already uses another
  hub, it stops there and shows that hub; to switch, run it again with `-Force` (`./install.sh <hub path> --force`).
- Runs `ccx doctor`, which checks CLIs, logins and wiring and reports Unknown when unsure. Rows about ccx's own
  workings (routing prior, tier policy, hub layout, ...) show only when something is wrong there, or with `--verbose`.

**Then** run the guided first run, `ccx setup` (it explains each step and asks before changing anything), or do it
step by step:

```powershell
ccx sync            # dry run: lists every change, touches nothing
ccx sync --apply    # apply; each changed file is backed up as *.ccx-backup-YYYYMMDD
ccx selftest        # one tiny real task per installed agent on its cheapest model: login, parsing, start-up cost
```

Finally, open `/hooks` in Codex once and trust the "ccx: shared memory delta" hook.

**Already have a shared setup?** For example, one AGENTS.md both tools read and your own sync script. Plug it in:

```powershell
ccx init --hub <path> --snapshot AGENTS.md --external-sync "<your sync command>"
```

ccx then never edits the tools' instruction files, and leaves skills and MCP to your script. On a machine that
already has another hub, or a `layout.toml` with other values, it stops and says so; add `--force` to replace them.

## Commands

```text
ccx run "task" --from claude --files 3 --coupling cross --clarity goal   # routed by the rubric (recommended)
ccx run "task" --model gpt-6.1-sol --effort high                         # explicit model and effort
ccx run "task" --tier T2                                                 # fixed tier
     [--mode read] [--check "pytest -q tests/test_x.py"] [--kind code|read|research|write] [--minutes 60]
     [--review auto|on|off] [--risk visible] [--seat reviewer] [--worktree] [--task <id> --step <n>] [--no-subagents] [--no-fallback] [--force] [--bg [--wait 540]]
ccx quota [--probe]                   # each subscription window projected to its reset (what routing prices quota at)
ccx bench [refresh]                   # the public benchmark data routing uses, its age and credits
ccx run "task" --to gemini --tier T2                         # Gemini CLI as the sub-agent
ccx run "task" --to deepseek       # DeepSeek flash through Claude Code (key in DEEPSEEK_API_KEY), effort by difficulty
ccx run "task" --provider deepseek-codex     # the same model through Codex (a model provider set with -c, key from env)
ccx run "task" --to dsh --tier T2            # DeepSeek's own agent, DeepSeek Harness (headless profile)
ccx run "task" --provider glm                # smaller APIs through Claude Code: kimi, glm, qwen, openrouter (key needed)
ccx verify <run_id> --ok 1|0 [--note "..."]   # the lead's verdict: calibrates routing/splitting, closes the checkpoint step
ccx resume <run_id> "follow-up"       # same sub-session; also how an interrupted run continues
ccx run "task" ... --bg --wait 540     # detached, then waits in the same call: the final result, or (not done by
                                      # then) exactly the --bg output; the id goes to stderr at once.
                                      # `ccx resume ... --bg [--wait N]` likewise
ccx stop <run_id>                     # stop a running delegation (its whole process tree); resume continues it
ccx task status | resume <task>       # long tasks: one command continues the interrupted step (hands off on quota)
ccx handoff --by claude --to codex "what's done / decided / next" [--next "task 5" ...]   # switch leads
ccx lead                                     # what each turn of your lead conversations re-reads and costs
ccx lead --breakdown | --cache | --suggest   # each re-read part / where the cache broke / a model for the lead itself
ccx sum -- python -m pytest -q               # run a command, show the lead only what matters (tests: failures); full output in .ccx/sum/
ccx fresh [--launch]                         # move a long conversation to a fresh one of the same tool, handoff from its file
ccx propose --lead claude:opus:high --minutes 30 "…"  # before offering to delegate: estimate, one line to say, recorded (--no ID, --stats)
ccx trial start | stop | report              # a week-long comparison: half the delegable tasks done by the lead, half delegated
ccx trial tag --arm native --session ID      # count a conversation that used Claude Code's own helpers / a workflow as a third half
ccx agents                                   # each agent CLI: vendor, what it can do, tested version, official or community
ccx way "brief" --risk low|visible|critical  # the risk picks the way: one agent / plan-build-accept / two versions (--yes)
ccx way --stats [--include-evals]           # per kind of work and tier: who is right the first time, how often rework
ccx discuss "question" [--dry-run]           # 2-3 vendors talk a costly decision through: propose, find faults, judge
ccx verify <run_id> --ok 0 --reason wrong     # your verdict (unjudged runs get a probable one after 12 h)
ccx verify --sample 5                        # spot-check 5 probable verdicts of this week: ok / wrong
ccx handoff --from-transcript codex --to claude   # the old lead can't write it (quota out): built from its session file
                                                  # (by code; a format the code can't read goes to a routed sub-agent, --no-model to skip)
ccx undo <run_id> [--apply] [--wrong]   # put back what a write run changed (new files moved aside); --wrong: also judge it wrong
ccx ask "question"                    # quick read-only second opinion from the other agent, low effort
ccx archive [--apply] | --restore <run>   # archive finished sub-sessions (automatic once a result is final;
                                          # sessions.archive = after_run | hours | off)
ccx batch plan.json                   # independent tasks in parallel; parallel writers get separate worktrees
                                      # (with uncommitted changes they share the folder: commit first)
ccx q add "title" --brief "..." [--dep q1] [--check CMD] [--minutes 30] [--budget 1]   # the project's work queue
ccx q run | resume | tree | done q3 --ok 1   # run every ready piece in parallel; a piece too big splits itself
ccx q add --plan plan.json            # a whole plan: {"tasks": ...} or task-split's {"pieces": ...} (depends_on, files)
ccx q run --gate                      # dependents start only after `ccx q done <id> --ok 1` (default off); parallel
                                      # writers get worktrees (clean checkout only), and what waits on one waits for
                                      # your merge + verdict; a piece whose dependency failed is marked dep_blocked
ccx q ls [--long]                     # one line a piece: id, state, agent, seconds, $ (a worktree piece not landed
                                      # yet shows `unmerged` with `next: ccx q done qN --ok 1, then ccx q
                                      # accept qN`, or `next: ccx q accept qN` once judged); --long = the full JSON
ccx q accept q1 q2 | --all-ready [--check CMD] [--dry-run]   # land worktree pieces: merge in dependency order,
                                      # joint check after each merge, roll that merge back if it fails; refuses
                                      # unfinished / no_changes / unverified pieces and stops a piece at a conflict;
                                      # never pushes, never into main without --into-protected (the person's yes);
                                      # refuses a run you rejected (verify --ok 0); stops the batch when a rollback
                                      # fails or the check leaves edits in tracked files
ccx route --files 3 --coupling cross ... [--lead claude:opus:high --ctx-files log.txt]  # recommendation; + self vs delegate
ccx plan size --minutes 240 --rung codex:gpt-6.1-sol:medium # how many pieces for a big task (task-split)
ccx show <run_id> [--full]            # compact result by default
ccx show <run_id> --wait [SECONDS]    # block until it (and a review fix round) is done, default 540 s; then the
                                      # same result as ccx run, else status=running: call it again
ccx stats [--summary]                 # per agent × tier; --summary: spend first, then a labelled saving estimate, cache share
ccx report [--days 30] [--publish]    # offline one-file dashboard; --publish commits it to your private repo
ccx ui [--project DIR] [--no-open] [--export FILE]   # live page on 127.0.0.1 (never calls a model; writes only yes/no on suggested notes)
ccx demo [--no-open] [--keep] [--export FILE]       # the same page on made-up data in a temp folder: no account, offline
ccx config set ui.lang zh            # language of ccx ui and of the lines ccx writes into conversations
ccx config set defaults.tradeoff 0.3  # the save <-> fast knob: save / balanced / fast, or 0..1
ccx config set routing.mode off      # delegate no work: do it yourself; ccx ask / discuss / run --mode read (a
                                     # cross-vendor review), mem, board as before; run / batch / q run / q resume /
                                     # way refuse without --force (auto = as shipped)
ccx ab done <id> --ok 1               # close an A/B sample (the ~10% the lead does itself)
ccx send --list | --thread <id> "msg" # message a live Codex desktop / interactive session (Codex only: a Claude Code
                                      # session, terminal or desktop app, has no way in for an outside message;
                                      # follow up a Claude sub-agent with ccx resume <run_id>)
ccx say --to codex|claude|deepseek|all "msg"   # the board: open sessions in this project see it on their next turn
ccx board [--thread T] / ccx reply <id> "msg"  # read what is new for you / answer one (docs/board.md)
ccx peek codex|claude|deepseek        # shared work context: what another tool's open session here has been doing
ccx run --context auto|on|off ...     # attach the lead's recent work to a delegated task (auto: write tasks only)
ccx say --to codex --now "msg"   # also push it into the live Codex desktop conversation (Claude Code desktop: next turn only)
ccx config set board.github owner/repo   # optional: mirror the board to a PRIVATE repo of yours (ccx board --sync)
ccx skills find pdf table             # search the shared skill library before writing a new skill
ccx skills install [--replace] [--apply]   # link this repo's skills into the hub (dry run first), so `git pull` upgrades them
ccx improve add <skill> "concrete problem" --fix "what to change"   # log real problems only
ccx mem add "one sentence" --by claude    # shared memory
ccx mem delta --as codex                  # the other side's new lines (the hook runs this)
ccx mem compact                           # fold the journal into the snapshot
ccx mem search gradle signing             # best notes first (BM25); --all-words: only notes with every word
ccx mem add "..." --kind pitfall          # preference|constraint|fact|pitfall|event; `ccx mem kinds --list`
ccx mem compact --by project              # one short block per project in memory/scenes.md
ccx ctx init | add "…" | show             # project background file
ccx config set projects.roots "DIR;DIR" ; ccx projects scan   # catalog of your projects (hub, this machine only)
ccx projects | projects show <name>      # list them / one: path, summary, rules to read first, recent work
ccx where "the desk pet"                # which project a sentence is about: one clear pick, else the candidates and why
ccx run --project "the desk pet" "brief"   # delegate into it (its rules first; approval rules quoted, then --rules-ok)
ccx autonomy --project desk-pet            # how much the manager does without asking: L0 / L1 (default) / L2
ccx project init | status | compact ; ccx inbox "note" --file mail.eml   # project layer
ccx sync [--apply] [--only skills,memory,hooks,mcp] ; ccx doctor ; ccx uninstall [--apply]
```
