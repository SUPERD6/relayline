# 运行后剩余的 Git 步骤

[English](git-pending.md) · 中文

每次运行结束时，保存的记录和主导收据新增 `git_pending`。这个只读检测不改变原有字段、判定或退出码。
`unmerged`、`conflict_markers`、`resolved_unstaged` 和 `unsafe_paths` 使用仓库相对路径；`operations`
列出进行中的 merge、rebase、cherry-pick；`steps` 列出尚需完成的 Git 步骤。无法检测时写
`status: "Unknown"`，不能当作没有待办。需要关注时主导视图展开完整收据，recap 也提示未完成步骤。

`resolved_unstaged` 只列出无冲突标记、且工作文件 SHA-256 与派发时 `fingerprints` 不同的 UU/AA 内容冲突。
派发时有冲突的路径暂存后又修改，也可能符合条件。没有运行前哈希就不自动暂存，不动用户原有且本次未改的冲突。
DU/UD/AU/UA/DD 冲突一律需要人工选择，即使文件内容已改；`manual_paths` 和 `steps` 保留这些待办。
候选不代表冲突解决正确。

快照在派发时取得，因此自动暂存只适用于当时已经存在的冲突。子智能体运行中自行 merge 产生的新冲突，
会报告为待办，但因没有派发时的冲突快照，不会自动暂存。

内容检测只读取当前未合并路径和派发时已知的冲突路径，不扫描普通已暂存/未暂存修改，也不扫描未跟踪的新文件。
支持 diff3、CRLF 和 `.gitattributes` 中的 conflict-marker-size。等号分隔行必须恰好为指定长度；
其他标记之后必须是空格或行尾，较长的标题下划线不会被识别为标记。
如果合并开始后改了属性，已有的默认七字符标记仍会被识别。
在检测范围内的冲突路径中，恰好七个 `=` 独占一行的合法内容也会被当作标记；这是偏安全的误报，需主导人工暂存。
每个冲突文件最多读取 4 MiB；超限或无法读取时记为 `Unknown` 和 `unknown_paths`，不自动暂存。
二进制文件、符号链接视为不安全。`unsafe_paths` 只在当前或派发时的冲突路径上影响主导的紧凑视图，
普通图片或符号链接不会让成功收据展开。暂存完成后，主导仍可能需要提交 merge 或执行 continue。
没有 Git 待办不代表任务已经验收。

## 主进程代为暂存（实验性）

```console
ccx config set git.auto_stage_resolved true
```

默认 `false`。仅对 write 运行生效：ccx 主进程逐个仅重新检查当前候选路径，对没有标记的已知冲突路径执行
`git --literal-pathspecs add -- <path>`。不暂存无关修改，不 commit，不执行 merge/rebase/cherry-pick continue。
`git_pending.auto_stage` 记录 `enabled`、`staged`、`failed` 和 `not_staged`；暂存后再次检测剩余状态。
带冲突标记的文件绝不暂存。索引锁或主进程权限不足时保留待办并记录失败。
开启前应停止并发写同一工作区：检测与 Git 读取文件不是一个原子操作。

配置不是布尔值时，关闭自动暂存并记录 `auto_stage.reason`，运行收据仍可写出。
若其他收尾进程（例如 `ccx stop`）已取得收据所有权，本进程保留该记录，不再覆盖收据或执行 Git 收尾。

证据等级是 **engineering check**，没有实测收益结论。测试使用临时 Git 仓库和假智能体 CLI；本改动没有实际运行
Windows 沙箱中的 Codex 冲突解决任务。

## 派发前说明权限

linked worktree 的 `.git` 文件指向主仓库的 `.git/worktrees/<name>`；这些元数据与索引可能在 Codex
workspace-write 沙箱的可写范围之外，`.git` 也可能有额外保护。能改文件不代表能暂存或提交。
如果任务需要写主仓库检出目录，该目录同样需要可写。冲突任务派发前应在简报说明这些权限，或让主进程/主导暂存，
完成操作前先看收据。

2026-11-06 本机核对 `codex-cli 0.164.0`：`codex --help` 和 `codex exec --help` 都提供
`--add-dir <DIR>`，用于添加可写目录。明确授权额外目录可能有助于主检出目录写入，但是否能解除 Git 元数据的
特殊保护，本次为 **Unknown**。ccx 不自动添加 `--add-dir`、不改变默认沙箱权限、不绕过审批。
自动暂存使用主进程已有权限；主进程本身也可能受沙箱约束，失败会留在收据中。
