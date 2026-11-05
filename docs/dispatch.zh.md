# 实验性便宜首轮派活

[English](dispatch.md)

通过 `ccx config set dispatch.cheap_first true` 开启；随仓库发布的
`[dispatch] cheap_first = false` 保持关闭。目前只有工程检查，省钱和正确率提升均为 **Unknown**。

可写任务带有调用者提供的独立 `--check` 时，先用该智能体配置的 T1 档；验收确认新增失败后，
回到原本选定的起始档。不增加任务大小、接口风险或措辞筛选。没有 `--check` 时走原路径。
显式模型、角色固定模型、续跑和 `--no-escalate` 保留原选择。没有移除命令或选项。

调用者需要提供独立验收命令，不能让干活的子智能体临时自写测试充当验收。现有自写测试检测发现
检查使用的测试全由本次运行编写或修改时，不触发升档；这不能证明任意 shell 命令的独立性或覆盖完整性。

本路径为当前运行启用 [`check.baseline = "on_fail"`](check-baseline.zh.md)，不修改 hub 的原配置。
只有旧失败不升档；基线通过时，可以携带本次失败输出；基线失败时，只携带能识别出的新增失败用例。
基线无法取得或比较不清楚时保留 Unknown，不触发派活升档。现有检查判定、退出码含义不变。
环境错误不触发任务升档；原额度 fallback、模型不可用替换、审查与修复限制保留。

`run.json`、`ccx show` 和 ledger 新增 `dispatch`：记录实际首档、原选定档、`attempted`、
`escalated`、`escalation_rate`、`first_usd`、`escalation_usd`、`recovery_usd`（额度或模型恢复）。
总体升档率用 sum(escalated) / sum(attempted)，不平均四舍五入后的比例。阶段费用是干活尝试的 API 等价美元，
审查与修复仍保留在原总费用中；缺失价格写 null，不当成零。

## 六题评测计划

从其他目录执行时，把脚本换成绝对路径：

```text
python scripts/eval/p4_long_session.py --dry-run --split dispatch --arms self,ccxcheapfirst --budget 6.5 --lead-budget .25 --child-budget .5 --tag dispatch-r1
```

dry-run 不调用模型。按冻结顺序复用 P4 前六道已校验题（四道 dev、两道 final），明确标记已用过，
不能当作未见最终集。每题每组新建一个只做本题的主导会话，交替组别顺序；只在候选组 hub 开启本功能。
候选组沿用独立验收命令，保留原审查。

只允许一轮、`self,ccxcheapfirst` 两组和不超过 $8 的预算。示例运行包络为 $7.25：
$6.50 步间预算加 $0.25 主导和 $0.50 子任务额度；`--run` 拒绝包络超过 $8。
这是运行步骤的预算界限，不是供应商账单的绝对硬限；不会切断正在执行的一步。记账 Unknown 就停。
已观察升档率严格超过 30% 时，在下一题开始前停止，包括只完成首个候选任务就超过的情况。
缺少派活证据也停止。失败和中断保留并入账。

汇总新增 `dispatch`，报告分阶段费用、升档分子分母，以及全部行和环境干净行的配对比较；原 P4 字段保留。
完整六对要求做对数不低于 self、总费不超过 self 的 0.8 倍、墙钟中位数不超过两倍；证据不全写 Unknown。
触发早停留下不完整比较，不能当作通过。付费执行前，由统筹按[工程标准](engineering-standards.zh.md)
提交预登记和代码 pin；本文不授权执行。
