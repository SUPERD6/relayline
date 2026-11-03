# 进度

[English](STATUS.md) · 中文 · 更新于 2026-11-03 · 版本 0.5.0 + Unreleased（#105–#253）· 收集到 2417 个测试；未重跑全量

供接手时读的一页。历史与旧把握程度表见[归档](STATUS-archive.zh.md)；改动见
[CHANGELOG](../CHANGELOG.md) 和[各 PR 记录](../changes/README.zh.md)。本页由统筹维护。

## 现在

**留出集运行 hc1（2026-10-29，预先登记）：** 在做 ccx 时没用过的 10 个任务上，ccx 未见正确率更差（29/30，自己做 29/30，
自带子智能体默认用法 27/28），每次成功 $0.063，约低 30% / 39%；用时约为自己做的 3 倍。限制：精简做法 builtin2 不在这次运行里，
本仓库任务可能泄漏答案（只看外部任务：15% / 42%），只有 10 个任务、一种主导模型。

**10-30 → 11-01 八层收尾：** 细节见[变更记录](../changes/README.zh.md)。
① 叫醒/一行结果/提示瘦身默认开（Codex 叫醒 hook 与瘦身实验性）；② 记忆去重、③ 无历史子会话/batch 合并实验性、默认关；④ `routing.mode=auto`，`small_self` 关，能力表只建议，配额感知开，角色自选/空表。
⑤ 覆盖 rubric/审查默认开，自写测试非独立证据，保留 `ok_self_checked`，复现门禁关，预算 0/不限，计费 `api`；⑥ worktree 默认 `sibling`、金丝雀开、取消后需 `--env-fixed`；⑦ 精简开关关、保留负结果；⑧ 可选 UI，含项目地图、运行视图与预览/确认。

**11-03 合入了什么**（#243–#253 共 11 个 PR；#250 汇集五个审查修复轮）：

- **⑤ 收据 #252：** agent/model/effort 记最终执行者；改派、预算停下、审查未跑进主导一行，auto-effort 依据可见。默认生效；退出码与 `ok_self_checked` 不变。
- **④ 就绪 #253：** `routing.require_ready=true` 默认优先已安装且有登录证据的 CLI；明确未就绪只降序，缺文件的 Unknown 不降序。刷新探候选（显式或角色限定目标只探该家，否则 Claude/Codex），不只探最终选中者；角色空态给示例。角色仍自选/空表，保留原回退。
- **⑧ 每日 UI #249：** 预算停审、配额新鲜度/Unknown、今天花费一行、角色按钮多行文本、CLI/UI 模式提示。UI 仍可选；打开页面不探针，保留预览/确认。
- **⑥ 控制 #246/#244：** `[worktree] fetch=true` 默认提示 upstream 落后，不 pull、不移动本地基点；启动器变量默认与验收/执行者/审查子进程隔离，保留后台完整日志。
- **⑦ 证据 #245/#248：** 真实限额事件与探针成本样本已进 fake 回放（每条已记录探针 < $0.005），不改路由默认。P0-13 discuss A/B 脚本与预登记就绪，未加 `--execute` 默认不付费执行；未跑。
- **流程 #243/#251/#247：** 决策走 `changes/<PR>.decision.md`，relayline 路径用 `workspace.canonical()`；统一 changes 措辞、维护页列发布后候选。只改文档/流程，运行默认不变，不升版本、不发布。

**安全：** #225 记录威胁模型、控制与剩余风险，不新增执行权限。

| 测量 | 结果与限制 | 出处 |
|---|---|---|
| hc1 | 自己做 29/30、$0.090、21 秒；自带默认 27/28、$0.103、123 秒；ccx 29/30、$0.063、61 秒；ccx 的两个配对花费差区间不含 0（自带 − 自己做的含 0）；逐点规则，不是统计非劣检验 | [hc1](research/2026-10-29-hc1-holdout.zh.md) |
| Polyglot pg1 | self 25/30，ccx2 12/30；小而接口严格的题留给主导；一种主导/子智能体配置，三行不干净 | [pg1](research/2026-10-31-polyglot-pg1.zh.md) |
| B3 精简开关 | nomem Unknown；clean Fail；leantools 按规则 Fail / 事后解读未定；精简侧均关、实验性；未证明可靠节省 | [B3](research/2026-10-31-b3-lean-switches.zh.md) |
| #158 后收据误报 | 报告口径 8/209 = 3.8%；排除主导续跑成功的 18 个：8/(209−18) = 8/191 = 4.2%，超过 2% 门槛；任务重复、一种主导配置；#223 已合入，**未重跑验证（not re-run）** | [审计](research/2026-10-31-verdict-audit.zh.md) |

