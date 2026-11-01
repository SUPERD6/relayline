# task-routing（中文说明）

[English instructions: SKILL.md](SKILL.md) · [方法与论文（英文）: references/method.md](references/method.md)

**作用**：在用户要求选模型、比较自己做与委派，或已经授权委派时，提供模型和推理强度的估算建议。普通“省 token”请求不触发估算或委派；输出不是实测成功率、订阅额度预测或启动代理的授权。

**可以单独用**：整个文件夹复制到任何 Claude Code 或 Codex 的技能目录就能用。只需要 Python 3.11+，不依赖 ccx。

## 怎么算的

1. **任务打分**：主导按 5 项给任务打分，加起来是难度 b（0–10）。这 5 项是：改几个文件、跨几个模块、目标清不清楚、风险高不高、要不要新设计。
2. **成功率**：P = 1 / (1 + e^(−1.2·(θ − b)))。θ 是某个“模型 × 强度”组合的能力值，这个公式来自项目反应理论（IRT），也是 IRT-Router 用的方法。
3. **单次成本**：按价格表折算成美元。
4. **怎么选**：能检查对错的任务，先用便宜的，失败了在同一个会话里升级（级联规则）。只有子智能体自己写的测试不算"能检查对错"：自写测试通过 ≠ 做对（ccx 会把这种运行标成 `ok_self_checked`）；要么给它一个已有测试做 check，要么主导对照任务原文验收，否则按"不能检查"算；在“最终成功率 ≥ 门槛”的选项里，挑“每成功一次花费”最低的。不能检查对错的任务，直接选“成功率 ≥ 门槛”里最便宜的。
5. **防过度**：难度 b ≤ 1 建议自己做。如果连最好的组合成功率都低于 50%，建议先拆成小任务。
6. **会学习**：每次记录真实结果（检查过了没有），能力值按 θ ← θ + 0.25·(结果 − 预测) 更新，每周向初始值回落一点。

## 例子

```
python scripts/task_routing.py route --files 3 --coupling cross --clarity goal --risk low --novelty pattern --explain
python scripts/task_routing.py record --rung codex:gpt-6.1-sol:medium --b 4 --ok 1
```

## 档位（整个流程）

`--tradeoff` 也是档位：决定每块活谁做。分档看主导的简报，加上 `--minutes` 和 `--files`（`ccx propose`，或
`scripts/task_routing.py tier`）。文件数、分钟数、简报长度任一项达到某档就算该档；`--minutes` 和 `--files` 都没给时
算大小拿不准。阈值是暂定值，在 ccx 的 `config/tiers.toml [policy.*]`。

| 档 | 谁做 |
|---|---|
| `save` | 全部经 ccx 委派（`ccx2`）；主导按 check + 审查验收 |
| `balanced` | 小、中自己做，大的交 `ccx2`；大小拿不准、状态机/续跑类自己做 |
| `fast` | 全部自己做 |
| `cheapest` | `direct`：交 ccx，主导不验收；要告诉用户结果可能做错 |

只有用户自己能选档，而且是在设置里选：`ccx config set policy.picked <档>`（`none` = 关，出厂即关）。选了以后，
`ccx propose`（不带 `--tradeoff`，或带同一档）等于预先授权按该档委派：返回 `authorized: true` 和 `worth_offering: true`；
把它的 `say` 那句告诉用户，照它给的 `next` 跑（委派部分按 save 选模型），这次运行跳过随机 A/B 自己做。项目的自主级别
（L0/L1）改文件前仍会停下；这次回答记成档位决定的，不算用户点了头。不要自己设 `policy.picked`。你传的 `--tradeoff`
不授权任何事：只是选模型，照旧“先提议一句”（agent-delegate 第 0 节），A/B 和试验不变，档位结果只展示。用户在对话里说了
档位，就是对该档要委派的那些块点了头：用普通的 `ccx run` 派（已获准的委派）。`cheapest` 经你跑仍要花你自己的轮次，
只有脚本或 CI 直接调用 `ccx run` 才省掉主导。你自己发起的 `ccx run --tradeoff balanced|fast` 按该档选模型；
`policy.picked` 只改谁做，不改选模型（不带 `--tradeoff` 的运行和以前一样选）。一次预先授权只管这个任务按你提议的大小跑一次：
用同一个 id 再跑，或跑得比提议小，都会被拒绝。
默认档仍是 `save`，等确认实验再定。

