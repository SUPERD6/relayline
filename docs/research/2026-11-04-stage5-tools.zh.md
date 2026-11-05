# 阶段 5 离线评测工具

[English](2026-11-04-stage5-tools.md) · 中文

**资格已更新：**下文八题表格是历史的隐藏测试校验。[后续 P5 合同审计](2026-11-05-p5-contract.zh.md)增加父版本全量基线后，
只有两题合格，目前没有完整可执行局。当前清单记录排除结果，不能继续把历史八题通过当作现行资格。

证据等级：**engineering check**。仅运行离线隐藏测试校验，未调用真实模型或付费 canary，未跑真实模型评测、下载或访问凭据。
没有删除命令或选项。阶段 4 默认 split、原字段含义、退出码与门槛保持不变；只新增花费字段和显式 `--gates p5` 报告。

## A：安装组停在等价性核查

**Unknown，未运行：**Claude Code 2.1.316 的 flags 未能证明与真实安装的原生 `@MEMORY.md` 导入和钩子等价；统筹已停止 A，不新增 `ccx2inst` arm。

## B：新长会话 split 与两侧花费

`p5_long_select.py --ext-cache CACHE` 只读已有本地 git 缓存，复用 `long_candidates.py`、`long_check.py`：
实现 `.py` 改动至少 60 行或 3 文件，不算测试、文档与 `.pyi`；排除 holdout 和全部阶段 4 dev/final commit。
仓库优先级、时间倒序、SHA 正序及同仓库四题一局保持不变。校验父版本隐藏测试失败、参考解通过，
保留拒绝项、缺失仓库、原始输出哈希与缺额，不下载、不降低规则凑八题。
初步题面只取 commit subject，不取补丁或参考解；预登记前应核对题面是否完整，不能看模型结果后改选题。

统筹随后提供了只读缓存与 Python 环境。按原顺序检查 **81 项**候选后选齐 **8/8**；
使用 Python **3.11.9**、pytest **9.1.1**，未查看任何模型结果。
完整选题、排除项、拒绝项与父版本/参考解结果保存在 `scripts/eval/p5_long_selection.json`。

| 仓库 | Commit | 内容 | 实现代码行数 | 父版本退出码 | 参考解退出码 |
|---|---|---|---:|---:|---:|
| more-itertools | `6887a7bd5ac3` | running_median | 71 | 1 | 0 |
| more-itertools | `bbe6c8f7f3f5` | sample counts | 65 | 1 | 0 |
| more-itertools | `5252383356e6` | 傅里叶变换 recipes | 67 | 1 | 0 |
| more-itertools | `02e753222ce2` | grouper recipe | 126 | 1 | 0 |
| boltons | `c669103ccbaf` | range2list / list2range | 115 | 1 | 0 |
| boltons | `294344b84fbd` | 双向 daterange | 69 | 1 | 0 |
| boltons | `d14b5a793d18` | cachedmethod descriptor | 61 | 2 | 0 |
| boltons | `6cea9343927b` | BufferedSocket 线程安全 | 348 | 2 | 0 |

八个参考解均通过。两个父版本收集失败分别因为缺少新增的 `cachedmethod`、`MessageTooLong`，
按原选题检查器允许的规则保留退出码 2。其他被拒绝的旧参考版本包括冲突标记、计时测试失败，
以及 pytest 9 不接受旧版 `pytest_ignore_collect` 接口；没有为凑数修改测试或环境。
完整归一化 pytest 输出及哈希保留在 worktree 本地 `.ccx/eval/p5-selection-raw/`（被忽略，交付时需随审阅证据保留）。
`--run --split p5` 不足八题仍先拒绝；旧 `--split all` 仍只包含阶段 4 原来的十二题。

每条新结果保留精简的 `side_ledger` 证据，包括审查账目；`p5_costs.py` 新增：

| 字段 | 含义 |
|---|---|
| `claude_side_usd` | 原生 Claude 主导（含原生子智能体）加账本中 Anthropic 模型花费 |
| `codex_side_usd` | 账本中 OpenAI 模型花费 |
| `unknown_side_usd` | 已知金额但 vendor/model 归属不明的子任务花费 |
| `side_cost_status` | 金额和归属完整才为 Pass，否则 Unknown |

按显式 vendor/model 或账本 `rungs` 中的模型名判断，不从 CLI/provider 名猜。
跨厂商混合账目没有逐次金额时归 Unknown；账本缺失或金额不符时，已知子任务总额全部进入 Unknown。
主导仍用原来经过累计计数校验的差额。全部行与干净行两个汇总口径均列两侧花费；中断行也保留这些字段。

`--gates p5` 单独增加报告，花费与正确数均用全部十六次尝试：每组八行、题目配对、每局四轮完整成功结束，
干净行总数至少十二、每组至少六。金额、归属或完成证据不足为 Unknown。
证据足够时，Claude 侧总花费 `ccxlong/self <= 0.5` 且做对数 `ccxlong >= self` 才 Pass。
同时列总花费比和墙钟中位比，墙钟没有新增门槛；阶段 4 的 `all` / `env_clean` 判定原样保留。

## 命令（只有显式 --run 才可能调用模型）

```bash
python scripts/eval/p5_long_select.py --ext-cache CACHE --ext-python PYTHON --raw-dir RAW --output scripts/eval/p5_long_selection.json
python scripts/eval/p5_long_select.py --ext-cache CACHE --ext-python PYTHON --raw-dir .ccx/eval/p5-recheck-raw --output .ccx/eval/p5-recheck.json
python scripts/eval/p4_long_session.py --dry-run --split p5 --gates p5 --rounds 1 --tag p5long --budget 9 --out RESULTS.jsonl
python scripts/eval/p4_long_session.py --run --split p5 --gates p5 --rounds 1 --tag p5long --budget 9 --pin-commit FULL_SHA --ext-cache CACHE --ext-python PYTHON --codex-home DEDICATED_HOME --wait-quiet 10 --out RESULTS.jsonl
python scripts/eval/p4_long_session.py --recompute P4FINAL.jsonl --tag p4final --gates p5
```

第二条命令可在沙箱外复现选题与校验，不覆盖冻结清单；CACHE、PYTHON 换成统筹提供的已有路径，机器路径不写入仓库。
真实运行示例需先提交预登记与 pin，显式提供缓存及统筹授权的专用 Codex home，本次没有打开该 home。
八题、十六次尝试的 dry-run 估价合计 **$11.064**：self **$6.915**，ccxlong **$4.149**，沿用历史规模与上下文公式。
该估价高于示例 $9 预算，实际执行预算由统筹决定；估价不是阶段 5 实测花费，也不是账单保证。
没有启动真实评测，没有提高预算。

只读重算 **16 条历史 p4final 记录**（pin `5acfa7d76479`）得到：

| 组别 | 已知 Claude 侧 USD | 已知 Codex 侧 USD | Unknown 侧 USD | 归属 |
|---|---:|---:|---:|---|
| self | 1.015828 | 0 | 0 | Pass |
| ccxlong | 0.125456 | 0 | 1.958487 | Unknown |

ccxlong 的 Claude 数字只是**已知下界**，不是完整 Claude 侧花费；旧行没有保存子任务 vendor/model 账本，
不能据此判阶段 5 花费 Pass。两组均做对 7/8、干净 8/8；总花费分别 $1.015828、$2.083943。
源 JSONL 的 SHA256 保持不变。
