# 进度

[English](STATUS.md) · 中文 · 更新于 2026-11-04 · 版本 0.6.0（GitHub Release 和 PyPI 已发布）

供接手时读的一页，由统筹维护。历史见[归档](STATUS-archive.zh.md)；
改动见 [CHANGELOG](../CHANGELOG.md) 和[各 PR 记录](../changes/README.zh.md)。

## 现在

**已发布：** 0.6.0 已发 GitHub Release 和 PyPI；安装命令为 `pipx install relayline`（#265）。
[工程标准](engineering-standards.zh.md)和[优化计划](research/2026-11-04-optimization-plan.zh.md)已合入（#266）。目标是默认不变差，并找到一个可复现的正效果场景；当前效果仍为 **Unknown**。

**阶段 0 — measured，诊断，题目已用过，非最终证据：** self 留出集 30/30，每次成功 $0.0989，墙钟中位 26.9 秒，`env_clean` 30/30，总花费 $2.97。按预登记，self 配对成本比 1.017 为 Pass（成本增幅不在主导侧）；配对墙钟比 1.276 落在灰区（**Unknown**）。同版本 hc2 ccx2：28/30，每次成功 $0.0861，墙钟中位 169 秒，非同时段。这些诊断不能证明当前版本更省。[hc2 报告](research/2026-11-04-hc2-holdout.zh.md)

**沙箱 — measured：** 只有工作目录外的 TMP 被拒并报 WinError 5，默认系统 Temp 正常，属于评测条件问题（[报告](research/2026-11-04-sandbox-tmp.zh.md)）。

**阶段 1 — engineering check，效果 Unknown：** 已合入 #267（用户原话）、#268（钩子和报告提速）、#269（评测临时目录和事件流）、#270（`small_self_run` + `strict_escalate`）；**#271 待合并**（测试型审查和回放脚本）。全部默认关或评测专用。#268 合成数据：报告 336→97 ms，归档钩子路径 914→5 ms（只算调度，不代表归档完成）。

**已有默认与历史：** 路由 auto，配额感知/审查开；`small_self`、精简开关、记忆去重、无历史子会话/batch 合并、复现门禁关/实验性；worktree 默认 `sibling`，`inside` 自选/实验性；预算 0/不限，计费 `api`。#243–#262 与八层收尾见变更记录/归档。0.6.0 豁免 GIF、博文和 H11 新试用（统筹提议，用户未反对）；`memory.by_kind` 仍关/实验性。#225 记录安全控制和风险，不新增权限。

| 证据 | 结果与限制 | 出处 |
|---|---|---|
| hc2 收据 | 普通 `ok` 误报 0/19，95% 上界约 15%；`done` 仅 6 张，不足以测 2% 门槛；自带子智能体未重跑 | [hc2](research/2026-11-04-hc2-holdout.zh.md) |
| pg3b | 普通 `ok` 收据 0 张；29 张 `ok_self_checked` 中 15 张隐藏测试不过，审查全部给 pass | [pg3b](research/2026-11-03-pg3b-receipts.zh.md) |
| hc1，历史旧代码 | self 29/30、$0.090、21 秒；自带 27/28、$0.103、123 秒；ccx 29/30、$0.063、61 秒；逐点规则，非统计非劣效；“便宜约 30%”不描述 0.6.0 | [hc1](research/2026-10-29-hc1-holdout.zh.md) |
| Polyglot pg1 | self 25/30，ccx2 12/30；小而接口严格的题，一种配置，三行不干净 | [pg1](research/2026-10-31-polyglot-pg1.zh.md) |
| B3 | nomem Unknown；clean Fail；leantools 按规则 Fail / 事后未定；精简侧均关，未证明可靠节省 | [B3](research/2026-10-31-b3-lean-switches.zh.md) |
| #158 后、#223 前误报 | 8/209 = 3.8%；排除主导续跑成功后 8/191 = 4.2%，超过 2%；#223 后没有样本足够的重测 | [审计](research/2026-10-31-verdict-audit.zh.md) |

## 接下来三件

1. **阶段 2：** 回放测试型审查，抓错 ≥ 50%，误拦 ≤ 20%（工程检查）。
2. **阶段 3 和 4：** 新题和大任务评测，门槛见[计划](research/2026-11-04-optimization-plan.zh.md)。
3. **阶段 5：** 重复和外部 issue 基准，然后定对外定位。**总上限 $60**，含失败/中断；任一阶段超过估算上限 1.5 倍就停。

## 把握有多大（简版）

- **real（Windows，已登录 CLI）：** 双向派活、检查/审查、停止/续跑/记账、归档、DeepSeek 主导、discuss、对话板/叫醒、共享上下文 A/B、hc1/pg3b/hc2 和阶段 0、batch/worktree/undo、非 ASCII 路径/隐藏控制台、Windows Codex hook、交互式 Codex 每轮 hook、dsh 排队归档、临时 Claude 插件市场安装、UI 隐藏测试、Codex 实现/审查流程。#243–#254 例外：#248 缺 Claude 审查（限额），#250 统筹 cherry-pick，#244/#246 修复在沙箱外验收。
- **只有 fake / 工程检查：** 席位、配额排序/改派、角色、就绪/刷新、一行结果、看板及阶段 1。**真实样本回放：** #245 Claude 限额事件/四条探针读数（每条 < $0.005）；Codex 拒绝样本仍为合成，不证明真实自动改派（[样本](../tests/data/real_signals/)）。
- **未验证：** 真实限额改派、macOS 钥匙串就绪（缺凭据 = Unknown）、真实离线/慢网络 fetch 超时、已安装 `gpt-6.1-terra` 计价；macOS/Linux 真机（只有 CI）、Gemini CLI、Codex 桌面 `say --now`/doctor 规则/叫醒 hook、dsh 后续写归档、从 GitHub 装 Codex 插件、真实子智能体上限（F11 未触发）、`--review auto` 触发率、真实 hook 超时、GitHub intake、L2 自动合并整条链、评测外路由。本 worktree 缺本地 plan-review；`/private/var`、8.3 短名和 `\\?\` 前缀的 CI 修复未复核。

### 待本人验证（2026-11-04）

- ~~#205 必需检查~~：API 确认已是 `ci-ok` + `personal-data`；~~TestPyPI/PyPI token~~：已发布；~~旧个人路径~~：决定保留历史；~~旧本地分支~~：已删，有备份；~~`worktree.location`~~：保持默认 `sibling`。
- 确认 GitHub 描述/topics 文字。
- Claude 桌面 app 的 Pinned Git Origins 重新固定。
- 批不批 P0-13（约 $2）？未运行。~~留出集上重跑自己做~~：阶段 0 已完成。
