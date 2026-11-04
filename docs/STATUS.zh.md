# 进度

[English](STATUS.md) · 中文 · 更新于 2026-11-04 · 版本 0.6.0（标签和 PyPI 见“接下来三件”）

供接手时读的一页。历史与旧把握程度表见[归档](STATUS-archive.zh.md)；改动见
[CHANGELOG](../CHANGELOG.md) 和[各 PR 记录](../changes/README.zh.md)。本页由统筹维护。

## 现在

**0.6.0 候选重测（hc2，2026-11-04，预先登记）：** 留出集做对 28/30（干净行 25/27），每次成功 $0.088，墙钟中位 168 秒；自己做和自带子智能体**没有重跑**。19 张普通 `ok` 收据这轮没有误报，只能说到这里（95% 上界约 15%，`status=done` 只有 6 张），不能说低于 2%。预登记第 3 条有歧义，统筹按比例判，[报告](research/2026-11-04-hc2-holdout.zh.md)里写明了。成本和墙钟比 hc1 高（配对 +32% / +157%）；代码、沙箱、Claude 版本都变了，原因没有隔离，不能认定产品变慢。**hc1（2026-10-29，旧代码）现在是历史实验：** “便宜约 30%”不描述当前版本。

**10-30 → 11-01 八层收尾：** 细节见[变更记录](../changes/README.zh.md)。
① 叫醒/一行结果/提示瘦身默认开（Codex 叫醒 hook 与瘦身实验性；#239 缓存前缀对齐未实测节省）；② 记忆去重、③ 无历史子会话/batch 合并实验性、默认关；④ `routing.mode=auto`，`small_self` 关，能力表只建议，配额感知开，角色自选/空表。
⑤ 覆盖 rubric/审查默认开，自写测试非独立证据，保留 `ok_self_checked`，复现门禁实验性/关，预算 0/不限，计费 `api`；⑥ worktree 默认 `sibling`，`inside` 自选/实验性，金丝雀开，沙箱授权取消（`kind=env`）后需 `--env-fixed`；⑦ 精简开关关、保留负结果，#204 评测/开发共用一台机器一个账号；⑧ 可选 UI，含项目地图、运行视图与预览/确认。

**11-03 → 11-04 合入：** #243–#262，见 [0.6.0 变更](../CHANGELOG.md)：按就绪情况选人（#253）、收据写明最终执行者（#252）且 `check_failed` 不再读成做对（#261）、每日 UI（#249）、记忆建议筛选和批量处理（#257、#260）、修复链 `needs_lead` 提示（#258）、评测汇总把完成率和正确率分开（#256）、对外数字改写（#262）。

**0.6.0 豁免（统筹提议，用户没有反对）：** GIF、博文（发布说明先顶）、H11 新试用（`memory.by_kind` 仍默认关，实验性）。

**安全：** #225 记录威胁模型、控制与剩余风险，不新增执行权限。

| 测量 | 结果与限制 | 出处 |
|---|---|---|
| hc2（0.6.0 候选） | ccx 28/30（干净行 25/27）、$0.088、168 秒；自己做和自带未重跑；0/19 误报，上界约 15% | [hc2](research/2026-11-04-hc2-holdout.zh.md) |
| pg3b 收据 | 普通 `ok` 收据 0 张：测不到 2% 门槛，证据不足；29 张 `ok_self_checked` 中 15 张隐藏测试不过，审查 29 张全给 pass | [pg3b](research/2026-11-03-pg3b-receipts.zh.md) |
| hc1（历史，旧代码） | 自己做 29/30、$0.090、21 秒；自带默认 27/28、$0.103、123 秒；ccx 29/30、$0.063、61 秒；逐点规则，不是统计非劣效 | [hc1](research/2026-10-29-hc1-holdout.zh.md) |
| Polyglot pg1 | self 25/30，ccx2 12/30；小而接口严格的题留给主导；一种主导/子智能体配置，三行不干净 | [pg1](research/2026-10-31-polyglot-pg1.zh.md) |
| B3 精简开关 | nomem Unknown；clean Fail；leantools 按规则 Fail / 事后解读未定；精简侧均关、实验性；未证明可靠节省 | [B3](research/2026-10-31-b3-lean-switches.zh.md) |
| #158 后收据误报 | 8/209 = 3.8%；排除主导续跑成功的 18 个 8/191 = 4.2%，超过 2% 门槛；这是 #223 之前。#223 之后没有 `done` 收据足够的重测（hc2 只有 6 张） | [审计](research/2026-10-31-verdict-audit.zh.md) |

