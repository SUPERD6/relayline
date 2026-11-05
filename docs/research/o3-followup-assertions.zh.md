# O3 后续断言调整清单

[English](o3-followup-assertions.md)

统筹明确授权按第 4、5 项需求修改本轮新写的派活与接力测试。以下逐条列出原有断言的变化；其余原断言保留。

| tests/test_dispatch.py 中的测试 | 原值 | 新值 |
|---|---|---|
| 升档策略参数化的 Unknown 情况 | `False` | `True` |
| Unknown 基线集成测试 | `len(attempts) == 1` | 尝试档位 `['T1', 'T2']`；`check_failed` 与比较结果 `Unknown` 保留 |
| 普通脚本检查通过 | 档位 `['T1']` | 档位 `['T2']` |
| 普通脚本检查通过的收据 | `dispatch.escalated == 0` | 不含 `dispatch`；仍不含基线记录 |
| 普通脚本检查先失败后成功 | 档位 `['T1', 'T2']` | 档位 `['T2', 'T3']` |
| 普通脚本检查先失败后成功的收据 | `dispatch.escalated == 1` | 不含 `dispatch`；最后检查仍通过 |

| tests/test_relay.py 中的测试 | 原值 | 新值 |
|---|---|---|
| 实际安装的裸 StopFailure 钩子命令 | 只断言 `quota_signal.source == 'StopFailure'` | 断言完整信号 `{'kind': 'rate_limit_unconfirmed', 'source': 'StopFailure'}`，来源值不变 |

新增断言验证：未确认包与通知的状态、建议等待或手动接续且不建议停止旧会话、未 force 时无子进程、
显式 force 后可启动、已确认额度证据无需 force，以及旧的未标记 StopFailure/rate_limit_event 包也需要 force。

原共享派活夹具由 `check_run.py` 模拟 pytest 输出；现在提交独立 pytest 验收文件并真正运行 pytest。
Unknown 基线用例在派活前留下未提交文件，使基线确实无法取得。普通脚本的通过与失败用例保留脚本，
改为验证原路径；另补真实 pytest 便宜首轮通过和 CLI 错误升档的覆盖。
