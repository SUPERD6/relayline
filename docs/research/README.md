# Research reports

English · [中文](README.zh.md) · back to [Measured](../measured.md)

Every report keeps its limits and unfavourable results; read the report before quoting a number. Plans were written
before their runs. Round 5 and everything after it use a development set (tasks also used while tuning ccx): signal,
not proof; the exception is the hold-out run hc1 (2026-10-29), on tasks not used while building ccx. Scrubbed data is in [data/](data/).

| Date | Question | Result in one line | Main limit | Report |
|---|---|---|---|---|
| 2026-10-23 | How should token savings be measured? | One unit (API-equivalent USD); headline metric is cost per success against the lead doing it itself | Literature gains are from single-call QA; expect much smaller for multi-turn coding agents | [token-cost quantification](2026-10-23-token-cost-quantification.md) |
| 2026-10-24 | What does the lead itself cost, and does delegating small tasks save it anything? | Only if the lead trusts ccx's check (one request fewer per task); a lead that re-checks pays more | Tasks too small and easy; haiku 8 pairs, sonnet 6; lead not a real long session | [H11 / E8 / F9 measurements](2026-10-24-h11-e8-f9-measurements.md) |
| 2026-10-24 | Do the seven cores work on real CLIs (round 1, Claude Code + Codex)? | Leading each other and project memory work; no evidence yet that working together is better | Small tasks, core n = 7; headless ~12k-context lead; cheapest sub-agent only | [seven cores A/B](2026-10-24-seven-cores-ab.md) ([plan](2026-10-24-seven-cores-plan.md)) |
| 2026-10-24 | How does ccx live with the official plugin, and what similar projects exist? | Overlap only on the Claude → Codex side; no other project found that routes by odds and cost with a ledger | No plugin installed; GitHub figures read on 2026-10-24 only; coexistence untested | [landscape](landscape.md) |
| 2026-10-25 | Round 2: does dividing the work beat one model, and is it cheaper? | Review and dividing point the right way, not significant; the cheap model is near the ceiling on clear tasks | Clear-brief medium tasks only; 4-B n = 14 per arm, one task separates the arms | [round 2](2026-10-25-seven-cores-r2.md) ([plan](2026-10-25-seven-cores-r2-plan.md)) |
| 2026-10-25 | Does the lead's recent work, attached to a brief, help the sub-agent? | First try right 36/36 vs 7/36, 63 % less spend; the feature's best case by design | Fake lead sessions (written files, not a real lead); short clean chats; one model each, 3 repetitions | [shared-context A/B](2026-10-25-shared-context-ab.md) |
| 2026-10-25 | Does the board work with the real Codex and DeepSeek CLIs? | Yes: messages, replies and per-turn delivery right; one wording bug found and fixed | Codex desktop hook, `ccx say --now` into live Codex and the dsh desktop rule not verified | [board acceptance](2026-10-25-board-acceptance.md) |
| 2026-10-25 | Can three vendors talk a decision through (`ccx discuss`)? | Works, n = 1: right answer, $0.016, 85 s | n = 1; Gemini CLI, dsh, Kimi, GLM, Qwen, OpenRouter not run (not installed or no keys) | [three-vendor discuss](2026-10-25-discuss-three-vendors.md) |
| 2026-10-25 | DeepSeek as lead and as `dsh` sub-agent | Works as a sub-agent; as a lead only with full access or through Claude Code | Codex-on-DeepSeek lead, dsh desktop lead, Gemini, Kimi, GLM, Qwen, macOS/Linux not run | [DeepSeek lead](2026-10-25-deepseek-lead.md) |
| 2026-10-25 | Could Gemini CLI be a lead? | Not built and not run; what it would take | Not built and not run; Gemini CLI not installed on the writing machine | [Gemini lead](2026-10-25-gemini-lead.md) |
| 2026-10-25 | Round 3: ccx versus Claude Code's built-in sub-agent on harder tasks | All arms 20/20; doing it yourself is cheapest; ccx cuts the lead's tokens but is slower | 10 tasks, 60 units, all right, so success rates untestable; one lead model (sonnet medium) | [round 3](2026-10-25-r3.md) ([plan](2026-10-25-r3-plan.md)) |
| 2026-10-25 | Do warm lanes (continuing a session per piece) save? | About 40 % cheaper than a fresh session per piece, but slower and still dearer than one run; stays off | n = 2, descriptive only; one task kind (ten small modules); Codex luna low only | [warm lanes](2026-10-25-warm-lanes.md) |
| 2026-10-26 | Round 4: where do cheap models fail; does delegating save in a long lead session? | Hardly fail (ceiling); in a long session doing it yourself is cheapest | Long session: 5 tasks once each; tasks too easy to separate models (ceiling) | [round 4](2026-10-26-r4.md) |
| 2026-10-26 | Round 5: large real tasks, does delegating save, is it more right? | First run: no; after the fixes ccx2 39/40 over r5e+r5f (76/80 over r5e–r5h), $0.116–0.135 per success (dev set) | Dev set: all tasks from this repo; n = 20 per run; builtin's right varied 17–19 between days | [round 5](2026-10-26-r5.md) ([plan](2026-10-26-r5-plan.md)) |
| 2026-10-27 | Batch / pipeline: several changes at once, scored on the merged tree | Plan only, nothing measured yet | Plan only, nothing measured | [batch plan](2026-10-27-batch-plan.md) |
| 2026-10-28 | Offline experiments C1–C6 on the round-5 records | namecheck 0 false alarms; most other candidates dropped or still need paid runs | Development set only (10 tuned tasks); C2, C4 not run, B2 not done here (replayed later: DECISIONS 2026-10-28) | [offline experiments](offline-experiments.md) |
| 2026-10-28 | Did ccx keep its own obligations in round 5 (r5e–r5h)? | Right answers hid harness problems: 76/76 right ccx2 units failed at least one criterion | Dev data (r5e–r5h, n = 80 ccx2); its own criteria; mechanism chains are hypotheses | [harness audit](2026-10-28-harness-audit.md) |
| 2026-10-29 | Hold-out confirmation hc1: on 10 tasks not used while building ccx, is ccx no worse and cheaper? | Not seen less right (29/30, 29/30, 27/28); $0.063 per success, about 30 % below self and 39 % below the built-in sub-agent's default usage; about 3× self's wall time; external tasks only: 15 % / 42 % | builtin is its default usage; this repo's 5 tasks may leak answers; 10 tasks; one lead model | [hc1 hold-out](2026-10-29-hc1-holdout.md) |
| 2026-10-30 | B3: do the lean sub-agent switches (Codex memories off, clean sub-agent, fewer Codex tools) cost right answers, measured against the person's daily setup? | Plan only, nothing measured yet; the switches ship off | Plan only, nothing measured | [B3 lean switches plan](2026-10-30-b3-lean-switches-plan.md) |
| 2026-10-30 | Polyglot slice: on 30 outside exercises with a difficulty spread (aider's polyglot benchmark, Python), does routing show? | Plan and harness only, nothing measured; outside benchmark, 30 exercises, chosen without looking at solutions, Exercism MIT | Plan only; Python only; the difficulty spread is assumed, not measured | [polyglot slice plan](2026-10-30-polyglot-slice-plan.md) |
| 2026-10-31 | B3 result: do the three lean switches cost right answers or save sub-agent tokens? | All keep their defaults: Codex memories off Unknown, clean Fail (3 pairs lost), fewer tools Fail under the rule (undecided post hoc); medians fell, paired totals show no reliable saving | Only the hold-out half (30 pairs per arm, not the registered 50) is clean; one shared baseline | [B3 lean switches result](2026-10-31-b3-lean-switches.md) |
| 2026-10-31 | External benchmark pg1: on 30 polyglot Python exercises, does handing work to the cheapest tier pay? | Not through the lead: right 12/30 delegated (ccx2) vs 25/30 self (13:0 discordant, p = 2.4e-4, all 30), 3.1× cost per success (95 % CI 2.2–5.4), 82 % of it the lead's side; with no lead (direct) 0.57× self per success but right 9/30; 14 of 18 failures guessed the hidden tests' interface wrong; the sub-agent's own tests (the only check) passed in all 18; the tier never climbed | One round; Python only, all one-file exercises; public Exercism tests a model may have seen; one sub-agent tier, one lead model; failure coding by one person | [polyglot pg1](2026-10-31-polyglot-pg1.md) |
| 2026-10-31 | How often does ccx's receipt say right when the hidden tests fail? | After #158, 8 of 209 receipts that said right were wrong (3.8 %, above the 2 % bar; before #158, 6.7 %); all 8 a check that passed without testing what the hidden test asked; 47 of 51 receipts that said wrong were right | Hidden tests are never seen by the check; one lead model; units not independent; before/after not controlled | [verdict audit](2026-10-31-verdict-audit.md) |
| 2026-10-31 | What does the real hub's ledger show for one week of use? | 283 runs, $8.17, but only 5 (3–5 tasks) were real work outside ccx's own tests; the ledger has no lead tokens for delegated runs, so the saving is Unknown | Real use, not controlled; one person, the week ccx was built; groups told from labels | [dogfood](2026-10-31-dogfood.md) |

## Completion, correctness and all-started cost / 完成、正确与全部启动成本

The R5 and P13 summaries, and each experiment in the B3-arms summary, add `completion_and_cost` before the old
eligibility/pair filters. Its `clean`, `unclean` and `env_unknown` strata use `env_clean is True`, `is False` and
missing/null respectively; rates never mix these strata, even with `--include-unclean`. `by_arm` repeats the same
breakdown (R5 keeps its existing model/isolation arm names). `batch_cost` alone totals started units and known
spend across all environments; it has no pooled correctness rate. The input is the selected results/tag/experiment,
not the planned schedule. One JSONL row is one started **evaluation unit attempt**, including a recorded setup
failure; child runs, retries and reviews are already inside its cost rollup and are not added again.

R5、P13 和 B3-arms 每个实验的汇总都新增 `completion_and_cost`，在旧筛选与配对之前读取结果行。
`clean`、`unclean`、`env_unknown` 分别是环境干净、污染、缺失或 null，比例始终分开，
`--include-unclean` 也不合并。`by_arm` 按 arm 重复分组；`batch_cost` 只跨环境列总启动数、已知支出和缺费数，
不混算正确率。统计范围是已选文件、tag、实验的结果行，不含尚未启动的计划任务。每行是一次已启动的
**评测单元尝试**，包括记录下来的准备失败；其费用已包含子运行、重试和复审，不重复相加。

| New field / 新列 | Definition and source / 定义与来源 |
|---|---|
| `started` | Number of input rows in the stratum, before survivor/pair filtering. / 组内原始结果行数，包含失败和 Unknown。 |
| `valid_completion` | Count of normal terminal receipts: R5 `subtype=success` (from the Claude result event) or `status=done` (direct ccx receipt); P13 all saved `worker_results` must terminate normally; B3 m3/m5 use the saved receipt `status`. Explicit errors, timeout/quota/env stops, nonterminal failure statuses, failure kinds, and rc outside 0/2 invalidate delivery. rc 2 can accompany a completed result whose check failed. Hidden `ok`, `protocol_ok`, a run id or rc alone proves no delivery. / 正常结果终态计数；错误、超时、额度或环境停止不算完成；判对与协议标志均不替代交付证据。 |
| `right` | R5/P13: hidden-test `ok is True` (R5 error-path `ok=False` is not a test verdict). B3 m3/m5: `right=1`; m4: `right == n_pieces > 0`, one whole-unit success, retaining the old piece count separately. / 隐藏测试通过数；m4 所有小块通过才算一个单元成功，旧小块总分保留。 |
| `unknown` | Rows with unknown completion **or** unknown hidden-test outcome, counted once. `completion_unknown` and `right_unknown` expose the two causes; counts can overlap `right`. / 完成或判对信息未知的行数，交集只计一次；两个细分计数说明原因，可能与已知判对数重叠。 |
| `valid_over_started`, `right_over_started` | `valid_completion / started`, `right / started`; zero denominator is JSON null (Unknown). / 分母包含所有已启动行；零分母为 null。 |
| `right_over_valid` | `right / valid_completion`, null if no valid completions or any recorded right lacks valid completion evidence. `right_valid_completion` reports the intersection so legacy unknown completions cannot silently enter this denominator. / 没有有效完成，或某次判对缺少有效完成证据时为 null；交集另列，避免错误配分母。 |
| `spend_all_started` | Sum known `usd` once per row, including failures/Unknowns. If absent, recover disjoint `lead_usd + ccx_usd`; if ccx total is absent, P13 can use `lead_usd + discuss_usd + worker_usd`. Never add a total to its own components, `review_usd`, or child tokens/cost again. / 所有启动行的已知总支出；总额优先，缺失时仅恢复互不重叠的已知分项。 |
| `cost_per_success_all` | `spend_all_started / right`; null with no recorded successes or no known spend. Missing spend remains missing: a partial known subtotal is not the complete bill. / 已知支出除以判对数；无成功或无已知费用为 null；存在缺费时不代表完整成本。 |
| `missing_cost_n` | Unit attempts lacking a complete finite nonnegative cost; null/missing, nonfinite, negative and boolean values are unknown, genuine recorded zero is known. R5's error-path zero without billing components is an unproven default, hence unknown. All-unknown nonempty spend is null; empty spend is zero. / 完整费用缺失的单元尝试数；未知不补零；旧 R5 异常路径缺计费依据的默认零也记未知。 |

Implementation/source map: [`common.py`](../../scripts/eval/common.py) (`valid_completion`, `_unit_spend`,
`completion_cost_summary`); R5 `lead_unit`, `direct_unit`, `run_unit`, `summarize`; P13 `hub_stats`, `run_unit`,
`summarize`; B3 `run_stats`, `m3_unit`, `m5_unit`, `_unit_right`, `rule`. Older m4 rows have piece scores/run ids
but no piece terminal receipts, so completion is Unknown; no output is inferred from hidden-test success.
Legacy unit rollups cannot reveal missing costs of individual internal model attempts. There is no new paid run,
runtime behavior, or backfill. Old `ok/n/usd/cps`, P13 Right/Wrong/Unknown/protocol gates, B3 paired piece metrics
and preregistered verdicts remain intact for historical comparability; these descriptive columns do not replace them.

来源函数如上。旧 m4 行只留了小块评分和 run id，没有保存终态，完成状态保留 Unknown，不能从隐藏测试通过反推。
旧单元总额也无法恢复每个内部模型 attempt 的缺费情况。本次不补跑、不改执行行为、不回填历史数据。
旧 `ok/n/usd/cps`、P13 原判定、B3 配对与小块指标及预注册结论均保留，方便历史比较；新列仅补充描述。
