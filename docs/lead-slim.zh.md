# 实验性短任务主导精简

[English](lead-slim.md) · 中文

`[lead] slim_small = false` **默认关闭**。用 `ccx config set lead.slim_small true` 开启。
运行 `ccx sync --only memory --apply` 更新已有受管块；正常的 `ccx turn` 钩子也会给出指令。
两处都调用 `ccx.lead_slim.small_guidance`，子智能体的钩子不输出它。
关闭时运行 `ccx config set lead.slim_small false`，再同步一次，移除受管块里的指令。
已经打开的对话可能仍保留旧指令；切换后用新会话核对。

开启后，主导已有信息能确认是小活时，直接实现并检查，不先调用 ccx、不写 brief、不加载派活技能。
沿用 `routing.small_self_files` 的文件数限制（默认 1 个实现文件）。这是给主导的指令，不增加硬性拒绝。
文件数不确定、需要 ccx 的 worktree/undo/resume/另一厂商支持、主导上下文大或已知额度紧张时，仍走正常派活。
上下文和额度阈值沿用现有配置。已选档位、按成本判断小活时不输出捷径指令，仍由原路由决定。
不会为这个捷径额外查额度或上下文；不知道大小不等于小活。

命令、选项、JSON 含义、退出码、拒绝绕过方式、验收、审查与升档规则均保留。
实际调用 `ccx run` 时仍按原行为运行。指令存在不能证明模型会照做，也不能证明路由决策完全相同。

证据为 **engineering check**，尚无省钱实测。r5 可选组 `ccx3cand` 开启阶段 3 的候选开关和本开关，
使用压缩指令，保留相同的派活命令及检查、审查、等待、验收行为。这是提示词与配置一起改变的实验。
小活捷径不会写 `small_self_run` 账本事件；没有事件时保持 null/Unknown，不伪造主导的判断。
`fresh2` 新题和历史开销分析见[交付报告](research/2026-11-05-lead-slim.zh.md)。
