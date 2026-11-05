# P4 累计花费修正

[English](2026-11-04-p4-cost-accounting.md)

证据是工程测试和对已保留开发结果的只读重算，没有新增模型调用。题目、门槛、预算金额和产品行为不变。

Claude Code 2.1.316 恢复会话后的 result 事件中，`total_cost_usd` 与 `modelUsage` 是会话累计值，
`result.usage` 是本次调用值。原脚本相加累计值，重复计入了之前的轮次。
现在每局每组单独保留已校验的累计基准，初始为零。`lead_cumulative_usd` 保存本轮累计，
`lead_previous_cumulative_usd` 保存上轮可信累计，`lead_usd` 是二者差值。
`usd`、`known_usd`、每局累计、Budget 和 summary 都使用差值。

`lead_result_usage` 保留本次 result usage，`lead_model_usage` 汇总各模型的累计计数。
仅当逐轮相加的 `input_tokens`、`output_tokens`、`cache_read_input_tokens`、`cache_creation_input_tokens`
分别等于 `modelUsage` 的 `inputTokens`、`outputTokens`、`cacheReadInputTokens`、`cacheCreationInputTokens` 时，
`cost_cumulative_check=true`。字段缺失、非整数或负数也判校验失败，`cost_errors` 记录原因。
累计费用缺失、非有限数、负数、倒退、usage 校验失败或会话 ID 不符时，主导费用未知：
`lead_usd=null`、`usd=null`、`cost_complete=false`。已知子智能体费用仍入账。
保留最后可信基准，未知记账会停止运行；后续收据不能自动补平未知间隙。
任务失败但收据完整有效时，仍记入已观察到的费用。

再次核实了 `claude --version` 和 `claude --help`：版本 **2.1.316**。
help 只说明 `--max-budget-usd` 限制 print 模式 API 花费，没有说明 resume 下按单次还是整个会话判断，
计划中对此明确记为 **Unknown**。现有预算上界仍是调度政策，不是供应商账单保证。

可以从任意目录只读重算，旧行必须显式指定对应的 artifacts 运行目录：

```text
python /path/to/repo/scripts/eval/p4_long_session.py --recompute /path/to/p4dev-results.jsonl --artifacts-root /path/to/p4dev-results-artifacts/20261104-231406Z --tag p4dev --split dev
```

命令只向 stdout 输出修正行及全部行、干净行 summary，不写原始文件，不运行预检或模型。
新行已保存规范化计数，可以省略 `--artifacts-root` 重算。缺日志、缺轮次和校验不符均保留未知，不退回原先重复计算的数字。

保留的开发数据重算结果如下，全部行和干净行口径一致：

| 指标 | self | ccxlong | ccxlong / self |
|---|---:|---:|---:|
| 花费，美元 | 0.258323 | 0.397702 | 1.539553 |
| 做对 / 尝试 | 1 / 3 | 0 / 3 | 0 / 1 |
| 墙钟中位，秒 | 47.563 | 135.688 | 2.852806 |

每组只完成预登记四题中的三题，原门槛下结论仍是 **Unknown**。
派活和只读一行仍同时变化；这份不完整开发数据不能支持正效果说法。

统筹已授权更新共享假 CLI，使其符合真实收据协议：累计费用为 $0.10/$0.20/$0.30/$0.40，
modelUsage 逐轮累计，usage 只含本次；每次实际费用仍为 $0.10。原有断言全部保留。
新增独立回归测试检查两组的累计值和本次字段，本次跟进没有修改记账校验及其保护逻辑。
