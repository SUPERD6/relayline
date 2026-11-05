# Offline tier and queue diagnosis — 2026-11-05

English · [中文](2026-11-05-tier-queue-diagnosis.zh.md)

## Protocol recorded before execution

Evidence level: **engineering check**, never a paid-model evaluation. Pin:
`945a8e590caf024c616cb5f65c9f227d8556774c`. No product or default changes.
The assigned worktree is isolated from the lead checkout. This protocol is recorded
before execution but is not a committed preregistration; the assignment forbids commits.
Consequently this diagnostic is not a formal evaluation under engineering standards §3.

Use fresh synthetic tasks, repository configuration/priors, empty learned state,
and actual `ccx.plan.resolve_role` / `_plan` decision functions. Compare workflow
policy separately from forced model selection. No real ledger or credentials.

Queue workload: ten independent, disjoint-file fake writes, each with 0.2 seconds
of artificial worker delay. Execute `ccx q add --plan`, `q run --max N --lanes 0`,
and `q accept --all-ready --check ...` as separate processes outside the repository.
Use fresh fixture repositories and isolated homes; disable fetch, quota probing,
benchmark refresh, independent review and automatic archival in fixtures only.
Run two rounds, widths 1/3/10 then 10/3/1, sequentially. No paid CLI.

Record queue CLI wall time, per-worker wall median and sum, worker interval union,
queue wall minus worker union (non-worker residual, **not pure scheduler CPU**),
serial fake CLI baseline, and acceptance/merge wall. Fixture setup is excluded.
Completion requires ten queue items done and ten generated files present after
acceptance; fixture verification is not hidden-test task correctness.
Report all failures; no speed pass threshold, default change or quality claim.
Real model quality, cash savings and optimal concurrency remain **Unknown**.

## Findings and limits

Do not pay to test all four labels first. Prioritize **save versus balanced as complete
workflows**, on cases where their ownership actually differs. Save and cheapest select
the same model chains on all eight synthetic cases; cheapest removes lead acceptance,
so it is not a new cheap model. Fast overlaps balanced on small/medium ownership and
can be deferred. No defaults should change from this diagnostic.

All results below are **engineering check**. This is Windows, Python 3.11.9, on the
pin above, 2026-11-05. Neither Linux/macOS performance nor real-model correctness,
cost or optimum width was tested. Two local rounds are signals, not statistical evidence.
Machine idleness was not established. Targeted pytest was started during the tail of
round 2 (widths 3/1 may overlap it); retain those rows, do not treat them as clean
controlled comparisons. The serial baseline was run once after the queue rounds.

### What the four names actually control

`--tier` accepts auto/T0..T4; it does **not** accept save/balanced/fast/cheapest.
Those four names belong to `--tradeoff` and `[policy.*]`.
The diagnostic calls `ccx.plan.resolve_role` (its ordinary path calls
`ccx.commands.common.resolve`) and then actual `ccx.plan._plan`, without a CLI/model
execution. No resolver or selection function is mocked. It also calls
`ccx.learn.tier_plan` against repository policy, bridged to the bundled routing skill.
Fresh isolated hubs keep task/usage history out; bundled priors still include historical
calibration, so these are not prior-free choices. Candidate agent is fixed to Codex;
cross-vendor choice under real quota/login conditions is **Unknown**.

The ownership table is a policy result, not proof that `q run` or `run` performs that
ownership automatically. `[policy].picked` ships empty. Policy normally informs a
proposal/lead; the forced resolver probe below delegates even when policy says self.
`_one` in the queue also passes `force=True`. An explicit `--tradeoff` does not grant
authorization. Configuring `policy.picked` authorizes one proposal's workflow, while
ordinary model picks still use `defaults.tradeoff` unless explicitly overridden.

