# P4 native checkout、聚焦修复与重复检查

[English](2026-11-05-p4-native-retry.md)

证据等级为 **engineering check**；没有调用新模型。新增开关默认关闭，现有命令、选项、
JSON 字段含义、退出码和验收规则保留。P5 继续沿用原来的 native checkout 策略。

`p4_long_session.py --native-checkout` 把已有 native Git checkout 策略扩展到所有 split，
包括冻结的 final 8 题。Windows 按 Git 属性检出 CRLF，明确指定 LF 的文件仍保留 LF。
实际任务目录、隐藏评分目录和模型启动前的离线验收使用同一策略。
每题原始父版本必须先通过全量验收命令（exit 0），再满足隐藏测试父版本失败（exit 1 或 2）、
参考版本通过（exit 0）。任何一题不合格就停止，不替换冻结题目。

离线验收不需要模型或 Codex home：

```text
python /path/to/repo/scripts/eval/p4_long_session.py --validate-native --split final --native-checkout --ext-cache CACHE --ext-python PYTHON --audit-output AUDIT.json
```

报告保留逐题 baseline、隐藏父版本和参考版本结果、检出 EOL 计数。全部符合约定时 exit 0，
有排除项时 exit 1。真实 final 8 题在原始 Git cache 上的验收目前为 **not run / Unknown**：
本 worktree 未收到该 cache 的确切位置和原始外部解释器。临时仓库测试验证了验收门禁与
检出策略一致性，不能替代真实 8 题资格校验。

已有 `defaults.focused_retry`，出厂值仍为 false。子智能体报 done/partial 而 ccx 检查失败时，
它可以在下一条已有 rung 中续同一家会话，带入失败命令、退出码和约 2,000 字符输出，
要求只修失败处。它不新增 rung，也不改变升档和验收规则。`--focused-retry` 仅在一次评测的
独立 hub 中开启此设置，影响两个派活 arm；self 不派活。计划和结果记录该开关。
没有新增配置键，也没有修改用户配置。

三组 dry-run 共安排 24 次尝试，不调用模型：

```text
python /path/to/repo/scripts/eval/p4_long_session.py --dry-run --split final --native-checkout --focused-retry --arms self,ccxlong,ccxlongcheap --tag p4native --out RESULTS.jsonl
```

仓库外运行该 dry-run 的退出码为 0，共 8 题；历史成本代理估算为 **$9.603**
（self $4.365、ccxlong $2.619、ccxlongcheap $2.619），不是实际花费。
cheap 使用普通派活流程的规划代理，真实成本仍为 Unknown。6 个相关测试文件共 **72 项通过**，
未跑仓库全量测试。

这两个开关改变不同因素，应在预登记中固定，不能把合并结果单独归因于其中一个。
真实执行仍要求已有的显式 `--run --budget`、源码 pin、外部 cache/解释器及独立模型 home。
dry-run 不证明父版本合格，也不证明三组模型表现。

## 重复检查：暂不复用子智能体检查

`delegate.py` 已经在同一次 attempt 的最终验收中复用自己先前运行的 `early_check`。
子智能体自己执行的命令之后，控制器仍独立验收。`check_baseline.Checks` 也已经按命令缓存
原始 baseline，但不信任子智能体自行报告的测试结果。

[历史 P4 events 回放](data/p4-check-overlap.json) 覆盖 final 的 8 个 ccxlong 单元，源码 pin
见数据；派活累计墙钟为 1,774.921 秒。找到 7 个与最终控制器收据的命令和退出码一致的候选，
**7 个全失败**，没有观察到可供“复用成功检查”路径使用的候选。候选子进程的 pytest 摘要
报告执行时间合计 **5.46 秒**。这是 pytest 报告的执行时间，**不是节省的墙钟时间**：
不含 Python/进程启动开销。8 张控制器收据均未保留检查用时，events 也没有
检查前后的文件树绑定。因此实际可省秒数为 **Unknown**，已证明可安全复用的秒数为零。
这不是当前代码或新优化的实测。

决定：保留独立验收。现有证据不足以支持新增需要绑定精确命令、退出码、环境和文件树的缓存。
没有实现跳过检查，也没有改变默认值。

从任意目录用明确的历史结果和 artifact run 重现：

```text
python /path/to/repo/scripts/eval/p4_check_overlap.py --results P4FINAL.jsonl --artifacts-root ARTIFACT_RUN --out OVERLAP.json
```

回放只读取指定的主导和子智能体 events，不读取模型 home、不执行日志内的命令、不跑测试或模型。
同一 run 的重复收据只计一次；候选命令和退出码只作为观察，不作为验收。
