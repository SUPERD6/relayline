# 进度

[English](STATUS.md) · 中文 · 更新于 2026-11-01 · 版本 0.5.0 + Unreleased（#105–#241）· 收集到 2245 个测试；未重跑全量

供接手时读的一页。历史与旧把握程度表见[归档](STATUS-archive.zh.md)；改动见
[CHANGELOG](../CHANGELOG.md) 和[各 PR 记录](../changes/README.zh.md)。本页由统筹维护。

## 现在

**留出集运行 hc1（2026-10-29，预先登记）：** 在做 ccx 时没用过的 10 个任务上，ccx 未见正确率更差（29/30，自己做 29/30，
自带子智能体默认用法 27/28），每次成功 $0.063，约低 30% / 39%；用时约为自己做的 3 倍。限制：精简做法 builtin2 不在这次运行里，
本仓库任务可能泄漏答案（只看外部任务：15% / 42%），只有 10 个任务、一种主导模型。

**10-30 → 11-01 的收尾合入，按八层列出**（PR 细节见[变更记录](../changes/README.zh.md)）：

- **① 对话：** #227 叫醒默认开（Claude 收件箱真机试过，Codex hook 实验性）；#237 干净通过默认一行结果；#238 提示瘦身默认开、实验性；#239 固定规则前缀缓存对齐，未实测节省。
- **② 记忆：** #195 共享上下文去重为实验性，默认关。
- **③ 拆分：** #194 原生 Codex 子会话不带历史、#196 batch 合并均为实验性，默认关。
- **④ 派活与选人：** #200/#234 `small_self` 默认关（默认 `files`，可选 `cost`），`routing.mode=auto`；#230 能力表只建议、不接路由；#240 配额感知默认开（仅 fake）；#241 角色表自选、默认空表，项目角色 check 只展示。
- **⑤ 验收与收据：** #211 展示覆盖与来源；#212 覆盖 rubric 默认开，自写测试不算独立证据；#223 仅自测通过标 `ok_self_checked`、默认送审；#215 `[must]` 复现门禁实验性/默认关；#235 `--max-usd` 默认 0（不限）；#232 API 美元 + 配额单位，默认 `api`。
- **⑥ 控制：** #231 worktree 默认 `sibling`，`inside` 自选/实验性；#193 worktree 竞态重试；#197 切换 hub 有门禁；#219 评测金丝雀默认开；#220 沙箱授权取消按 `env` 停止，续跑需 `--env-fixed`。
- **⑦ 测量与诚实：** #199 精简开关保持关；#221 polyglot 负结果；#209 收据审计 8/209；#216 公开 `bench/`；#204 评测/开发共用一台机器一个账号仍有限制。
- **⑧ 界面与上手：** 可选 `ccx ui`：#226 项目地图首页，#233 运行视图与预览/确认对话框；#202 隔离 demo；#207/#208/#210/#218 GIF/截图/架构图/网站；#228 README 八层。

**安全：** #225 记录威胁模型、控制与剩余风险，不新增执行权限。

| 测量 | 结果与限制 | 出处 |
|---|---|---|
| hc1 | 自己做 29/30、$0.090、21 秒；自带默认 27/28、$0.103、123 秒；ccx 29/30、$0.063、61 秒；ccx 的两个配对花费差区间不含 0（自带 − 自己做的含 0）；逐点规则，不是统计非劣检验 | [hc1](research/2026-10-29-hc1-holdout.zh.md) |
| Polyglot pg1 | self 25/30，ccx2 12/30；小而接口严格的题留给主导；一种主导/子智能体配置，三行不干净 | [pg1](research/2026-10-31-polyglot-pg1.zh.md) |
| B3 精简开关 | nomem Unknown；clean Fail；leantools 按规则 Fail / 事后解读未定；精简侧均关、实验性；未证明可靠节省 | [B3](research/2026-10-31-b3-lean-switches.zh.md) |
| #158 后收据误报 | 报告口径 8/209 = 3.8%；排除主导续跑成功的 18 个：8/(209−18) = 8/191 = 4.2%，超过 2% 门槛；任务重复、一种主导配置；#223 已合入，**未重跑验证（not re-run）** | [审计](research/2026-10-31-verdict-audit.zh.md) |

## 接下来三件

不定发布日期：先做到每天真用（11-01 的优先顺序）。

1. **在本项目和另一个项目真用一周：** 先配置角色，再用 `ccx run --role build "一句话"`、UI 角色按钮和配额感知；统筹每天读 `ccx report`，小修开 PR。
2. **验证 P0-8 并复查收据误报：** polyglot ccx2 一轮约 $1.4（[pg1](research/2026-10-31-polyglot-pg1.zh.md)）；结果决定 README 收据段能否写数字。未重跑（not re-run）。
3. **其余测量按 release-plan §11 分批：** B3 少跑几趟开关、档位矩阵、大任务五组、外部仓库基准；一次一批，再问发版。

## 把握有多大（简版）

**real** = 真实 Windows 机器、已登录 CLI；**只有 fake** = 假 CLI 测试，不是真实试用。

- **real：** 双向派活、`--check`、审查（第 1–2 轮）、`ccx way`、停止/续跑与被杀运行记账、
  跑完即归档、DeepSeek 主导、三家 discuss、经 `say --resume` 的对话板、共享上下文 A/B、
  hc1（90 个单元、三组）、目录扫描、Claude 插件市场安装（临时配置）、UI 隐藏测试、
  3 任务 batch（#100）、非 ASCII 路径、隐藏控制台、Windows Codex hook（H7，#82/#92）、队列恢复、
  worktree 派活/undo、Codex+dsh 并行 batch、`--fork`、交互式 Codex `say --now`/每轮 hook、
  dsh 退出后写入排队归档；#227 在真实 Claude 桌面统筹收件箱里叫醒；
  Codex 实现 + Codex 审查的四单 PR 流程。
- **只有 fake：** 席位；#240 配额排序/自动改派；#241 角色解析、CLI/UI 检查与 `other` 回退。这些是实际工程测试，不是真实限额/角色流程证据。
- **未验证：** 真实限额时改派、探针真实成本、已安装 `gpt-6.1-terra` 计价；
  macOS/Linux 真机（只有 CI）；Gemini CLI；Codex 桌面 `say --now`、doctor Codex 规则、Codex 叫醒 hook；
  dsh 自己后续写归档、从 GitHub 装 Codex 插件、真实子智能体上限（F11 未触发）、
  `--review auto` 触发率、真实 hook 超时、intake 对 GitHub、L2 自动合并整条链、评测外路由。
  本 worktree 缺少本地 plan-review；`/private/var`、8.3 短名、`\\?\` 前缀的 CI 修复未复核。

### 待本人验证（2026-11-01）

请集中清理这些事项，再依赖其结果继续：

- #205：分支保护必需检查切到 `ci-ok` + `personal-data`。
- 配置 test.pypi token。
- 决定全局 `worktree.location` 用 `inside` 还是 `sibling`（无项目级设置）。
- 确认 GitHub 描述/topics 文字。
- Claude 桌面 app 的 Pinned Git Origins 重新固定。