| Synthetic task | Minutes / files / lead context | Band | save | balanced | fast | cheapest |
|---|---|---|---|---|---|---|
| tiny: Rename a local label | 5 / 1 / 0 | small | ccx2 | self | self | direct |
| medium: Add a cache helper | 15 / 2 / 0 | medium | ccx2 | self | self | direct |
| large-files: Update three independent adapters | 20 / 3 / 0 | large | ccx2 | ccx2 | self | direct |
| large-time: Implement a parser extension | 45 / 1 / 0 | large | ccx2 | ccx2 | self | direct |
| medium-context: Add a cache helper | 15 / 2 / 150000 | medium | ccx2 | ccx2 | self | direct |
| hard-large: Repair resume state machine | 60 / 4 / 0 | large | ccx2 | self | self | direct |
| unknown-size: Investigate a handler | null / 0 / 0 | small | ccx2 | self | self | direct |
| long-brief: 180 repetitions of parser, separated by spaces | 5 / 1 / 0 | large | ccx2 | ccx2 | self | direct |

`ccx2` means delegate plus lead acceptance; `direct` omits that acceptance and is marked
`may_be_wrong`; `self` means lead work. Hard-word detection takes priority over size,
then uncertain size, then the medium/large-context exception. Thus a 60-minute,
four-file resume task remains self under balanced. At exactly 150000 context tokens,
a medium task switches to ccx2. No minutes/files means uncertain even for long text.

### Forced model plans, separate from policy

Every cell is initial attempt → possible escalation, not evidence escalation ran.
L = `codex:gpt-6-luna`, S = `codex:gpt-6.1-sol`, A = `codex:gpt-6-astra`.
Inputs are those in the ownership table, `mode=write`, `force=True`, `no_ab=True`,
empty roles, one maximum escalation, quota routing/readiness disabled in fixture config.

| Synthetic task | b | save | balanced | fast | cheapest |
|---|---|---|---|---|---|
| tiny | 2.32 | L:low → L:high | L:low → L:high | S:medium → S:high | L:low → L:high |
| medium | 3.91 | S:medium → S:high | S:medium → S:high | S:high → S:xhigh | S:medium → S:high |
| large-files | 4.32 | S:medium → S:high | S:medium → S:high | S:high → S:xhigh | S:medium → S:high |
| large-time | 5.49 | S:high → S:xhigh | S:medium → S:high | A:xhigh → A:max | S:high → S:xhigh |
| medium-context | 3.91 | S:medium → S:high | S:medium → S:high | S:high → S:xhigh | S:medium → S:high |
| hard-large | 5.91 | S:high → S:xhigh | S:high → S:xhigh | A:xhigh → A:max | S:high → S:xhigh |
| unknown-size | Unknown | L:low → S:medium | L:low → S:medium | L:low → S:medium | L:low → S:medium |
| long-brief | 2.32 | L:low → L:high | L:low → L:high | S:medium → S:high | L:low → L:high |

Save/cheapest chains match **8/8**; save/balanced **7/8**; balanced/fast **1/8**.
This is model-chain equality, not quality equivalence. Balanced's 45-minute start is
actually weaker than save's here: its cost/time objective and threshold do not guarantee
a monotonic model ladder between presets. The unknown-size case falls back to keyword
routing, so all four chains match and no `b` is computed. Explicit `--tier T1` without
minutes/rubric produces L:low → S:medium under all four names (4/4); model tier wins.

### Basis for save and the thresholds

`config/tiers.toml:27–29` and the 2026-10-25 decision in `docs/DECISIONS.md` record the
historical reason for default save: balanced picked sonnet medium on five-minute work,
about 10× the recorded luna-low cost, while luna low was right on 55/63 attempts;
failed checks could then escalate. This is a source-recorded historical finding, not
a result reproduced here, and cannot establish today's default superiority.

Workflow size thresholds are provisional round-5-derived rules (`config/tiers.toml:49–65`):
large at ≥3 files, ≥45 minutes or ≥180 words; medium at ≥2 files, ≥15 minutes or ≥80 words;
take the largest signal. Chinese characters count as 1/2.5 word. Balanced's medium-context
cutoff is 150000 tokens; numeric knobs split at 0.34/0.67. These boundaries change balanced's
ownership, not save's always-ccx2 ownership. Statistical justification for the exact
boundaries is **Unknown**; this diagnostic does not optimize them.

Model thresholds in `skills/task-routing/data/priors.toml` are save τ=0.70/cascade,
balanced τ=0.80/cascade, fast τ=0.90/no cascade. Cheapest maps to save in `ccx/learn.py`.
τ is a prior-model probability cutoff, **not an observed success rate**. Cascading
minimizes money + quota shadow cost + time + failure risk among qualifying chains.
Without a cascade, routing selects a qualifying single attempt; `_plan` may still
provide an escalation ladder. Empirical calibration of τ=0.70 itself is **Unknown**.

