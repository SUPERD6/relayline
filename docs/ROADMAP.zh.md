# 路线图

[English](ROADMAP.md) · 中文 · 更新于 2026-11-25 · 追踪 issue [#528](https://github.com/SUPERD6/relayline/issues/528)

**这是一份活文档。** 它记录 relayline 往哪走、哪些已经证明、哪些还没有。结果改变了计划，就用 PR 更新本文件（和
[ROADMAP.md](ROADMAP.md)），并在文末「[调整记录](#调整记录)」加一行写明原因。每个任务和每个阶段的交接都走 GitHub
issue 或 PR；统筹会话在每个阶段结束时检查一次路线图。追踪 issue（[#528](https://github.com/SUPERD6/relayline/issues/528)）列出各阶段、里程碑和当前状态。证据标签沿用
[工程标准](engineering-standards.zh.md)：*实测*、*工程检查*（假 CLI 或回放）、*未运行*，另加*推算*表示由少量数据算出的数。
日期都是估计：过去的排期一直偏乐观，而最不可控的一项是真实额度事件什么时候来。

## 定位

> Claude Code 额度用完时，让 Codex 在同一个分支上接着把同一件事做完（反过来也行）。「做完」指你选的检查真的跑过并且通过。

这是**目标，还不是事实**。今天的接力要手工敲命令、默认关、包里没有检查命令；*真实*额度事件能不能触发它是*没测*。阶段 2
就是为了让这句话变成真的。

阶段 0 的竞品复核（[#534](https://github.com/SUPERD6/relayline/issues/534)，2026-11-25）有两处更正：

- 换一家接着干已经**不是独有**的了：Orca（约 138k 星）有手动的「一键在另一个 harness 续同一会话」，OpenAI 官方
  `codex-plugin-cc` 有手动的 `/codex:transfer`。还没人做的是这个组合：接力包里带检查命令、*真跑*检查、出回执、记进账本
  （R3 [#522](https://github.com/SUPERD6/relayline/issues/522)、R5 [#524](https://github.com/SUPERD6/relayline/issues/524)），以及「不把『做完了』当真」。
- Claude Code 自己在额度重置后会自动继续（默认开）。所以接力省下的不是「能不能续」，而是等的那几个小时。每个演示和每篇文章都要这样说。

不承诺：每种任务都更快、更省、更准。哪类任务值得派出去，看下面的取舍地图，带实测数据。

## 三层

| 层 | 是什么 | 现在到哪了 | 目标 |
|---|---|---|---|
| 1. 可靠性常开 | 四件 agent 常出的事有人兜底：会忘、会卡、会谎报完成、互相踩 | 会忘：共享上下文和记忆一轮实测 Pass。会卡：只有工程检查。谎报：执行式检查有效，但回执假阳性还没过线。互相踩：worktree 在 Windows 上实测 | ≥ 5 次真实额度事件且 ≥ 80% 接上并做完；回执假阳性 ≤ 2%；共享上下文在 Codex 上凑齐第二轮 Pass |
| 2. 取舍地图 | 一张表：哪类任务用哪种做法能在哪一维赢、其他维最多输多少。分流器照表选，没证明的格默认「自己做」 | 12 格里没有一格已证明 | 发布时：底线格有一次正式判定，肥上下文格有诊断结果，其余格如实标状态 |
| 3. 高级开关藏起来 | 默认路径只留安装、接力、检查与回执、共享记忆、账本；实验开关保留，但不出现在首屏和日常命令里 | `ccx -h` 只列日常命令，`ccx advanced` 列全部；安装要三步 | 一行安装加一条 `ccx setup`；不用记任何命令 |

三层都不删任何东西：「藏」指不放在 README 前两屏、不放在日常命令列表里，集中到一页（[T4-2](https://github.com/SUPERD6/relayline/issues/551)），每个开关标一个标签。

## 取舍地图

**一格** = 一类任务 + 一种做法 + 想赢的那一维。同时满足三条才算*已证明*：在那一维上，对两种原始用法（主导自己做、工具自带子 agent）都明显更好；
其他维的损失不超过事先写死的上限；证据是当前版本、新题、预登记，并且跑过两轮（一轮只算信号）。按这个标准，**今天没有一格已证明**。
串行派活每次实测都更慢（2.7–5.5 倍），从没更准，所以现实目标是「每格赢一维」。

门槛都是提议，写进预登记后才生效。「顺序」是建议的先后，1 最先。

| 格 | 任务类型和做法 | 想赢的维 | 状态（证据） | 要证明的门槛 | 测法 | 花费 | 顺序 | Issue |
|---|---|---|---|---|---|---|---|---|
| 底线 | 装了 ccx、走默认路径 | 不比自己做差 | **没测。** 最近一次相关结果是 Fail（0/30 次派活，花费 1.27 倍，门槛 1.2） | 做对率差的下界 > −0.10；总花费比上界 ≤ 1.1 | 先数装了不用的 token → 离线回放 → 混合题付费对照 | $0，然后 $15–25（推算） | 1 | [#531](https://github.com/SUPERD6/relayline/issues/531) [#544](https://github.com/SUPERD6/relayline/issues/544) [#556](https://github.com/SUPERD6/relayline/issues/556) [#557](https://github.com/SUPERD6/relayline/issues/557) |
| 1 | 小活（自己做 ≤ 3–4 次请求）派出去 | — | **已证伪**：25/30 对 12/30；交接花费约等于自己做 | 正确做法是自己做；要证明的是「判成自己做不多花钱」 | 并入底线 | $0 | 1 | [#545](https://github.com/SUPERD6/relayline/issues/545) |
| 2 | 中等活、短上下文、同家便宜档先试（第二轮 B 组） | 总花费 | **4 道开发题上已证伪**（推算）：花费比约 2.1，墙钟约 3.1 倍。正式第二轮待跑 | 按预登记，四项全过 | 第二轮 B | 约 $26.5，已批 $34.5 | 已排定 | [#536](https://github.com/SUPERD6/relayline/issues/536) |
| 3 | 中到大活、短上下文、跨家便宜子 agent | 总花费 | **线索互相矛盾**：0.70 倍（旧代码）、0.55–0.62 倍（开发集）；也有更贵或做对率掉的 | 总花费比上界 ≤ 0.8；做对率下界 > −0.15 | 在已有数据上算神谕上界，不单开评测 | $0 | 6 | [#544](https://github.com/SUPERD6/relayline/issues/544) |
| 4 | 长活 + 肥上下文 + 跨家 | 主导那家的额度 | **有线索，按真实条件没测**：主导自身花费 0.24 倍，主导 token −54%。见下面「真实主导上下文」 | 主导那家花费的几何平均上界 ≤ 0.6；护栏：总花费 ≤ 1.2 倍、做对率下界 > −0.15、墙钟 ≤ 3 倍；并且不比自带子 agent 差 | 肥上下文三臂诊断，过了再新题确认 | $15–25，然后 $30–55 | 2 | [#546](https://github.com/SUPERD6/relayline/issues/546) [#547](https://github.com/SUPERD6/relayline/issues/547) [#560](https://github.com/SUPERD6/relayline/issues/560) |
| 5 | 一批说明清楚的机械小活，打包成一次便宜运行 | 省，也可能更快 | **有线索**：十块一次做完全对，$0.004–0.005，68–83 秒。对「自己做」没测 | 总花费比上界 ≤ 0.8；做对率下界 > −0.15；墙钟照报 | 10–15 批，两臂 | $5–8 | 4 | [#548](https://github.com/SUPERD6/relayline/issues/548) |
| 6 | ≥ 4 块互不相关的大块并行派 | 更快 | **有线索**：10 路 29–31 秒对 1 路 68–83 秒，token 7.4 倍；对照不是自己做，块也都很小 | 墙钟中位比 ≤ 0.7，做对率不降；token 倍数照报，不设 1.2 倍护栏 | 等真实使用显示确有可拆的大活 | $15–25 | 发布后 | [#564](https://github.com/SUPERD6/relayline/issues/564) |
| 7 | 高风险改动 + 别家阅读式审查 | 更准 | **已证伪倾向**：29 张自检回执 15 张错，审查全放过 | 从地图上划掉 | 不测 | — | — | — |
| 8 | 高风险改动 + 执行式敏感检查 | 更准（回执可信） | **没测**（B 组是第一次真跑） | 回执假阳性点估计 ≤ 2% 且上界 ≤ 5% | 用 B 组的行 | $0 | 3 | [#538](https://github.com/SUPERD6/relayline/issues/538) |
| 9 | 派活时带共享上下文和记忆 | 派出去不掉准确率 | **实测一轮 Pass**：上下文 4/21 → 20/21，记忆 2/18 → 16/18（用过的最有利题，Codex 子 agent）。比的是带不带上下文，不是比自己做更准 | 精确 McNemar，Holm 校正后显著 | 第二轮 A 组 | 约 $2 | 已排定 | [#536](https://github.com/SUPERD6/relayline/issues/536) |
| 10 | 额度用完，换一家接着干 | 更快（少等） | **没测。** 原始做法是等重置后自动续 | ≥ 5 次真实事件，≥ 80% 接上并做完；另报少等了多久 | 记自然事件（不可能有对照臂） | $0 | 一直在攒 | R1–R8（[#520](https://github.com/SUPERD6/relayline/issues/520)–[#527](https://github.com/SUPERD6/relayline/issues/527)）、[#541](https://github.com/SUPERD6/relayline/issues/541) |
| 11 | 主导上下文太肥时接力到新会话 | 省主导额度 | **没测。** 线索：主导花费的 99% 是重读 | 只能做前后对比，最多到「有线索」 | 每周重算「每次请求重读多少」 | $0 | 5 | [#532](https://github.com/SUPERD6/relayline/issues/532) |

### 分流器（草案，没有格过线之前全部默认关）

分流器不是新模型，而是主导开工前看得到的一小段规则，加上 `ccx` 里现成的几个判断。三条硬要求：判成「自己做」必须零成本（主导自己判断，不调
`ccx`）；拿不准就自己做；先用阈值规则，不用学出来的模型。草案规则：额度事件 → 第 10 格；主导上下文超过阈值 → 提示接力（只提示）；长活 + 肥上下文 +
有能看见新要求的检查 → 第 4 格；≥ 5 个说明清楚的机械小活 → 第 5 格；≥ 4 块互不相关的大块 → 第 6 格；高风险 → 自己做加敏感检查；其他情况或任何输入拿不到 →
自己做。阈值（约 10 次请求、上下文多大、5 个、4 块）是暂定值，由离线回放和诊断来定。底线的道理：所有格都关着时，分流器就等于「自己做」，底线只剩装了不用的开销。

## 阶段 0 实测数据（2026-11-25）

所有美元都是 **API 等价美元**，不是账单。详细报告由统筹本地保存，结论写在对应的已关闭 issue 里。

| 数 | 值 | 取代 | 出处 |
|---|---|---|---|
| 评测累计花费 | **$101.92**：结果文件 $98.10 + 主账本带 `eval-` 标签的运行 $3.82 | 「约 $182」 | 账本核对，[#529](https://github.com/SUPERD6/relayline/issues/529) |
| 第二轮正式评测目前花费 | $0（只做过 dry-run） | — | [#529](https://github.com/SUPERD6/relayline/issues/529)、[STATUS](STATUS.zh.md) |
| 真实主导每次请求重读（cache read 中位数） | **225,389** token；输入总量中位 228,362；p25 152,060、p75 358,902、p90 545,958；40,242 次请求、706 个会话，2026-10-23 至 11-25；每周中位 15.1 万到 28.4 万；本仓库主目录中位 304,944 | 35.2 万（10 月某一周） | [#532](https://github.com/SUPERD6/relayline/issues/532) |
| 装了不用的开销（主导第一次请求） | 全新默认安装约 710 token（600–1,310），维护者本机约 470；占 225k 的 0.31% / 0.21%；最坏约 1,700 = 0.75%（推算，±30%） | — | [#531](https://github.com/SUPERD6/relayline/issues/531) |
| 派活开销分解（26 个单元，推算） | 主导交接 花费 22.7% / 时间 5.2%；干活 37.3% / 62.5%；检查和审查 3.3% / 13.9%；修复或升档 36.7% / 18.0% | — | [#530](https://github.com/SUPERD6/relayline/issues/530) |
| 日常 A/B 抽样（约 10% 可派任务自己做） | 0 条 | — | [#532](https://github.com/SUPERD6/relayline/issues/532) |

**$182 为什么不对。** 它在仓库任何文件里都没有出处，账本也复现不出来。仓库里只有两个统筹估算（11-07 的 $154、11-16 的约 $165）。按评测口径账本是
$101.92（少 $80.08）；按「所有派活」口径是 $358.48（多算了按 token 估价的 Codex 子 agent $237.44，那不是账单）。两个都不等于 $182；从 $165 到 $182
的 $17 增量在账本里没有来源（Unknown）。以后按评测口径和脚本汇总的结果文件管预算。

**225k 重读改变了什么。** 原方案把肥上下文诊断设在 352k token。实测中位更低，而且每周都在变，所以诊断改为灌到**约 225k 的主档**（重读中位），再加一个约
360k 的可选重档（总输入 p75），并报告每周的波动。暂定的「装了不用的开销 ≤ 中位请求的 1%」判断线从约 3,500 token 变成约 2,250 token；实测开销仍然过线。
全新评测会话每次请求重读约 1–3 万，所以「评测里的『自己做』基线比真实使用便宜得多」这个判断仍成立，大约差一个量级。限制：一台机器、一个用户；窗口从
2026-10-23 起，352k 对应的那一周无法重算；Codex 主导的会话没有重算（Unknown）。

## 预算

| 项 | 评测花费（API 等价美元） | 出处 |
|---|---|---|
| 已花 | **$101.92**（账本核对；原为「约 $182」） | [#529](https://github.com/SUPERD6/relayline/issues/529) |
| 第二轮正式组 | 约 $29，最坏约 $41（推算）；报告和审查 ≤ $8 | [预登记](research/prereg/2026-11-16-round2.md) |
| 肥上下文诊断 | $15–25（推算，很可能偏低：先冒烟，$25 买不到 12 道就停） | [#547](https://github.com/SUPERD6/relayline/issues/547) |
| 机械小活打包实验 | $5–8（推算） | [#548](https://github.com/SUPERD6/relayline/issues/548) |
| 底线对照（混合题） | $15–25（推算） | [#557](https://github.com/SUPERD6/relayline/issues/557) |
| 确认轮（有条件） | $30–45，加选题约 $10（推算） | [#560](https://github.com/SUPERD6/relayline/issues/560) |
| 到发布新增 | 约 $94–162 | 以上各行之和 |
| 到发布累计 | 约 **$196–264**；距 $450 上限还剩 $186–254 | $101.92 + 新增 |
| 发布后可选 | 并行格 $15–25；改默认前的确认 $20–40 | [#564](https://github.com/SUPERD6/relayline/issues/564) [#565](https://github.com/SUPERD6/relayline/issues/565) |

$450 是硬上限，只有维护者能提。累计到 $380 时统筹停下来汇报剩余计划。每次评测开跑前先用冒烟或开发题量出单价，超线就停。

## 阶段

工作方式：统筹只统筹，每件活开子会话；一个 issue 一个 PR；每个 PR 由新开的只读 agent 独立审查。模型：实现和文档用中档；高风险审查（超过 300 行、跨 3
个以上源文件、或动 `ccx/delegate.py`、接力启动路径）和花钱的评测用最强档；只读巡查用便宜档。评测窗口里评测机器不跑 pytest，所以实现类子会话白天做、评测夜里跑。
每个任务的 issue 写明模型、验收和依赖。

| 阶段 | 日期（估计） | 目标 | 验收 | 里程碑 |
|---|---|---|---|---|
| 0. 不花钱打底 | 11-25 – 11-30 | 先免费拿到后面决定要用的数；把方案拆成 issue | 五份只读结果；issue 和里程碑建好 | [阶段 0](https://github.com/SUPERD6/relayline/milestone/2) |
| 1. 第二轮照登记跑完 | 11-27 – 12-06 | 五组都有判定 | 不改门槛和题；每组存档后才开下一组 | [阶段 1](https://github.com/SUPERD6/relayline/milestone/3) |
| 2. 接力真跑通，一行装得上 | 12-01 – 12-13 | 有一次完整记录的真实接力；别人能一行装上最新版 | 一页真实额度事件记录，字段全部来自真实文件；0.8.0 可装 | [阶段 2](https://github.com/SUPERD6/relayline/milestone/1) |
| 3. 地图第一版 | 12-07 – 12-20 | 每格有今天的状态；分流规则 v0 有离线数字；第 4 格有诊断 | 回放、神谕上界、诊断和 `docs/map.md` 发布 | [阶段 3](https://github.com/SUPERD6/relayline/milestone/4) |
| 4. 简化、首屏、软发布 | 12-14 – 12-22 | README 首屏、高级开关一页、setup 一问、小范围验证 | README 链接仍是绝对地址；没删任何命令或开关；走查分钟数有记录 | [阶段 4](https://github.com/SUPERD6/relayline/milestone/5) |
| 5. 底线对照和文章 | 12-28 – 01-10 | 底线判定；诚实数据文章；01-09 信号闸门 | Pass/Fail/Unknown；文章每个数字有样本量、版本、日期、限制和链接 | [阶段 5](https://github.com/SUPERD6/relayline/milestone/6) |
| 6. 确认轮和公开发布 | 01-11 – 01-24 | 诊断够格就跑确认轮；01-19 公开发布 | README、文章、地图页一致；每个外部 issue 24 小时内有回应 | [阶段 6](https://github.com/SUPERD6/relayline/milestone/7) |
| 7. 发布后 | 01-25 – 02-28 | 技术报告、并行格、默认值决策、1.0 | 每次改默认都有决策记录和两份报告 | [阶段 7](https://github.com/SUPERD6/relayline/milestone/8) |

### 阶段 0：不花钱打底（除 T0-7 外已完成）
[#529](https://github.com/SUPERD6/relayline/issues/529) 花费对账 · [#530](https://github.com/SUPERD6/relayline/issues/530) 开销分解 · [#531](https://github.com/SUPERD6/relayline/issues/531) 装了不用的开销 · [#532](https://github.com/SUPERD6/relayline/issues/532) 真实使用现状 ·
[#533](https://github.com/SUPERD6/relayline/issues/533) 接力差距核对（R1–R8，[#520](https://github.com/SUPERD6/relayline/issues/520)–[#527](https://github.com/SUPERD6/relayline/issues/527)）· [#534](https://github.com/SUPERD6/relayline/issues/534) 竞品复核 · [#535](https://github.com/SUPERD6/relayline/issues/535) 本路线图。
T0-1 到 T0-6 建成已关闭的 issue 留痕，结论写在正文里，这样数字不依赖统筹的本地文件。

### 阶段 1：第二轮照登记跑完
[#536](https://github.com/SUPERD6/relayline/issues/536) 登记正式 PIN 后按 A1 → A2 → A1x → A2x → B 一次一组跑 · [#537](https://github.com/SUPERD6/relayline/issues/537) 报告 · [#538](https://github.com/SUPERD6/relayline/issues/538) 用 B 组算回执假阳性 ·
[#539](https://github.com/SUPERD6/relayline/issues/539) 用 B 组的行回放两条规则 · [#540](https://github.com/SUPERD6/relayline/issues/540) STATUS。
结果怎么接（在看到任何结果之前就定下）：A1x/A2x Pass → 共享上下文和记忆在 Codex 上两轮 Pass，可带限制对外引用；A 组 Fail → 证据退回一轮，不加钱重跑；
B Fail（预计最可能：墙钟门槛 ≤ 2 倍，而以往每次都是 2.7–5.5 倍）→「同家便宜首轮」标「已测，不推荐」，功能保留，B 组的行拿去做回放和假阳性，
剩下的一次改进机会留给第 4 格的跨家版本；B Pass → 如实记录，按预登记进确认轮；普通 `ok` 回执不到 59 张 → Unknown，继续攒。

### 阶段 2：接力真跑通
八件事：[#520](https://github.com/SUPERD6/relayline/issues/520) 真实事件登记模板 · [#521](https://github.com/SUPERD6/relayline/issues/521) 目标自动带上 · [#522](https://github.com/SUPERD6/relayline/issues/522) 包里带检查命令并出执行式回执 · [#523](https://github.com/SUPERD6/relayline/issues/523) 另一家会话开场提示 ·
[#524](https://github.com/SUPERD6/relayline/issues/524) 接力路径记账 · [#525](https://github.com/SUPERD6/relayline/issues/525) Codex → Claude 方向（Codex hooks 文档里没有额度钩子，只能覆盖 `ccx` 启动的 Codex 会话）· [#526](https://github.com/SUPERD6/relayline/issues/526) 每日额度事件页与 R1 一致 ·
[#527](https://github.com/SUPERD6/relayline/issues/527) `docs/relay.md` 开头重写成三步。R1 现在就能开，只等事件；R2、R3 必须在验证帖之前完成；R4 最好完成；R5–R8 可以放到信号闸门之后。另有
[#541](https://github.com/SUPERD6/relayline/issues/541) 真实使用日页 · [#542](https://github.com/SUPERD6/relayline/issues/542) 0.8.0 发版准备（发 PyPI 由维护者本人做，agent 不碰凭据）· [#543](https://github.com/SUPERD6/relayline/issues/543) setup 与 Codex 插件走查。这两周除了本表和真实使用里碰到的问题，不合入新功能；新的接力行为默认关。

### 阶段 3：地图第一版
[#544](https://github.com/SUPERD6/relayline/issues/544) 离线回放和神谕上界 · [#545](https://github.com/SUPERD6/relayline/issues/545) 分流规则 v0 · [#546](https://github.com/SUPERD6/relayline/issues/546) 诊断评测臂 · [#547](https://github.com/SUPERD6/relayline/issues/547) 诊断运行 · [#548](https://github.com/SUPERD6/relayline/issues/548) 机械小活打包实验 · [#549](https://github.com/SUPERD6/relayline/issues/549) `docs/map.md`。

### 阶段 4：简化、首屏、软发布
[#550](https://github.com/SUPERD6/relayline/issues/550) README 首屏 · [#551](https://github.com/SUPERD6/relayline/issues/551) `docs/advanced.md` · [#552](https://github.com/SUPERD6/relayline/issues/552) setup 一问 · [#553](https://github.com/SUPERD6/relayline/issues/553) 真实事件的 60 秒演示 · [#554](https://github.com/SUPERD6/relayline/issues/554) 验证帖草稿（人看过并发出，agent 只起草）·
[#555](https://github.com/SUPERD6/relayline/issues/555) 新手走查。演示必须录真实事件，写日期、两个 CLI 版本和提交号；不拿回放冒充真实。

### 阶段 5：底线对照和文章
[#556](https://github.com/SUPERD6/relayline/issues/556) 预登记 · [#557](https://github.com/SUPERD6/relayline/issues/557) 运行 · [#558](https://github.com/SUPERD6/relayline/issues/558) 文章初稿 · [#559](https://github.com/SUPERD6/relayline/issues/559) 信号闸门。底线若 **Fail**，这是最严重的结果：停所有新功能，先把默认路径改保守（需决策记录），首屏不能写「不比原始的差」。

### 阶段 6：确认轮和公开发布
[#560](https://github.com/SUPERD6/relayline/issues/560) 确认轮（仅当诊断过了进入条件：主导那家花费比 ≤ 0.7，做对数不少于自己做减 2，不比自带子 agent 臂差；没过就不跑，第 4 格写「诊断未见优势」，效率主张收到「不添乱」）·
[#561](https://github.com/SUPERD6/relayline/issues/561) 公开发布 · [#562](https://github.com/SUPERD6/relayline/issues/562) 发布当天巡查。

### 阶段 7：发布后
[#563](https://github.com/SUPERD6/relayline/issues/563) 技术报告（主线：委派评测里的基线偏差；先做文献检索）· [#564](https://github.com/SUPERD6/relayline/issues/564) 并行格（有条件）· [#565](https://github.com/SUPERD6/relayline/issues/565) 默认值变更（每个一条决策记录）· [#566](https://github.com/SUPERD6/relayline/issues/566) 别家当主导的对照 ·
[#567](https://github.com/SUPERD6/relayline/issues/567) 1.0（要底线两轮 Pass 和 5 次真实接力事件）。

## 闸门和退路

| 闸门 | 继续公开发布 | 含糊 | 没信号 |
|---|---|---|---|
| 明确说「我也要」「我也遇到」的独立用户 | ≥ 10 | 3–9 | ≤ 2 |
| 装上并跑通一次的外部用户 | ≥ 3 | 1–2 | 0 |
| 被追问的方向 | 多数在问接力本身 | 分散 | 多数说「我再买一个订阅就行」 |
| 星（只作参考） | ≥ 50 | 10–49 | < 10 |

这些线是统筹的提议，依据同类小项目的量级，不是外部基准。01-09 闸门：有信号 → 01-19 发布；含糊 → 只改包装（标题、动图、安装），在另一处再发一次，两周后再看，只做一次；
没信号且多数说「再买一个订阅」→ 停止为接力加功能，退回「个人工具 + 一份诚实的评测报告」；没信号但追问集中在别处 → 用被追问的那件事做下一个两周验证，最多换一次切口。

其他退出条件：到 12-20 仍没有真实额度事件 → 验证帖推迟（不拿回放冒充真实）；真实事件里钩子始终不触发 → 最多修两轮，然后改成半自动的「说一句接力」，并去掉「自动」两个字；
官方做了跨厂商接力 → 立刻重估；底线 Fail → 见阶段 5；任何一次真实事件出现两个 agent 同时写同一分支 → 把接力从 setup 推荐项里拿掉，直到修好并有测试；累计到 $380 → 停下汇报。
时间滑了一周以上就砍范围不砍纪律：先砍机械小活实验，再砍确认轮（移到发布后），最后才动发布日期。

## 交接规则

1. 每个任务和每个阶段的交接都走 GitHub issue 或 PR：issue 写明做什么、验收标准、用什么模型、依赖，并链到追踪 issue（[#528](https://github.com/SUPERD6/relayline/issues/528)）。
2. 结果改变了计划，就用 PR 更新本文件和它的英文版，并在调整记录里写一行原因。预登记、冻结的数据和已登记的 SHA 的修改走它们自己的规则，不在本文件里改。
3. 统筹会话在每个阶段结束时检查一次路线图，并在记录里写一行（没有变化也写）。
4. 对外说的话遵守[工程标准](engineering-standards.zh.md)：没有样本量、版本、日期、限制和报告链接的数字不说。

## 调整记录

| 日期 | 改了什么 | 为什么 | 在哪 |
|---|---|---|---|
| 2026-11-25 | 首个公开版本：定位、三层、12 格地图、阶段 0–7、issue 和里程碑 | 让方案能通过 PR 随时调整；追踪 issue [#528](https://github.com/SUPERD6/relayline/issues/528) | [#535](https://github.com/SUPERD6/relayline/issues/535) |
| 2026-11-25 | 已花改为 $101.92（原约 $182），剩余预算 $348.08（到发布累计 $196–264） | 账本核对：$182 没有出处 | [#529](https://github.com/SUPERD6/relayline/issues/529) |
| 2026-11-25 | 肥上下文诊断改为约 225k 主档（重档约 360k），原为 352k；装了不用的判断线约 2,250 token | 实测真实主导重读中位 225,389（2026-10-23 至 11-25） | [#532](https://github.com/SUPERD6/relayline/issues/532) [#531](https://github.com/SUPERD6/relayline/issues/531) |
| 2026-11-25 | 更正「换一家接着干没有高星项目」；差异化收窄为接力包 + 执行式检查 + 回执 + 账本 | 查到 Orca 和 `/codex:transfer`；官方更新日志里没有自动跨厂商接力 | [#534](https://github.com/SUPERD6/relayline/issues/534) |
