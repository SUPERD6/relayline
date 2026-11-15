# 检查基线感知（实验性）

[English](check-baseline.md) · 中文 · [功能](features.zh.md)

证据等级：**engineering check**，使用假智能体 CLI 和临时本地 Git 仓库。
真实模型评测与节省费用：**not run / Unknown**。没有移除命令或选项。

## 配置

```toml
[check]
baseline = "off"  # 默认；可选 "on_fail"
sensitivity = "off"  # 实验性；可选 "warn"、"escalate"
```

开启：`ccx config set check.baseline on_fail`；恢复：`ccx config set check.baseline off`。
默认保留已有检查判定、重试阶梯和退出码。新增默认行为：每次保存 stdout/stderr 日志（合计最多 2 × 256 KiB），
并新增 `stdout_path`、`stderr_path`、`stdout_truncated`、`stderr_truncated` 和 `failed_cases`；紧凑收据默认新增
`headline` 展示字段。这些字段和日志保存行为在 `baseline = "off"` 时也生效。

`on_fail` 在派活前记录干净 Git HEAD 和工作子目录，并将已跟踪文件的实际字节保存到 `check-baseline-start.zip`。
Git 显示干净仍可能有归一化后的 LF/CRLF 差别；只有开启功能时才增加这份本地磁盘和 I/O 开销。
验收命令第一次失败后，在该 HEAD 的独立本地 clone 中
重跑同一命令一次；不改源仓库的索引、文件、分支或 worktree 注册表。检出沿用有效的 `core.autocrlf`、
`core.eol` 和 `core.symlinks`，设置固定提交的 HEAD/索引，再恢复保存的起点字节，不执行检出 hook 或 smudge filter。
无论检出、命令是否失败，都在 `finally` 清理临时 clone。
有整单验收命令时，此模式等检查通过后才开始审查，避免在诊断基线时启动审查。

## 结果

| 基线与比较 | 处理 |
|---|---|
| 基线通过 | 保留原来的失败与重试流程 |
| 失败列表完整，没有新增用例 | `kind=check_baseline_failed`；不进入检查修复、不升档（下文敏感性选项除外）、不自动记任务做错；由主导先修基线再验收 |
| 失败列表完整，有新增用例 | 按原阶梯修复；修复提示只列新增失败用例名，原始输出保存在日志 |
| 无法比较 | `baseline_comparison=Unknown`；保留退出码，继续原失败与重试流程 |

`check_baseline_failed` 和 `check_failed` 一样返回 `ok=true`、CLI 退出码 **0**，表示执行完成，但验收失败。
脚本必须检查 `kind`、`check.passed` 和 `check.baseline_comparison`，不能仅凭进程退出码或 `ok` 接受结果。

当前只解析 pytest 完整短摘要中的 `FAILED` / `ERROR` 用例标识，支持参数化用例；数量必须与末尾失败、错误总数
一致。输出中断、收集失败、非结构化输出或数量不符都为 Unknown；仅凭相同非零退出码不判断“全是旧失败”。
参数标识按方括号配对截取，保留其中的 ` - `；括号不配对时为 Unknown。
起点不干净、非 Git 仓库、含子模块或符号链接、提交不可用、检出失败或清理失败也为 Unknown。命令含源仓库绝对路径时，
不会把修改后的源目录当作基线运行。基线环境会移除 `PYTHONPATH` 中指向源树的条目，并用启动探针记录实际 Python
模块路径到 `check_baseline.import_origins`（`check_baselines` 各项也保存），包含 editable 安装实际导入的路径。
失败检查仍从源树导入，或无法收集导入证据（例如非 Python 命令、`-I`/`-S`、突然退出）时，基线为 Unknown，
不能判为 `baseline_only`。被忽略的依赖和其他外部状态不会复制；这里比较干净 Git 基线，不复现整台机器。
每次明确派活或 resume 都记录自己的起点，只在同一运行内复用基线。合并批任务的逐项检查也使用整组派活起点，
每个不同命令只跑一次基线；审查修复轮仍使用整组第一次派活的快照。
敏感性开启时，通过的合并任务项也运行基线。开启基线失败比较时，只有旧失败的项不进入检查修复或另派单项。
基线失败不能证明本单改动正确。

## 记录和日志

`run.json.checks` 保存每次实际验收检查；`run.json.check` 仍代表最后一次检查。每次只新增 `stdout_path`、
`stderr_path`、`stdout_truncated`、`stderr_truncated` 和 `failed_cases`（`null` 表示 Unknown）。
stdout/stderr 分别保存，单文件最多 256 KiB，保留开头；已有 `tail` 字段含义不变。比较只使用完整解析的用例列表，
不依赖日志是否截断。日志包含命令输出，按已有运行 events/stderr 日志对待。