Paid follow-up recommendation (not authorization): preregister **save vs balanced** on
new small/medium, hard/resume, large, and medium/high-context strata. Include lead,
worker, review, retries and merge/check effort; score hidden tests, cost per correct
task and unit median/cumulative wall. Retain failures and separate environment errors.
The large-task equal-policy stratum is a control. Do not spend on repeated identical
plans merely because labels differ; cheapest needs an acceptance-quality question,
and fast can wait until balanced's self strata establish a baseline. Do not choose
a winner or change defaults without that paid comparison.

## Queue timings

Six batches, ten attempted pieces each: **60/60** queue-done, **60/60** fixture files
present after acceptance, **60/60** accepted/check-passed entries, no interrupted or
failed diagnostic batch. Hidden-test correctness is **Unknown**. The check only asserts
at least one generated file at each merge; the driver separately asserts exactly ten
at the end. This tests plumbing, not semantic correctness. Fakes write unique names,
while declared ownership files are disjoint. No dependencies, conflicts, quota errors,
paid token accounting, warm lanes, background wakeups or real lead were exercised.

All `q` commands execute as child processes with fixture-repository cwd, not source-root
cwd. Fixtures are physically nested in the assigned workspace to respect write scope.
Only fixture Git repositories receive generated commits/merges; the source branch is
never switched or committed. Subprocess homes/config and all adapters are isolated;
network fetch/probes/refresh are disabled. `tests/fakes/fake_codex.py` supplies results
through a timing wrapper, with 0.2 s of artificial delay before each exec. Version/login
probes are excluded from worker intervals and remain in queue wall where incurred.

| Round | Width | Queue wall s | Worker median s | Worker sum s | Worker union s | Non-worker residual s | Accept wall s | Queue + accept s |
|---|---|---|---|---|---|---|---|---|
| 1 | 1 | 14.931 | 0.227 | 2.272 | 2.272 | 12.658 | 4.157 | 19.088 |
| 1 | 3 | 10.357 | 0.242 | 2.405 | 1.897 | 8.460 | 5.863 | 16.221 |
| 1 | 10 | 6.699 | 0.256 | 2.580 | 2.147 | 4.552 | 7.395 | 14.094 |
| 2 | 10 | 7.428 | 0.252 | 2.577 | 2.030 | 5.399 | 6.893 | 14.321 |
| 2 | 3 | 8.581 | 0.230 | 2.317 | 1.520 | 7.061 | 7.079 | 15.660 |
| 2 | 1 | 12.088 | 0.222 | 2.214 | 2.214 | 9.873 | 4.345 | 16.433 |

| Width | Median batch queue s (n=2) | Cumulative batch queue s | Median queue + accept s | Cumulative queue + accept s | Queue speed ratio vs width 1 |
|---|---|---|---|---|---|
| 1 | 13.509 | 27.019 | 17.760 | 35.521 | 1.00× |
| 3 | 9.469 | 18.939 | 15.940 | 31.881 | 1.43× |
| 10 | 7.064 | 14.128 | 14.208 | 28.415 | 1.91× |

One serial direct-fake baseline: ten processes, **3.719 s** total,
including process start, the artificial delay and fake execution; no ccx/Git/check cost.
It is not an equal-functionality alternative to the queue.

Worker median is the median of ten worker intervals per batch; worker sum is their
cumulative wall. Worker union counts overlapped time once. Non-worker residual = queue
CLI wall − worker union: exposed startup/routing/state/Git/scheduling time, **not** the
sum of internal overhead or pure scheduler CPU. Queue wall starts before process spawn
and ends after process exit. Acceptance wall includes per-item merged-tree checks,
verification and records; pure Git merge time is **Unknown**.

### Fixture-topology caveat

