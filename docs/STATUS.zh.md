# 进度

[English](STATUS.md) · 中文 · 更新于 2026-11-10 · 0.6.0 已发布（GitHub Release 和 PyPI）；main 已领先，尚未发版

供接手时读的一页，由统筹维护。历史见[归档](STATUS-archive.zh.md)；
改动见 [CHANGELOG](../CHANGELOG.md) 和[各 PR 记录](../changes/README.zh.md)。

## 现在

**已发布：** 0.6.0（`pipx install relayline`，#265）。此后 main 又合入 #266–#316，尚未发版；`changes/` 里的记录还没折进 CHANGELOG。目标不变（[工程标准](engineering-standards.zh.md)、[优化计划](research/2026-11-04-optimization-plan.zh.md)）：默认不变差，并找到一个可复现的正效果场景。下面所有新开关的实际效果均为 **Unknown**。

**阶段 1 及之后的工具、第二、三轮（#267–#277，工程检查，多数默认关）：** #267 把用户原话带给子智能体；#268 把归档移到后台、报告只读一次账本（提速，只算调度，未测对完成工作的影响）；#269 评测临时目录放进工作区并保留事件流；#270 加 `small_self_run` 和最便宜档护栏。之后 #271 测试型审查和回放，#273 修第一轮回放发现的问题，#274 阶段 3 工具（30 道新题和候选默认路径组），#275 阶段 4 工具（长会话），#276 第二轮（收据、检查基线、审查、短任务开销），#277 第三轮（额度接力、便宜首轮、审查契约、上手收窄）。**阶段 0**（诊断，题目已用过；self 30/30，配对成本比 1.017 为 Pass，墙钟比 1.276 为 Unknown；同版本 hc2 ccx2 非同时段运行）只作诊断，不能当作当前版本省钱的证据：[hc2 报告](research/2026-11-04-hc2-holdout.zh.md)。**沙箱：** WinError 5 只在 TMP 放在工作区外时出现，属于评测条件问题（[报告](research/2026-11-04-sandbox-tmp.zh.md)）。

**此后合入的修复和开关（#290–#316）：**
- Windows：`--check` 里的 `export` 改用 Git Bash 执行，不再交给 PowerShell（#293）；preflight 输出固定 UTF-8（#301）。
- 派活前：发现简报和运行模式矛盾会警告；只有 `--strict-brief`（实验性，默认关）才拒绝（#294）；`ccx verify --list` 单独列出待判结果（#295）。
- 收据：不再把 `ok` 显示成“做对了”，无独立检查的运行显示 UNVERIFIED（#296）；超时被切断的运行留下改动清单和最后一条消息，时限可配置，超时提醒 `defaults.timeout_reminder` 默认关（#304）；列出未完成的 Git 步骤（#309）；凭据禁读状态按尝试记录（#305；凭据禁读本身默认关，见下）。
- 模型满载：先换模型再换家，不再同模型重试（#298，**默认开**，可关）。
- 默认关：`routing.default = self_first`（[说明](self-first.zh.md)，#299）；`lead.slim_context`（#300）；子智能体凭据文件拒绝规则（#297，**仅 Claude 侧**；Codex 侧没有生效的拒绝规则，见开着的 issue #289）；ccx 可选暂存已解决冲突的文件（#309）；`defaults.timeout_reminder`（#304）。
- 文档/诊断：首页和功能页集中列出“实验性、已测不推荐”的开关，附数字和出处（#302）；`CCX_NO_START_ARCHIVE=1` 关闭会话启动归档（#310；`CCX_NO_AUTO_ARCHIVE` 只管运行后归档）；数字提示（429/401）按独立词匹配，UUID 和哈希不再被判成限流或登录问题（#313）。
- 测试/工具：测试清理前先等后台维护子进程和 UI 线程结束（#308、#312）；只读评测汇总脚本 `scripts/eval/unified_summary.py`（按组成功数、配对 McNemar、p4 任意两组比较）（#315）。

**统一测试 — 已预登记，尚未开跑：** [预登记](research/prereg/2026-11-07-unified.zh.md)已合入（#316）：本轮跑 G1 共享上下文、G2 记忆、G3 便宜首轮、G4 长任务，每组只改一个因素，只作诊断；G5/G6 移出本轮。截至 2026-11-10 尚未开跑（开跑前冒烟发现 Codex 额度用完）。每组只给 Pass/Fail/Unknown，一轮只算信号，不据此改默认值。开跑之前，不能把任何开关说成更省或更好。

