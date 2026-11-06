# 实验性优先自己做路由

[English](self-first.md) · 中文

`ccx config set routing.default self_first` 优先在当前会话自己做。
默认仍是 `auto`：现有行为、策略、JSON 字段含义、判定和退出码保持不变。
本开关只有工程检查，**尚未用真实 CLI 实测成本、墙钟和正确率**。
执行 `ccx config set routing.default auto` 恢复现有行为。

启用 `self_first` 后，`ccx route`、`ccx propose` 建议自己做，普通自动路由的 `ccx run` 拒绝派活，
除非至少满足下面一项：

| 条件 | 复用的现有输入 |
|---|---|
| 主导额度紧 | 现有额度读数或 `--quota 主导=已用比例`；任一有效窗口已用比例大于 `quota.avoid_above`（0.8），或预测比例大于 1.0 |
| 主导上下文很大 | route/propose 的 `--lead-ctx`，否则读取当前主导会话；至少 `policy.bands.lead_ctx_large` 个 token（150000） |
| 明确指定派活 | 具体的 `--to`、`--model`、`--provider`、`--role`，或任务规格中对应的字段 |
| 有独立并行工作 | run/route/propose 显式 `--independent-parts`，或任务规格中 `independent_parts: true` |

额度或上下文读不到时保持 `Unknown`，不算满足条件。不按任务大小或正文关键词猜测并行性和明确派活。
route/propose 不能自动识别主导时，用 `--lead` 指定。
路由、提议账本或运行收据的 `route` 中，`self_first.checks`、`matched`、`why` 记录判断依据。
`eligible` 只表示可以继续现有路由检查，不强制派活，也不构成授权。
现有小任务、额度、预算、自主权限和验收检查继续生效；`--force` 保留显式覆盖作用，`routing.mode=off` 仍是总开关。
显式 `--role`（包括固定模型的角色）属于 `explicit_request`。其内部选型覆盖不算用户传了 `--force`，
收据的 `forced` 只记录用户实际传入的标志。

`--independent-parts` 声明任务有可由主导并发派发的独立块，不要求子智能体再开子智能体。
原有 run 的 `--parallel` 保留要求子智能体自己开子智能体的作用，不满足 self-first 的并行条件。
需要两种行为时同时传两个选项；没有删除任何选项。

读取额度出错（文件或解析错误）时，`quota_tight` 同样是 `Unknown`。
`checks.quota_missing` 列出额度读数中已有名称、但已用比例不可用的窗口，包括已过期窗口。
`quota_tight: false` 表示观测到的有效窗口都不紧，不表示所有窗口都有读数；没有有效窗口时保持 `Unknown`。
完全未出现在读数中的窗口名称不做猜测。某个已知窗口额度紧时，即使另一窗口缺读数，仍可满足条件。

当前上下文来源只有 `given`（显式 `--lead-ctx`）、`lead_session`（读取主导会话）、`none`（不可用）。
仅复用前两种读数，零也是有效读数。估算、默认值及其他来源标签不当作读数；没有实际会话读数时，
即使成本估算含很大的 token 数，上下文条件也保持 `Unknown`。

原有整套流程策略不变：`fast` 全部自己做，`balanced` 按任务大小和上下文决定，都不能表达这四个条件。
所以在 `[routing]` 加一层小开关，复用已有输入，不增加一套模型选择策略。
没有满足条件时也阻止已选档位预授权提议；满足条件后仍遵循该档位自己的决定。

没有移除命令或选项。已开始会话的续跑、ask 和 discuss 路径不变。

## 用户强制与内部路由调用

只有 CLI 真正解析到 `--force` 时才产生正向标记 `_user_force`。self-first 不再从路由规格的 `force`
推断用户意图，包括 batch JSON 或旧 `_self_first_force` 键。原有 `force` 的模型选型和 A/B 语义不变。
run、batch 传递 CLI 标记；队列补位和暖通道只在用户确实传入时保留它。`--` 后正文里的 `--force` 不算选项。

队列 piece 已由 `q run` / `q resume` 明确决定派发，因此符合 `checks.explicit_request: true`，
并记录 `checks.explicit_request_source: "queue"`，`why` 带 `source=queue`。未传 CLI `--force` 时，
其 `forced` 为 false。这是明确要求派活，不是强制覆盖；原有额度、预算、自主权限、验收和路由总开关的含义不变。

只搜索 `ccx/` 后找到以下 5 处内部路由 force 来源：

| 内部位置 | self-first 处理 | 回归测试 |
|---|---|---|
| `commands/workqueue.py` 的 `_one` | 队列派发记明确要求；内部 `force=True` 不算用户强制 | `test_queue_piece_records_explicit_queue_request` |
| `commands/memory.py` 的 `_handoff_by_model` | 自动转录回退仍需满足门槛，不能借 force 覆盖 | `test_transcript_handoff_internal_force_does_not_launch` |
| `commands/delegation.py` 的 `_route_pick` 角色分支 | 内部只为建议选型，最终建议按真实 CLI 意图判断 | `test_advisory_role_and_rubric_force_is_not_user_force` |
| `commands/delegation.py` 的 `_route_pick` 普通难度分支 | 内部只为建议选型，最终建议按真实 CLI 意图判断 | `test_advisory_role_and_rubric_force_is_not_user_force` |
| `plan.py` 的 `resolve_role` 固定模型选型 | 保留选型 force，原样传递 CLI 标记；角色属于明确派活 | `test_fixed_role_reports_explicit_assignment_and_actual_force` |

还核查了：relay 直接启动原生 CLI，`--force-unconfirmed` 是另一种选项；resume、review、merge 修复
使用不含路由 force 字段的 `Request`，不向 `resolve` 或 `_plan` 传入内部 force。
`setup.py` 的 `init_hub(force=True)` 用于切换 hub 接线，不是路由判断。
这些路径不制造用户强制标记，原有行为保留。