`ccx.workspace.worktree_repo` recognizes path components lexically. Because the assigned
workspace is itself under `.ccx-worktrees`, even the standalone fixture root is treated
as a ccx worktree. Width 1 therefore records/commits each item on its fixture's same
`diagnosis` branch; acceptance performs repeated same-branch/no-op merges plus checks.
Those are not ten independent branch merges. Wider runs use actual per-writer fixture
worktrees for all ten items. Therefore width-1 acceptance is a closure/check baseline,
and the end-to-end ratios confound width with Git topology. Ordinary-path behavior is
not remeasured, and its timing is **Unknown**. Keep this negative finding visible.

### Isolated scheduling probe

Supplemental protocol declared after the full-path runs, before this probe: execute the
real `_refill` dispatcher and durable queue with ten read items, replace only `_one` by
a callback that runs the timed fake CLI as a subprocess and updates doing/done. No
routing, Git, ledger, reviews or acceptance. Two rounds at widths 1/3/10, after targeted
tests finish. Time subprocess boundaries externally, so startup/pipe handling is
included in their union. Residual = dispatcher wall − union; it is exposed scheduling
and queue-state overhead, not total CPU nor costs overlapped behind running workers.
This is a component engineering check, not the product's end-to-end behavior.

| Round | Width | Dispatcher wall s | Subprocess interval union s | Exposed scheduling/state overhead s |
|---|---|---|---|---|
| 1 | 1 | 3.6978 | 3.4234 | 0.2744 |
| 1 | 3 | 1.6443 | 1.5143 | 0.1299 |
| 1 | 10 | 0.7251 | 0.6424 | 0.0826 |
| 2 | 1 | 3.6094 | 3.3429 | 0.2665 |
| 2 | 3 | 1.5107 | 1.4443 | 0.0663 |
| 2 | 10 | 0.5693 | 0.5064 | 0.0629 |

### Bottlenecks and bounded candidates (not implemented)

The full-path worker intervals are only about 0.22–0.26 s per piece, but much of queue
wall lies outside them. At width 10 the worker union stays around two seconds rather
than collapsing to one worker duration. Serialized worktree preparation and per-item
Git/state work are plausible contributors (`workspace._worktree_lock`, `_place`,
`_tree_fields`/`lanes.commit_block`); their individual causal shares are **Unknown**.
The isolated probe bounds exposed dispatcher overhead for this tiny queue; it cannot
be used to subtract a clean scheduler number from the full-path timings.

Serial acceptance is an explicit floor: `ccx.accept` merges/checks/records one item at
a time. `scripts/eval/batch.py` measures a real lead, acceptance, hidden tests and
wakeups, and `--jobs` there means concurrent **evaluation units**, not queue width.
Its `cmd_run` is deliberately not invoked: it can run paid lead/canary CLIs. Here the
real `q run --max` controls only worker width; turning batch `--jobs` to 10 would change
a different layer and violate a single-evaluation-at-a-time paid protocol.

| Candidate | Risk / required guard | Decision here |
|---|---|---|
| Add opt-in per-stage monotonic timing (resolve, queue replay/lock wait, worktree prepare, worker, commit, merge, check) | Low: additive records only, disabled by default; check JSON compatibility and instrumentation cost | Best first diagnostic change; not implemented |
| Document/validate fixture roots beneath `.ccx-worktrees` | Low for documentation; changing lexical ownership detection needs dedicated nested-repo regression tests | Report limitation; do not silently patch semantics |
| Reuse a loaded queue snapshot inside one bounded operation | Requires lock/gate/dependency/backpressure concurrency tests; cross-process changes cannot be cached away | Profile first; not yet a low-risk proven speed fix |
| Reduce duplicate Git status/clean probes within one refill | Must revalidate a writer's base and preserve dirty-tree handling | Candidate after timing evidence |
| Skip redundant Git merge plumbing for a branch already landed | Preserve each item's check, verdict, ledger, dependency release and rollback boundaries | Candidate after dedicated acceptance tests |
| Batch ten branches then check once / remove gates / enlarge default width | Changes failure isolation or workload pressure | Do not do from this evidence |

Safe operational action requires no code: keep existing width 3 as an unproven default,
bound concurrent writers by actually independent work and acceptance capacity, and use
the already-existing multi-item acceptance command. These are not claims of optimality.

## Reproduction and verification

