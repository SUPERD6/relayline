# 实验性小活开关

[English](small-tasks.md)

两个新开关默认均为 false。保留全部命令、选项、现有 JSON 含义及退出码。

| 配置 | 开启后的行为 |
| --- | --- |
| `routing.small_self_run` | `ccx run` 启动或转后台前复用 `routing.small_self` 判断。已知主导（不是 ccx 子智能体、user 或 unknown）收到 `state="small_self"`、`delegated=false`、自己做的提示及 `--force` 提示。沿用路由拒绝的退出码 0，表示未派出。 |
| `routing.strict_escalate` | 在 `ccx/plan.py` 中，无 check 的写任务、命中严格接口规则的 brief 跳过最低 T1 档（也识别 Codex gpt-6-luna low）。较强起点不变；`--no-escalate` 仍执行这一起点下限，它不是失败重试。 |

文件数来自 `--files` 或 brief 中已存在的文件路径；`routing.small_self_by=cost` 时复用现有实验性成本估算。
大小未知就继续派。保留已选档位、长上下文、额度紧张等例外；`--worktree` 也继续派。读任务跳过小活拦截。
`--force` 绕过小活拦截，不绕过独立的升档护栏。`routing.small_self` 仍然只影响建议。

严格接口采用不区分大小写的词法规则：`strict interface` / `strict-interface`，
`exact signature`、`exact output`、`exact match`（空格或连字符），`must return/raise/accept/match`，
或 `严格接口`、`精确匹配`、`必须返回`。可能漏掉改写，也可能匹配引文，不表示理解或验证了接口。
普通写任务有 `--check` 就不升档，除非命中上述规则。仅实际升档时，route 新增 `strict_escalate`，记录原档、新档和触发原因。

评测用 `scripts/eval/r5.py run --arms ccx2small` 显式选择。主导和命令措辞沿用 ccx2，追加遇到
`state=small_self` 自己实现的说明。独立 hub 在启动主导前设置并断言两个开关；结果行记录
`small_self_run.applied` 和账本判断，即使没有启动 ccx run 也记录。该组同时改两个因素，不能分别归因。本单未跑付费评测。

证据仅为 **engineering check**，效果 **Unknown**。保守保留 `small_self_files=1`、
`small_self_overhead_usd=0.035`，依据见[开发集报告](research/2026-11-04-small-calibration.zh.md)。
