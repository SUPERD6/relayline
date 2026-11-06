# 模型容量错误恢复

[English](capacity.md) · 中文

CLI 失败并报告 `Selected model is at capacity` 时，ccx 记录 `kind=capacity`，
与订阅额度耗尽、认证错误、网络错误分开。识别复用额度信号分类器，只接受明确 CLI
错误文本和错误事件；普通 assistant/tool 内容和单独的 HTTP 429 不算容量不足证据。
容量证据只看最后一条 CLI 错误或 turn 结果，中途自愈的错误不能覆盖最终失败；已有的
quota、模型不支持、认证和环境错误判定优先。

本次修 bug 默认开启。恢复旧的重试行为：

```console
ccx config set defaults.capacity_fallback false
```

恢复时先走现有梯子的剩余项，跳过已经尝试过的 agent/model 组合，包括同模型的其他推理档。
没有剩余项时，可由现有跨家选择器提供一次替代。每次运行最多因容量错误换两次，
每次新开会话并使用原始简报，仍受现有预算检查约束。
`--no-escalate` 去掉剩余梯子，`--no-fallback` 仍关闭额外的跨家后备；两个都设时首次容量错误就停。
显式 resume/追问遇容量错误时停止，避免悄悄丢掉上下文。自动接续的新任务允许恢复，
但新会话会收到完整任务提示，不发送依赖旧会话的追问提示。

收据新增 `capacity_recovery`，记录来源和目标 rung、`reason=model_at_capacity`、
`action=switch|stop`；每次尝试新增 `capacity_stop` 证据。
容量失败不永久标记模型不可用，不更新额度压力，也不作为模型能力不足来学习。
恢复记录还包含 `same_vendor`、`from_tier`、`to_tier` 和 `tier_upgrade`；档位不可比较时用 null。
同家升档会明确记录；`cost_increase=null` 表示没有推断实际价格差。
容量停止会中断暖通道、自动会话/seat 复用和合并任务的修复尝试；UI 保持待判断，不记成做错。
检查点保留现有 `reason=error` 约定，在 note 中写明 capacity 和 resume 命令。
保留现有命令、选项和退出码；关闭开关保留旧的错误分类。

证据等级：**engineering check**，只用合成错误事件和假 CLI 子进程检查。
真实服务行为及 Windows/Linux/macOS CI 为 **Unknown**，没有运行真实 CLI 评测。