The driver below uses only stdlib and repository code/fakes. Extract it to
`.diagnosis-local/diagnose.py` in a fresh assigned worktree at the pin; run
`python -X utf8 .diagnosis-local/diagnose.py`. Do not reuse an existing fixture folder.
The supplemental driver is extracted alongside it and run **after** tests/end-to-end
timings. Machine load, filesystem/antivirus and randomly named files make wall times
non-deterministic; completion assertions are deterministic, not timing thresholds.
Driver outputs/raw results are retained locally in the ignored
`.ccx/tier-queue-diagnosis-20261105/` folder and must not be published verbatim:
they contain local paths. The sanitized numeric tables above are the report artifact.

Commands executed: `q add --plan`, `q run --from claude --max 1|3|10 --lanes 0`,
`q accept --all-ready --check "<python> check.py"` (fresh fixture each time),
the real resolver/planner probes, standalone fake baseline, and the isolated dispatcher
probe. Related tests: `python -m pytest -q tests/test_task_routing.py tests/test_queue_pipeline.py
tests/test_queue_accept.py -k 'tier or parallel_writers or pieces_sharing or accept'`:
**19 passed, 52 deselected**, process exit 0 (123.17 s). The full suite was not run,
as assigned. `python scripts/collect_changes.py --check`: 13 notes and 9 decision
notes valid, exit 0. No product command,
option, JSON meaning, exit code, verdict rule, default or configuration schema changed.

### End-to-end diagnostic driver

