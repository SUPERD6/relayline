# Engineering standards

English · [中文](engineering-standards.zh.md)

These are long-term rules for changes, evaluations, receipts and public claims. For the contribution workflow,
see [CONTRIBUTING](../CONTRIBUTING.md); for project rules, see [AGENTS](../AGENTS.md). The current work is in the
[optimization plan](research/2026-11-04-optimization-plan.md). This document changes no code or defaults.

## 1. Evidence and verdicts

Use these labels in documents, PRs and receipt explanations. Evidence level and verdict are separate fields.

| Evidence level | Required evidence | What it supports |
|---|---|---|
| **measured** | Real CLI runs, with data files and a report | The observed result within the reported conditions |
| **engineering check** | Tests, fake CLIs or replay | Only that the code works as designed |
| **not run** | No execution | No result claim |

Use only **Pass / Fail / Unknown** for verdicts against stated criteria. Missing or insufficient evidence is
Unknown. When saying “done”, “fixed” or “effective”, name the evidence level and its scope. These reporting
labels do not rename existing JSON values, receipt kinds or exit codes.

## 2. Metric definitions

Use these definitions in evaluations. Record a decision before changing them; see [decision notes](../changes/README.md).

| Metric | Definition and reporting rule |
|---|---|
| Correct | All hidden tests pass. Tests written by the sub-agent itself do not establish correctness. |
| Completion rate | Completed units / attempted units. State the completion criterion before running. Report separately from correctness. |
| Correctness rate | Correct units / attempted units. Report the numerator and denominator, not just completed units. |
| Cost per success | Total spend on all attempts, including failures, / correct units. Include lead, sub-agent, review and repair spend. Label money as API-equivalent USD. If no unit is correct, report the spend and no finite cost per success. |
| Wall time | Median time from each unit's start to its end; also report cumulative wall time. Human waiting time may be separate, but cannot replace this metric. |
| Receipt false positive | An ordinary `ok` receipt whose hidden tests fail. Report failures / ordinary `ok` receipts. Count `ok_self_checked` separately. For 0/n, give the 95% upper bound and its method; n = 0 is Unknown. |
| Review catch rate | Actual errors blocked by review / all actual errors. |
| Review false-block rate | Actually correct units blocked by review / all actually correct units. |
| Environment cleanliness | If any row has `env_clean=false`, report both all rows and clean rows, with their denominators. |

Do not silently turn missing results or zero denominators into zero error. Preserve Unknown.

## 3. Evaluation rules

- Commit a preregistration before running. Pin the code and specify tasks, groups, rounds, metrics, thresholds,
  decision order, budget cap and interruption handling. Do not change thresholds after starting.
- Separate development and final sets. Tune only on development tasks. Do not tune on the final set. Mark any
  previously used task; it cannot count as unseen.
- Compare the same version under the same conditions. Label older results “historical”; they are not a
  current-version control.
- Change one main factor at a time. If factors cannot be isolated, say so.
- Evaluate in an independent clone, on an idle machine, one evaluation at a time.
- Retain and account for failures and interruptions, including their spend.
- Run at least two rounds before quoting public numbers. One round is only a signal.
- Allow at most two improvement rounds per item. If both miss the threshold, keep it off by default, or enable
  it only in scenarios with demonstrated benefit. Publish the negative results.

## 4. Feature rules

- New behavior starts off by default. Enable it by default only after its thresholds pass. A default change needs
  a decision linked to its report.
- Mark features supported only by engineering checks as experimental.
- Preserve commands and options as required by [AGENTS](../AGENTS.md). Stop investing in abandoned features:
  keep them off and experimental; spend no more on them.
- Preserve existing JSON field meanings, exit codes and verdict rules. Only add fields. Any change to those
  contracts needs a prior decision.

## 5. Code rules

These supplement [CONTRIBUTING](../CONTRIBUTING.md), rather than replacing its workflow.

- Use only the standard library. Support Python 3.11+ on Windows, Linux and macOS.
- Prefer small modules for new logic. Do not keep growing `ccx/delegate.py` or `ccx/ui.py`. Keep one theme per PR.
- Update `ccx/config.py`, `config/tiers.toml` and the documentation together when changing configuration keys.
- Classify environment errors separately from task failures. Environment errors do not trigger a tier upgrade
  and do not count as the task being wrong. Keep them in the all-row record and cost accounting.
- A bug fix needs a regression test that fails without it. Use fake CLIs; tests must not depend on the clock,
  execution order or machine environment.
- Keep credentials, personal paths and personal data out of logs and reports.

## 6. Delivery rules

- Save test output to a file. Inspect the summary line and the test process's actual exit code, not the exit
  code of a later pipeline command.
- A PR body says what changed, why, evidence level, unverified scope and what was preserved.
- The coordinating reviewer checks the diff and raw results, not only a title or self-assessment.
- After merging, check main's CI and clean up merged branches and worktrees. Follow the file rules below.

## 7. Public claims

- Every number carries sample size, version, date, limits and a report link.
- Without a same-version comparison, do not claim faster, cheaper or more accurate behavior.
- Publish negative results alongside positive ones.

## 8. File and context hygiene

Document what each session loads automatically. The baseline budget is below; any client-specific extra
startup input must also be listed. These are maintenance limits, not a claim that code enforces truncation.

| File | Reading rule and limit |
|---|---|
| `AGENTS.md` | Project instructions loaded by the agent client; at most 8 KB. `CLAUDE.md` points to it. |
| `docs/STATUS*.md` | One page for each current EN/ZH status file; do not read proactively. Read current status only when needed to choose work; read archives only for relevant history. |
| `.ccx/handoff.md` | Previous-session notes, when present and relevant to resuming work; at most 8 KB. Do not load for unrelated work. |

If a limit is exceeded, move old content to an archive and keep only what the next step needs. A file on disk
does not enter context unless it is read.

- Handoffs contain only current state, next steps and unverified items. Archive old history; do not append forever.
- Do not track regenerable artifacts or local machine data. Explain any single binary image over 300 KB.
- Treat local data by type: regenerable data may be cleaned; archive evaluation results and reports first.
  Never package or send directories containing credentials.
- Inspect contents before cleanup. Move items to an archive first, recording source and reason. The maintainer
  personally decides permanent deletion.
- Migrate unused configuration keys or warn about them in `ccx doctor`; do not silently retain them.
- Check this hygiene at the end of a large project or at release. Record the result in the handoff.

## 9. Stop and ask

Stop and ask the maintainer before exceeding budget, requiring credentials, publishing externally, changing
GitHub settings, rewriting history or doing anything irreversible. Also stop for a genuinely ambiguous decision
rule. Do not choose the interpretation that favors the result.