**派活总开关**（`[routing] mode = "off"`，`ccx config set routing.mode off`；出厂 `auto`）：`ccx route` / `ccx propose` 一律回答
`do-it-yourself`，带 `routing_mode: "off"`（照常显示选出的档，`choice` 保留 `recommend_before`），压过已选档位和 `small_self`；
`ccx run` / `batch` / `q run` / `q resume` / `way` 不带 `--force` 就拒绝。`ccx run --mode read`（跨厂商审查或第二意见）、`ccx ask`、
`ccx discuss`、记忆、对话板和已开始运行的 `ccx resume` 不变。

**小活自己做**（`routing.small_self`，默认关，用户自己打开）：没选档位时，`ccx route` / `ccx propose` 在自己做比派活的固定开销便宜时
建议 `do-it-yourself`。`small_self_by = "files"`（默认）：最多 `small_self_files`（1）个源文件。`"cost"`（实验）：请求数（`--requests`，否则 2 + 每个 `--files` 1.5 次，没给就按简报点名的文件）
× 每次重读的量（你的会话，`--lead-ctx` 或像 `ccx lead` 那样读出，读不到按 25k）× 你的模型价格，再加读进的文件写缓存的钱，
对比 `small_self_overhead_usd`（$0.035：pg1 里新会话的 Sonnet 主导在一次派活中自己那份的中位数，按你的模型价格缩放，再加你的
会话更长时它那约 3 次请求多读的部分）；两者都在 `small_self.self_cost` 里。用出厂常数算，不论模型和会话长度都大约是"一个文件"；
`--requests` 和读入大文件才会让结果变。`--minutes` 不挡。用户选了档位、
`--needs` 要只有 ccx 给得了的东西、你的上下文到了 `lead_ctx_large`、你的额度到了 `small_self_quota`（0.9）时不生效（没有价格的主导按
Sonnet 估），`small_self.why` 写明原因。rung、升级梯和档位计划照常显示，`ccx run` 不变。依据：pg1 派活花费 82% 在主导侧，
所以要看自己做贵不贵，而不是题难不难（暂定，等一轮实测）。

**按任务选主导模型**（用户执行 `ccx config set lead.model_by_task on` 才开，默认关）：正在跑的对话不换模型（换了缓存作废）。用同一个难度 b，`ccx route` / `ccx propose` 多给 `new_lead`（新对话用的模型：b 不超过 `easy_max_b` 用 `[lead_by_task]` 的便宜模型，否则用你的：按你平时的模型开）；`choice` 没推荐自带子智能体时，再给 `builtin_model`（你自带子智能体的备用模型，只在简单档给）；`ccx fresh` / `ccx handoff` 带 `--minutes` 时照它选。

## 自动校准

每次检查通过或失败后，记一次结果（ccx 会自动记）。参数会自动向真实情况靠拢：task-routing 校准成功率和花费，task-split 校准每个模型能做多长的任务。Claude 和 Codex 用的是同一个技能目录，所以学到的东西共用一份。价格表超过 30 天没更新会提醒，提醒后对照官方价格页更新。

## 局限

- 初始参数是带日期的估计值，前几周不准，要靠记录真实结果慢慢校准。
- 成本估计误差大约 ±2 倍，等 ccx 记录到真实用量后再替换。
- “成功”指检查通过；检查本身不严，结论也就不严。