```python
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
import statistics

ROOT = Path(__file__).resolve().parent.parent
BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

def put(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8', newline='') as f:
        f.write(text)

def environment(folder):
    env = dict(os.environ)
    for k in list(env):
        if k.startswith(('CCX_', 'CODEX_', 'CLAUDE_', 'FAKE_', 'TASK_ROUTING_', 'TASK_SPLIT_')) or k.endswith(('_API_KEY', '_AUTH_TOKEN', '_BASE_URL')):
            env.pop(k, None)
    for k, sub in [('CCX_HUB', 'hub'), ('CODEX_HOME', 'codex-home'), ('CLAUDE_CONFIG_DIR', 'claude-home'), ('DSH_HOME', 'dsh-home')]:
        p = folder / sub
        p.mkdir(parents=True, exist_ok=True)
        env[k] = str(p)
    env.update(CCX_CONFIG=str(folder / 'no-user-config.toml'), CCX_NO_LOCATE='1',
               CCX_NO_BENCH_REFRESH='1', CCX_NO_QUOTA_PROBE='1', CCX_NO_AUTO_ARCHIVE='1',
               CCX_AB_RATE='0', CCX_CODEX_BIN=str(BASE / 'fake_timed.py'),
               CCX_CLAUDE_BIN=str(ROOT / 'tests/fakes/fake_claude.py'),
               CCX_GEMINI_BIN=str(ROOT / 'tests/fakes/fake_gemini.py'),
               CCX_DSH_BIN=str(ROOT / 'tests/fakes/fake_dsh.py'), PYTHONUTF8='1',
               DIAG_TIMINGS=str(folder / 'timings'), FAKE_TOUCH='1')
    Path(env['DIAG_TIMINGS']).mkdir(exist_ok=True)
    put(folder / 'hub/ccx/tiers.toml', '[worktree]\nlocation = "inside"\nfetch = false\n[routing]\nrequire_ready = false\n[quota]\nrouting = "off"\n[review]\nmode = "off"\n[shared_context]\nmode = "off"\n')
    return env

def command(argv, cwd, env, label):
    start = time.perf_counter()
    r = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True, encoding='utf-8', timeout=180)
    wall = time.perf_counter() - start
    put(Path(env['DIAG_TIMINGS']).parent / (label + '.json'), json.dumps({'code': r.returncode, 'wall': wall, 'stdout': r.stdout, 'stderr': r.stderr}, indent=2))
    if r.returncode:
        raise RuntimeError(f'{label}: code {r.returncode}: {r.stdout[-1500:]} {r.stderr[-1000:]}')
    return r.stdout, wall

def union(intervals):
    end = None
    total = 0
    for a,b in sorted(intervals):
        total += max(0, b - max(a, end if end is not None else a))
        end = max(b, end if end is not None else b)
    return total

def main():
    put(BASE / 'fake_timed.py', '''import json, os, pathlib, runpy, sys, time
start = time.perf_counter()
argv = sys.argv[1:]
worker = argv[:1] == ["exec"]
if worker:
    time.sleep(0.2)
fake = pathlib.Path(__file__).resolve().parent.parent / "tests/fakes/fake_codex.py"
sys.path.insert(0, str(fake.parent))
try:
    runpy.run_path(str(fake), run_name="__main__")
finally:
    if worker:
        p = pathlib.Path(os.environ["DIAG_TIMINGS"]) / (str(os.getpid()) + ".json")
        p.write_text(json.dumps([start, time.perf_counter()]), encoding="utf-8")
''')
    route_env = environment(BASE / 'routing')
    os.environ.update(route_env)
    from ccx.config import Paths, load_config
    from ccx.plan import resolve_role, _plan
    from ccx.delegate import Request
    from ccx import learn
    p = Paths(Path(route_env['CCX_HUB']))
    cfg = load_config(p)
    tasks = [('tiny', 'Rename a local label', 5, 1, 0),
             ('medium', 'Add a cache helper', 15, 2, 0),
             ('large-files', 'Update three independent adapters', 20, 3, 0),
             ('large-time', 'Implement a parser extension', 45, 1, 0),
             ('medium-context', 'Add a cache helper', 15, 2, 150000),
             ('hard-large', 'Repair resume state machine', 60, 4, 0),
             ('unknown-size', 'Investigate a handler', None, 0, 0),
             ('long-brief', ' '.join(['parser'] * 180), 5, 1, 0)]
    routes = []
    for name, brief, minutes, files, ctx in tasks:
        for tradeoff in ['save', 'balanced', 'fast', 'cheapest']:
            policy = learn.tier_plan(p, tradeoff, brief, minutes, files, ctx, cfg['policy'])
            spec = dict(brief=brief, minutes=minutes, files=files, lead_ctx=ctx, to='codex', mode='write', tradeoff=tradeoff, force=True, no_ab=True, cwd=str(BASE / 'routing'))
            kw, route = resolve_role(spec, 'claude', p, cfg)
            rungs = _plan(Request(brief=brief, mode='write', **kw), p, cfg, 1) if kw else []
            routes.append(dict(task=name, tradeoff=tradeoff, policy=policy, route=route, rungs=rungs))
    # Explicit T1 checks show that tradeoff is not the T0..T4 ladder.
    explicit = []
    for tradeoff in ['save', 'balanced', 'fast', 'cheapest']:
        kw, route = resolve_role(dict(brief='Add a cache helper', tier='T1', to='codex', tradeoff=tradeoff, force=True), 'claude', p, cfg)
        explicit.append(dict(tradeoff=tradeoff, rungs=_plan(Request(brief='Add a cache helper', **kw), p, cfg, 1)))
    out = dict(pin=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(), python=platform.python_version(), system=platform.system(), routes=routes, explicit=explicit, queue=[])
    put(BASE / 'results.json', json.dumps(out, indent=2))
    for rep, widths in enumerate([[1,3,10],[10,3,1]], 1):
        for width in widths:
            folder = BASE / f'r{rep}-w{width}'
            env = environment(folder)
            work = folder / 'work'
            work.mkdir()
            put(work / '.gitignore', '.ccx/\n')
            put(work / 'check.py', 'from pathlib import Path\nassert len(list(Path.cwd().glob("fake-*.txt"))) >= 1\nprint("fixture files checked")\n')
            git = ['git','-c','user.name=fixture','-c','user.email=fixture@example.invalid']
            command(git + ['init','-q','-b','diagnosis'], work, env, 'init')
            command(git + ['add','.gitignore','check.py'],work,env,'git-add')
            command(git + ['commit','-qm','fixture start'],work,env,'git-fixture')
            # ccx auto-commits/merges fixtures only, never the actual source checkout.
            env.update(GIT_AUTHOR_NAME='fixture',GIT_AUTHOR_EMAIL='fixture@example.invalid',GIT_COMMITTER_NAME='fixture',GIT_COMMITTER_EMAIL='fixture@example.invalid')
            plan = {'tasks':[dict(id=f't{i}', brief=f'Write independent fixture {i}', title=f'fixture {i}', minutes=5, mode='write', to='codex', files=[f'piece{i}.txt']) for i in range(10)]}
            put(folder / 'plan.json', json.dumps(plan))
            cli = [sys.executable, str(ROOT / 'ccx.py')]
            command(cli + ['q','add','--plan',str(folder / 'plan.json')],work,env,'add-plan')
            stdout, wall = command(cli + ['q','run','--from','claude','--max',str(width),'--lanes','0'],work,env,'queue-run')
            result = json.loads(stdout)
            timings = [json.loads(f.read_text()) for f in Path(env['DIAG_TIMINGS']).glob('*.json')]
            assert len(result['results']) == 10 and all(x.get('status') == 'done' for x in result['results']), result
            assert len(timings) == 10, len(timings)
            stdout, merge = command(cli + ['q','accept','--all-ready','--check',f'"{sys.executable}" check.py'],work,env,'accept')
            count = len(list(work.glob('fake-*.txt')))
            assert count == 10, count
            durations = [b-a for a,b in timings]
            row = dict(rep=rep,width=width,queue_wall=wall,worker_median=statistics.median(durations),worker_sum=sum(durations),worker_union=union(timings),nonworker_residual=wall-union(timings),accept_wall=merge,files=count,accept=json.loads(stdout))
            out['queue'].append(row)
            put(BASE / 'results.json',json.dumps(out,indent=2))
            print(json.dumps({k:v for k,v in row.items() if k!='accept'}), flush=True)
    folder = BASE / 'serial-baseline'
    env = environment(folder)
    total = 0
    for i in range(10):
        # fake CLI expects a prompt over stdin; communicate through subprocess.run.
        begin = time.perf_counter()
        r = subprocess.run([sys.executable,str(BASE/'fake_timed.py'),'exec','-m','gpt-6-luna'],cwd=folder,env=env,input='fixture',capture_output=True,text=True,encoding='utf-8',timeout=30)
        assert r.returncode == 0, r.stderr
        total += time.perf_counter()-begin
    out['serial_fake_wall'] = total
    put(BASE / 'results.json',json.dumps(out,indent=2))
    print('serial_fake_wall',total,flush=True)

if __name__ == '__main__':
    main()
```