## 接下来三件

不定发布日期：先做到每天真用（11-03 优先顺序）。

1. **在本项目和另一个项目真用一周：** 角色表、配额感知、UI 每日看板、收据一行；统筹每天看 `ccx report`，只做小修。
2. **都等用户批准：** P0-8 验证 + 收据误报复查（约 $1.4；[pg1](research/2026-10-31-polyglot-pg1.zh.md)，not re-run），以及 P0-13 discuss A/B（约 $2；[预登记](research/2026-11-03-p13-discuss-prereg.zh.md)，未跑）。脚本已就绪：`python scripts/eval/p13_discuss.py run --execute --tag p13-r1 --wait-quiet 30 --budget 2`。
3. **其余测量按本地 release-plan §11 批次（计划约 $49）：** B3 开关、档位矩阵、大任务五组、外部基准及最终留出集回归；每批获批后再跑，最后问发版。这个计划总额含 P0-8，不重复相加。

## 把握有多大（简版）

**real** = 真实 Windows 机器、已登录 CLI；**只有 fake** = 假 CLI 测试，不是真实试用。

- **real：** 双向派活、`--check`、审查（第 1–2 轮）、`ccx way`、停止/续跑与被杀运行记账、
  跑完即归档、DeepSeek 主导、三家 discuss、经 `say --resume` 的对话板、共享上下文 A/B、
  hc1（90 个单元、三组）、目录扫描、Claude 插件市场安装（临时配置）、UI 隐藏测试、
  3 任务 batch（#100）、非 ASCII 路径、隐藏控制台、Windows Codex hook（H7，#82/#92）、队列恢复、
  worktree 派活/undo、Codex+dsh 并行 batch、`--fork`、交互式 Codex `say --now`/每轮 hook、
  dsh 退出后写入排队归档；#227 在真实 Claude 桌面统筹收件箱里叫醒；
  11-03 的 11 单 PR 流程：Codex 实现、Codex/Claude 交叉审查；启动器隔离在真实 `--bg` 验收中生效
  （#252 验收含 leadview 测试通过；沿用验收记录，本次 not re-run）。
- **只有 fake：** 席位；#240 配额排序/自动改派；#241 角色/`other`；#253 就绪判定/刷新范围；#252 一行结果各情况；#249 看板。这些是工程检查，不是真实流程证据。
- **有真实样本，回放：** #245 Claude 限额事件与四条探针成本/窗口读数，每条探针 < $0.005；不证明真实自动改派（[记录](../changes/245.md)）。
- **未验证：** 真实限额时改派、macOS 钥匙串登录就绪判定（无凭据文件记 Unknown）、worktree fetch 在真实离线/慢网络下超时、已安装 `gpt-6.1-terra` 计价；
  macOS/Linux 真机（只有 CI）；Gemini CLI；Codex 桌面 `say --now`、doctor Codex 规则、Codex 叫醒 hook；
  dsh 自己后续写归档、从 GitHub 装 Codex 插件、真实子智能体上限（F11 未触发）、
  `--review auto` 触发率、真实 hook 超时、intake 对 GitHub、L2 自动合并整条链、评测外路由。
  本 worktree 缺少本地 plan-review；`/private/var`、8.3 短名、`\\?\` 前缀的 CI 修复未复核。

### 待本人验证（2026-11-03）

已经超过三条，请先集中清理，再依赖其结果继续。

- #205：分支保护必需检查切到 `ci-ok` + `personal-data`。
- 配置 test.pypi token。
- 决定全局 `worktree.location` 用 `inside` 还是 `sibling`（无项目级设置）。
- 确认 GitHub 描述/topics 文字。
- Claude 桌面 app 的 Pinned Git Origins 重新固定。
- 决定是否删本地旧分支 `control/preflight-e2e`、`debug/b4-queue-flake`、`private-history`（以及 #205 合入后的 `claude/silly-fermi` 等）；本次未删。
- P0-8 + P0-13 两项小测量约 $3.4，现在批准跑吗？本次均未跑。
