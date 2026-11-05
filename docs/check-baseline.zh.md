# 检查基线感知（实验性）

[English](check-baseline.md) · 中文 · [功能](features.zh.md)

证据等级：**engineering check**，使用假智能体 CLI 和临时本地 Git 仓库。
真实模型评测与节省费用：**not run / Unknown**。没有移除命令或选项。

## 配置

```toml
[check]
baseline = "off"  # 默认；可选 "on_fail"
```

开启：`ccx config set check.baseline on_fail`；恢复：`ccx config set check.baseline off`。
默认保留已有检查判定、重试阶梯和退出码。两种模式都只新增检查日志字段。

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
| 失败列表完整，没有新增用例 | `kind=check_baseline_failed`；不进入检查修复、不升档、不自动记任务做错；由主导先修基线再验收 |
| 失败列表完整，有新增用例 | 按原阶梯修复；修复提示只列新增失败用例名，原始输出保存在日志 |
| 无法比较 | `baseline_comparison=Unknown`；保留退出码，继续原失败与重试流程 |

当前只解析 pytest 完整短摘要中的 `FAILED` / `ERROR` 用例标识，支持参数化用例；数量必须与末尾失败、错误总数
一致。输出中断、收集失败、非结构化输出或数量不符都为 Unknown；仅凭相同非零退出码不判断“全是旧失败”。
起点不干净、非 Git 仓库、含子模块或符号链接、提交不可用、检出失败或清理失败也为 Unknown。命令含源仓库绝对路径时，
不会把修改后的源目录当作基线运行。被忽略的依赖和其他外部状态不会复制；这里比较干净 Git 基线，不复现整台机器。
每次明确派活或 resume 都记录自己的起点，只在同一运行内复用基线。合并批任务的逐项检查也使用整组派活起点，
每个不同命令只跑一次基线；只有旧失败的项不进入检查修复或另派单项。基线失败不能证明本单改动正确。

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