`check_baseline_start` 记录起点或不可用原因；`check_baselines` 列出不同命令的基线，`check_baseline` 是第一份，
含 `status`（`Pass` / `Fail` / `Unknown`）、可用时的基线检查，以及包含检出、检查和清理的 `seconds`。
`check_baseline_seconds` 在运行和账本中另存这些基线的累计耗时（合并任务写入 merge 事件），
不改已有 `seconds`（智能体尝试耗时）的含义；不调用模型，也不产生额外模型费用。只有基线失败的队列任务记为
blocked，等待修基线，不记为任务完成。清理失败会记录 `cleanup_path`，基线记 Unknown，留下隔离目录
供主导检查；不会清理源工作树。收据给出最终日志路径和基线记录，一行结果说明为什么因基线问题停止修复与升档。

## 检查敏感性（实验性，默认关闭）

已有测试集可能在修改前后都通过，却没有测到新要求。运行 `ccx config set check.sensitivity warn`，
即可在子智能体检查通过时，也与派活时的干净 Git 树比较。`off` 保留现有行为，通过时不额外运行基线。
没有提供验收检查时，敏感性功能不捕获快照、不额外执行命令。复用上述快照、隔离 clone 和按命令缓存，
重试不会重复运行同一命令的基线。

| `check.sensitivity` | 行为 |
|---|---|
| `off`（默认） | 沿用已有基线与检查策略，不执行敏感性工作 |
| `warn` | 记录敏感性，检查没有验证新要求时提醒主导；不改重试策略 |
| `escalate` | 另外把不敏感的便宜首轮视为未验证，在原固定模型、预算、认证和升档限制内，进入原本请求的档位一次 |

`--no-escalate` 保留原起始档，并用 `needs_lead` 提醒主导检查不敏感。
不走便宜首轮时，`escalate` 与 `warn` 相同。敏感或未知结果不产生额外升档。
子智能体自写且失败的检查仍受已有独立性约束。`baseline = "on_fail"` 的原失败策略保留，
只有不敏感的便宜首轮可以使用已授权的敏感性升档。恢复：`ccx config set check.sensitivity off`。
单独开启 `warn`（`baseline = "off"`）保留审查与检查并行启动；`on_fail` 和 `escalate` 等检查结束后再审查。
`escalate` 下，检查通过但未验证的便宜首轮记为 `check_unverified`；`check_failed` 仍表示检查失败。
参与临时学习记录的尝试中，非最后一次尝试原本就按未成功计入；此次标签修改不改变这条学习规则。
这表示缺少验证，不代表已证明实现错误。

运行记录和紧凑收据增加 `check.sensitivity`：

| 值 | 证据 |
|---|---|
| `sensitive` | 基线失败、修改后通过；能完整解析 pytest 失败集合时，至少一个基线失败用例不再失败（`fixed_cases`） |
| `insensitive` | 基线与修改后检查都通过，或修改前后完整失败集合相同 |
| `unknown` | 基线缺失或不可用、检查损坏或超时、失败输出不可比较、从通过变为失败的回归，或只有新增失败而没有可识别的改善 |

完整失败列表使用已有 pytest 解析器。无法解析时，仅基线测试失败（退出码 1）后通过可判为敏感；
收集或环境问题等其他退出码保持未知。两个非零退出码不能证明敏感。
当前检查记录始终包含退出码；不含该字段的旧式摘要比较仍保留整体从失败变通过的判断。
没有用例证据时省略 `fixed_cases`。失败消失不能证明覆盖充分或检查独立：跳过、筛掉、删除或改写测试仍需主导检查，
已有检查依据标签继续生效。敏感也不能证明任务正确。通过的 Python 基线也必须有导入探针证据；
探针缺失或仍从修改后的源树导入时，敏感性为未知，不改变旧基线判定。
因此非 Python 命令、Python `-I`/`-S` 可能保持未知。
检查从项目内 `.venv` 导入 pytest 或依赖时，这些导入位于源仓库内，导入路径保护始终使敏感性为 `unknown`。
需要比较时，使用仓库外的解释器和依赖环境。

`insensitive` 时，`hint` 和 `needs_lead` 说明检查是否在修改前已经通过，或是否仍是同一批失败，
并要求增加验证新要求的测试。检查退出码、`passed` 和已有 `kind` 含义保留。
从通过变为失败的回归保留正常失败输出和重试流程。通过但不敏感的结果和已授权升档的相同基线失败，
都提示更强档位对照任务原文验证。相同失败的提示明确说明这些失败在修改前已经存在，只列用例标识，
不发送原始失败 tail，也不使用 focused“只修失败”指令。要求补充需求测试的提醒留给主导，不发给重试的子智能体。
`run.json.checks` 保存每次实际检查的敏感性，最后的 `run.json.check` 和 `ccx show` 收据也展示。
开启此设置时，顶层 `check_sensitivity` 在没有运行检查时默认为 `unknown`，`check_sensitivity_mode` 记录模式。
`check.sensitivity_seconds` 记录额外基线耗时，包含 clone、执行和清理；复用缓存时为零。
`check_baseline_seconds` 在运行和账本中记录累计耗时，只在敏感性开启时加入收据。
一行视图只保留敏感性模式、值和基线累计秒数；完整基线与导入路径仍在 `ccx show` / `run.json` 中。
基线比较不调用模型。
本功能目前只有工程检查，真实模型的正确率、费用和耗时影响均为 **not run / Unknown**。