## 接下来三件

1. **发布 0.6.0：** 标签、全矩阵 CI、GitHub Release 由统筹做；TestPyPI 和 PyPI 等用户配置 token。上 PyPI 后把安装命令改成 `pipx install relayline`。
2. **在本项目和另一个项目真用一周：** 统筹每天看 `ccx report`，只做小修。
3. **都等用户批准：** 在留出集上重跑自己做，把 hc1 → hc2 的上涨分清是代码还是环境；P0-13 discuss A/B（约 $2；[预登记](research/2026-11-03-p13-discuss-prereg.zh.md)，未运行）。

## 把握有多大（简版）

**real** = 真实 Windows 机器、已登录 CLI；**只有 fake** = 假 CLI 测试，不是真实试用。

- **real：** 双向派活、`--check`、审查（第 1–2 轮）、`ccx way`、停止/续跑与被杀运行记账、
  跑完即归档、DeepSeek 主导、三家 discuss、经 `say --resume` 的对话板、共享上下文 A/B、
  hc1（90 个单元、三组）、pg3b 和 hc2（各 30 个单元，只有 ccx）、目录扫描、Claude 插件市场安装（临时配置）、UI 隐藏测试、
  3 任务 batch（#100）、非 ASCII 路径、隐藏控制台、Windows Codex hook（H7，#82/#92）、队列恢复、
  worktree 派活/undo、Codex+dsh 并行 batch、`--fork`、交互式 Codex `say --now`/每轮 hook、
  dsh 退出后写入排队归档；#227 在真实 Claude 桌面统筹收件箱里叫醒；
  Codex 实现 + Codex 审查的四单 PR 流程。
  Codex 实现、Codex + Claude 交叉审查的流程在 #243–#254 上跑过，但有例外：
  #248 缺 Claude 审查（限额）；#250 是统筹 cherry-pick；#244/#246 的修复轮由统筹在沙箱外验收。
- **只有 fake：** 席位；#240 配额排序/自动改派；#241 角色/`other`；#253 就绪判定/刷新范围；#252 一行结果各情况；#249 看板。这些是工程检查，不是真实流程证据。
- **有真实样本，回放：** #245 Claude 限额事件与四条探针成本/窗口读数，每条探针 < $0.005；Codex 拒绝样本仍是合成的；不证明真实自动改派（[样本](../tests/data/real_signals/)）。
- **未验证：** 真实限额时改派、macOS 钥匙串登录就绪判定（无凭据文件记 Unknown）、worktree fetch 在真实离线/慢网络下超时、已安装 `gpt-6.1-terra` 计价；
  macOS/Linux 真机（只有 CI）；Gemini CLI；Codex 桌面 `say --now`、doctor Codex 规则、Codex 叫醒 hook；
  dsh 自己后续写归档、从 GitHub 装 Codex 插件、真实子智能体上限（F11 未触发）、
  `--review auto` 触发率、真实 hook 超时、intake 对 GitHub、L2 自动合并整条链、评测外路由。
  本 worktree 缺少本地 plan-review；`/private/var`、8.3 短名、`\\?\` 前缀的 CI 修复未复核。

### 待本人验证（2026-11-04）

已经超过三条，请先集中清理，再依赖其结果继续。

- #205：分支保护必需检查切到 `ci-ok` + `personal-data`。
- 配置 TestPyPI 和 PyPI token（放 `~/.pypirc` 或单个 shell，不要发到聊天里）。
- 定 Git 历史里的旧个人路径（`git log -S`）留不留：统筹倾向留。
- 决定全局 `worktree.location` 用 `inside` 还是 `sibling`（无项目级设置）。
- 确认 GitHub 描述/topics 文字。
- Claude 桌面 app 的 Pinned Git Origins 重新固定。
- 决定是否删本地旧分支 `control/preflight-e2e`、`debug/b4-queue-flake`、`private-history`（以及 #205 合入后的 `claude/silly-fermi` 等）；本次未删。
- 批不批 P0-13（约 $2）或留出集上重跑自己做？现在都没在跑。