### Supplemental dispatcher driver

```python
"""Supplemental dispatcher isolation; run only after full-path timings and tests end."""
from diagnose import BASE, ROOT, environment, put, union
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import json
import os
import subprocess
import sys
import time
from ccx import queue
from ccx.commands import workqueue

data = json.loads((BASE/'results.json').read_text())
data['dispatcher_probe'] = []
for rep in (1,2):
    for width in (1,3,10):
        folder = BASE/f'probe-{rep}-{width}'
        env = environment(folder)
        env.pop('FAKE_TOUCH',None)
        root = folder/'work'
        root.mkdir()
        for i in range(10):
            queue.add(root,str(i),'Read fixture',mode='read',files=[f'p{i}.txt'])
        intervals = []
        def one(it, root, caller, p, cfg, warm=None, got=None, **kw):
            queue.update(root,it['id'],status='doing')
            start = time.perf_counter()
            r = subprocess.run([sys.executable,str(BASE/'fake_timed.py'),'exec','-m','gpt-6-luna'],cwd=root,env=env,input='fixture',capture_output=True,text=True,encoding='utf-8',timeout=30)
            end = time.perf_counter()
            assert r.returncode == 0,r.stderr
            intervals.append((start,end))
            queue.update(root,it['id'],status='done')
            return {'id':it['id'],'status':'done'}
        done=[]
        with patch.object(workqueue,'_one',one):
            start=time.perf_counter()
            stop=workqueue._refill(SimpleNamespace(once=False,gate=False),root,'claude',None,{},width,done)
            wall=time.perf_counter()-start
        assert not stop and len(done)==10
        row=dict(rep=rep,width=width,wall=wall,subprocess_union=union(intervals),exposed_dispatch=wall-union(intervals),completed=len(done))
        data['dispatcher_probe'].append(row)
        print(json.dumps(row),flush=True)
put(BASE/'results.json',json.dumps(data,indent=2))
```
