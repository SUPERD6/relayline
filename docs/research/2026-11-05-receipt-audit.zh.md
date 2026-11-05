# P4 的 8 单收据：执行成功与验收分开看

[English](2026-11-05-receipt-audit.md)

这是历史原件的只读核查，没有新跑评测。来源为
`.ccx/eval/p4final-results-artifacts/20261105-000145Z/*ccxlong-*/streams/lead.jsonl`。
8 单收据均为 `ok:true`、`status:partial`、`check.passed:false`、check 退出码 1，
recap 均含 `outcome=check_failed`。下表记录主导最后的转述，不判定题目是否做对。
本次未独立验证转述中归因于 Codex 的解释。

| 单元 | Run | 收据 / 最终回复行号 | 主导最后怎么说 |
|---|---|---|---|
| 1-1-ccxlong-1 | 20261104-190247-3319 | 14 / 17 | 用 `DONE:` 总结 iterutils 修复及新增测试，明确说全量检查失败、验收不干净，并因 `ok=true` 接受。 |
| 1-1-ccxlong-2 | 20261104-190703-c776 | 15 / 17 | 用 `DONE:` 总结文件、路径与命名容器修复，转述未经核实的 52 项定向测试通过，同时明确全量检查失败、验收不干净。 |
| 1-1-ccxlong-3 | 20261104-191333-a50d | 11 / 13 | 用 `DONE:` 总结 GC、类型与追踪修复，转述未经核实的 18 项通过和换行、沙箱问题，明确验收不干净。 |
| 1-1-ccxlong-4 | 20261104-191641-6116 | 15 / 17 | 用 `DONE:` 总结集合操作修复，转述未经核实的定向检查数量与换行解释，明确全量检查失败、验收不干净。 |
| 1-2-ccxlong-1 | 20261104-192309-6a4a | 11 / 14 | 以 `DONE:` 开头总结映射修复，说明 pytest 的 JSON 测试仍失败，把 LF/CRLF 解释归于 Codex，并接受 partial 收据而未查看或重跑。 |
| 1-2-ccxlong-2 | 20261104-192745-6853 | 15 / 17 | 以 `DONE:` 开头总结 BarrelList 兼容修复，说明全量 pytest 仍失败、摘要截断所以原因未知，并说按提示接受。 |
| 1-2-ccxlong-3 | 20261104-193237-772a | 10 / 12 | 以 `DONE:` 开头总结 ellipsize 及新增测试，因 `ok=true` 接受，同时报告全量失败、Codex 未核实的定向测试与换行说法，以及另一个被截断的问题。 |
| 1-2-ccxlong-4 | 20261104-193606-4929 | 11 / 13 | 以 `DONE:` 开头总结 USTimeZone 及新增测试，因 `ok=true` 接受，同时报告全量失败，以及 Codex 未核实的 212 项通过和换行解释。 |

8 单都用了 `DONE:`，也都披露了检查失败。这是完成与接受信号有歧义，不能说主导声称 8 单测试全过。
没有修改隐藏评分、成本、原判定或已发表结论。

## 原因

`ccx/delegate.py` 将适配器的 `oc.ok` 存入 `record.ok`；验收检查失败会设 `kind=check_failed`，
但不改执行标记。`exit_ok()` 排除若干其他失败类型，却不排除 `check_failed`；`compact()` 再排除
子智能体的 blocked/failed 状态及环境失败。因此，即使验收失败，也可能返回 `ok=true` 和退出码 0。
子智能体报告的 status 也是另一回事。

原生 `ccx/leadview.py` 只压缩 `clean()` 结果，`CCX_LEAD_VIEW=line` 不会强制把失败检查压成一行。
P4 专用的 `scripts/eval/p4_receipt.py::render` 则将所有 `ok=true` 收据通过 `leadview.line` 压成一行，
隐藏提示与完整详情，但保留失败检查和 recap。`scripts/eval/p4_long_session.py::prompt` 明确要求：
`ok=true` 就接受且停止查看，否则才允许诊断与修复；还要求两组统一以 `DONE:` 收尾。
这把执行标记当成了验收门槛，能解释已观察到的转述模式。本次保留历史提示与结果；未来更改评测协议须另写预登记。

## 展示修复与证据边界

序列化的一行 JSON 现在把新增的 `headline` 放在最前，例如：
`{"headline":"CHECK_FAILED","run_id":"...","ok":true,"status":"partial",...}`。
使用 JSON 字段是为了保留现有解析器，直接加文本前缀会破坏解析。失败或无法执行的检查优先显示，其他提示包括
`REVIEW_ISSUES`、`PARTIAL`、`BLOCKED`、`FAILED`、`STOPPED`、`RUNNING`、`SELF_CHECKED`、`UNVERIFIED`、`DONE`。
标签只概括已有证据，即使 `DONE` 也不证明隐藏测试正确。标签在序列化时添加，原始记录及现有字段含义不变；
原生完整输出和压缩条件不变。P4 执行成功的任务收据同样将此字段放在最前。没有改选项、默认值、命令、退出码或验收规则。

证据等级：修复为 **engineering check**（定向假 CLI 与单元测试）；新付费模型评测为 **not run**。
标签是否改善真实主导行为、成本或正确率为 **Unknown**。
测试从仓库外通过实际包装器复现检查失败而 `ok=true`，通过 `ccx.py` 检查原生一行输出，并核对现有字段及退出码。
原有测试保持不变。

本地检查：修复前回归测试当时的 15 项全部失败；修复后 `tests/test_receipt_headline.py`、
`tests/test_leadview.py`、`tests/test_p4_long_session.py`、`tests/test_p4_budget_selection.py` 一起通过
（74 项、12 项子检查）。补充过期标签的回归后，收据与变更记录测试一起通过（30 项、15 项子检查）。
变更记录格式及 `git diff --check` 也通过。本单未跑全量、远端 CI、Linux/macOS 或真实模型。