**已有默认：** 路由 auto，配额感知/审查开；`small_self`、精简开关、记忆去重、无历史子会话/batch 合并、复现门禁关/实验性；worktree 默认 `sibling`，`inside` 自选/实验性；预算 0/不限，计费 `api`；`memory.by_kind` 关/实验性。

| 证据 | 结果与限制 | 出处 |
|---|---|---|
| hc2 收据 | 普通 `ok` 误报 0/19，95% 上界约 15%；`done` 仅 6 张，不足以测 2% 门槛；自带子智能体未重跑 | [hc2](research/2026-11-04-hc2-holdout.zh.md) |
| pg3b | 普通 `ok` 收据 0 张；29 张 `ok_self_checked` 中 15 张隐藏测试不过，审查全部给 pass | [pg3b](research/2026-11-03-pg3b-receipts.zh.md) |
| hc1，历史旧代码 | self 29/30、$0.090、21 秒；自带 27/28、$0.103、123 秒；ccx 29/30、$0.063、61 秒；逐点规则，非统计非劣效；“便宜约 30%”不描述 0.6.0 | [hc1](research/2026-10-29-hc1-holdout.zh.md) |
| Polyglot pg1 | self 25/30，ccx2 12/30；小而接口严格的题，一种配置，三行不干净 | [pg1](research/2026-10-31-polyglot-pg1.zh.md) |
| B3 | nomem Unknown；clean Fail；leantools 按规则 Fail / 事后未定；精简侧均关，未证明可靠节省 | [B3](research/2026-10-31-b3-lean-switches.zh.md) |
| #158 后、#223 前误报 | 8/209 = 3.8%；排除主导续跑成功后 8/191 = 4.2%，超过 2%；#223 后没有样本足够的重测 | [审计](research/2026-10-31-verdict-audit.zh.md) |

## 接下来三件

1. 按[预登记](research/prereg/2026-11-07-unified.zh.md)跑统一测试 G1–G4 并出报告（需要 Codex 额度）。
2. 用真实 Codex CLI 验证 #289：Codex 侧的凭据禁读规则是否生效。
3. 发版：把 `changes/` 折进 CHANGELOG 并升版本（`scripts/collect_changes.py`，见 [changes/README](../changes/README.zh.md)）。

## 把握有多大（简版）

- **real（Windows，已登录 CLI）：** 双向派活、检查/审查、停止/续跑/记账、归档、DeepSeek 主导、discuss、对话板/叫醒、共享上下文 A/B、hc1/pg3b/hc2 和阶段 0、batch/worktree/undo、非 ASCII 路径/隐藏控制台、Windows Codex hook、交互式 Codex 每轮 hook、dsh 排队归档、临时 Claude 插件市场安装、UI 隐藏测试、Codex 实现/审查流程。
- **只有 fake / 工程检查（含 #271 之后合入的内容），例如：** 席位、配额排序/改派、额度接力、模型满载换模型、角色、就绪/刷新、一行结果、看板、收据 UNVERIFIED 显示、超时收据、Git 未完成步骤列表、简报/模式矛盾检查、self_first、slim_context、Claude 侧凭据禁读、汇总脚本。**真实样本回放：** #245 Claude 限额事件/四条探针读数；Codex 拒绝样本仍为合成，不证明真实自动改派（[样本](../tests/data/real_signals/)）。
- **未验证：** Codex 侧凭据禁读（#289）；真实限额改派、macOS 钥匙串就绪（缺凭据 = Unknown）、真实离线/慢网络 fetch 超时、已安装 `gpt-6.1-terra` 计价；macOS/Linux 真机（只有 CI）、Gemini CLI、Codex 桌面 `say --now`/doctor 规则/叫醒 hook、dsh 后续写归档、从 GitHub 装 Codex 插件、真实子智能体上限、`--review auto` 触发率、真实 hook 超时、GitHub intake、L2 自动合并整条链、评测外路由；上面列出的各开关对成本或成功率的影响（统一测试开跑前均为 Unknown）。
- **已知问题：** 开着的只有 #289。此前仍未验证：没有本地 plan-review；CI 对 `/private/var`、8.3 短名和 `\\?\` 前缀的修复没复查；真实子智能体上限（F11 未触发）。

### 待本人验证（2026-11-10）

- 额度接力的桌面钩子：1 分钟验证（[docs/relay.zh.md](relay.zh.md)）。
- 新建评测用 Codex 登录目录。
- 沿用：确认 GitHub 描述/topics 文字；Claude 桌面 app 的 Pinned Git Origins 重新固定。
