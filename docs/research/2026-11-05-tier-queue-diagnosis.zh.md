# 档位与队列离线诊断 — 2026-11-05

[English](2026-11-05-tier-queue-diagnosis.md) · 中文

## 结论与证据范围

不建议先付费把四个标签各测一遍。优先比较 **save 与 balanced 的完整流程**，
选二者实际分工不同的新任务。8 个合成案例中，save 和 cheapest 的模型梯级完全相同，
cheapest 省掉的是主导验收；balanced 在多数案例也选相同模型。fast 与 balanced
在小、中任务的“自己做”策略重合，可以后置。**本报告不支持改任何默认值。**

证据等级全部为 **engineering check**，不是标准所指真实 CLI 的 measured。
版本 `945a8e590caf024c616cb5f65c9f227d8556774c`，日期 2026-11-05，
Windows、Python 3.11.9。真实模型质量、现金节省、最优并发以及 Linux/macOS 表现均为 **Unknown**。
两轮只作诊断信号，无统计推断。

开跑前已把方案写入英文报告，但本单禁止提交，因此不是工程标准第 3 节要求的“已提交预登记”，
不能作为正式评测。使用本单独立 worktree、合成任务、全新隔离 hub/home，未读真实账本或凭据。
未证明机器空闲；相关 pytest 在第 2 轮尾段开始，3 路和 1 路可能与其重叠。
保留这些行，不视为干净对照。串行假 CLI 基线只跑一遍。

## 四档究竟有什么不同

`--tier` 是 auto/T0..T4；save/balanced/fast/cheapest 属于 `--tradeoff` 与 `[policy.*]`。
不能把流程策略与模型梯级混为一谈。

实际调用 `ccx.plan.resolve_role`（无角色时进入 `ccx.commands.common.resolve`），
再进入 `ccx.plan._plan`；决策函数未替换。另通过 `ccx.learn.tier_plan` 调用仓库自带技能的流程策略。
配置/priors 来自当前仓库，学习状态为空；priors 本身含历史标定，不是“完全无先验”。
候选固定 Codex；真实登录、额度压力下跨厂商选择为 Unknown。

下表“谁做”只是策略返回值。默认 `policy.picked` 为空；由提议/主导按策略安排，
不代表 `run` 或 `q run` 自动替主导完成所有分工。强制模型探针设 `force=True`，
因此策略写 self 时仍会返回模型。队列 `_one` 本身也传 `force=True`。
传 `--tradeoff` 不等于授权；用户设置 `policy.picked` 才预授权某次提议的流程，
没有显式 `--tradeoff` 的模型选择仍用 `defaults.tradeoff`。

下表输入依次为分钟、源文件数、主导上下文 token；任务文字为实际合成输入。

| 合成任务 | 分钟 / 文件数 / 主导上下文 | 大小 | save | balanced | fast | cheapest |
|---|---|---|---|---|---|---|
| tiny: Rename a local label | 5 / 1 / 0 | small | ccx2 | self | self | direct |
| medium: Add a cache helper | 15 / 2 / 0 | medium | ccx2 | self | self | direct |
| large-files: Update three independent adapters | 20 / 3 / 0 | large | ccx2 | ccx2 | self | direct |
| large-time: Implement a parser extension | 45 / 1 / 0 | large | ccx2 | ccx2 | self | direct |
| medium-context: Add a cache helper | 15 / 2 / 150000 | medium | ccx2 | ccx2 | self | direct |
| hard-large: Repair resume state machine | 60 / 4 / 0 | large | ccx2 | self | self | direct |
| unknown-size: Investigate a handler | null / 0 / 0 | small | ccx2 | self | self | direct |
| long-brief: 180 repetitions of parser, separated by spaces | 5 / 1 / 0 | large | ccx2 | ccx2 | self | direct |

`self` = 主导自己做；`ccx2` = 派活后主导验收；`direct` = 无主导验收并标 `may_be_wrong`。
hard 关键词优先于大小，其次为不确定大小，再看 medium/大上下文特例。
所以 60 分钟、4 文件的 resume 状态机在 balanced 下仍自己做。
medium 的主导上下文恰好到 150000 时改派 ccx2。分钟和文件数都没给，即使文字很长也算大小不确定。

### 强制派活时的模型与后备梯级

以下是“首选 → 允许的后备”，不代表真的运行过或发生了升级。
L = `codex:gpt-6-luna`，S = `codex:gpt-6.1-sol`，A = `codex:gpt-6-astra`。
均设 write、force、no_ab、最多升级一次，空 roles，诊断配置关闭 readiness/额度路由。

| 合成任务 | 难度 b | save | balanced | fast | cheapest |
|---|---|---|---|---|---|
| tiny | 2.32 | L:low → L:high | L:low → L:high | S:medium → S:high | L:low → L:high |
| medium | 3.91 | S:medium → S:high | S:medium → S:high | S:high → S:xhigh | S:medium → S:high |
| large-files | 4.32 | S:medium → S:high | S:medium → S:high | S:high → S:xhigh | S:medium → S:high |
| large-time | 5.49 | S:high → S:xhigh | S:medium → S:high | A:xhigh → A:max | S:high → S:xhigh |
| medium-context | 3.91 | S:medium → S:high | S:medium → S:high | S:high → S:xhigh | S:medium → S:high |
| hard-large | 5.91 | S:high → S:xhigh | S:high → S:xhigh | A:xhigh → A:max | S:high → S:xhigh |
| unknown-size | Unknown | L:low → S:medium | L:low → S:medium | L:low → S:medium | L:low → S:medium |
| long-brief | 2.32 | L:low → L:high | L:low → L:high | S:medium → S:high | L:low → L:high |

save/cheapest 梯级相同 **8/8**；save/balanced **7/8**；balanced/fast **1/8**。
这只证明决策相同，不证明质量等价。45 分钟案例里 balanced 起点甚至低于 save：
其时间/成本目标和阈值并不保证不同策略之间“逐档变强”。
unknown-size 没有 b，退回关键词路由，因此四档相同。
另实调显式 `--tier T1` 且不给分钟/rubric：四档均为 L:low → S:medium（4/4），模型梯级优先。

### 默认 save 与阈值的依据

`config/tiers.toml:27–29` 与 `docs/DECISIONS.md` 的 2026-10-25 决定记录：
历史七核心 A/B 中，balanced 给 5 分钟小活选 sonnet medium，约为记录中 luna low 的 10 倍花费，
luna low 做对 55/63；后来 check 失败可自动升级。这是仓库记载的历史理由，
本次没有复跑，也不能据此认定当前 save 最优。

流程阈值是第 5 轮导出的暂定规则（`config/tiers.toml:49–65`）：
大任务 ≥3 文件、≥45 分钟或 ≥180 词；中任务 ≥2 文件、≥15 分钟或 ≥80 词；取最大信号。
中文按字符数 /2.5 折词；balanced 的 medium 上下文阈值为 150000；数字旋钮切点 0.34/0.67。
这些边界改变 balanced 的分工，save 本身各类均 ccx2。精确切点的统计依据 **Unknown**，本次不调参。

模型阈值另在 `skills/task-routing/data/priors.toml`：save τ=0.70、允许级联；
balanced τ=0.80、允许级联；fast τ=0.90、不用级联目标；cheapest 经 `ccx/learn.py` 映射 save。
τ 是先验模型估计的成功概率门槛，**不是实测正确率**。
级联在达标链中最小化现金、额度影子价、时间、失败风险之和；
非级联按达标单次选起点，`_plan` 仍可能给升级梯级。τ=0.70 本身的经验标定依据为 **Unknown**。

付费后续建议（不是开跑授权）：预登记 save 对 balanced，新题分小/中任务、hard/resume、
大任务、medium/大上下文；把主导、子任务、审查、重试、合并验收全部算入成本，
用隐藏测试、每做对一项成本、单项中位与累计墙钟验收。保留失败，环境错误另分。
大任务中同策略部分可作对照；不为不同标签反复付费跑相同计划。
cheapest 应先明确“省掉验收会漏多少错”的问题，fast 等 balanced 的 self 基线清楚后再测。

## 10 项假任务的流水线耗时

先写定方案：10 个独立写任务，每项假 CLI 增加 0.2 秒延迟；两轮按 1/3/10、10/3/1 顺序，
每格全新 fixture。跑实际 `q add --plan`、`q run --max N --lanes 0`、
`q accept --all-ready --check ...` 子进程。cwd 为独立 fixture Git 仓库而非源码根；
为守写入范围，fixture 物理位置仍在本单 worktree 内。只有 fixture 仓库生成提交/合并，
源码仓库未提交、推送或切换分支。禁用 fetch、quota probe、benchmark refresh、审查和自动归档。

六批共 **60/60** queue-done、**60/60** 文件最终存在、**60/60** accepted/check-passed；
没有失败或中断的诊断批次。隐藏测试正确率 **Unknown**。
每步 check 只断言至少一个文件，driver 最后断言恰好十个；它验的是管线，不验语义正确。
假 CLI 创建唯一名字文件，声明的所有权文件互不相交。
未覆盖依赖、文件冲突、额度错误、付费 token、warm lanes、后台唤醒或真实主导。

| 轮次 | 并发数 | 队列墙钟秒 | worker 中位秒 | worker 累计秒 | worker 区间并集秒 | 非 worker 剩余秒 | 合并验收秒 | 队列加验收秒 |
|---|---|---|---|---|---|---|---|---|
| 1 | 1 | 14.931 | 0.227 | 2.272 | 2.272 | 12.658 | 4.157 | 19.088 |
| 1 | 3 | 10.357 | 0.242 | 2.405 | 1.897 | 8.460 | 5.863 | 16.221 |
| 1 | 10 | 6.699 | 0.256 | 2.580 | 2.147 | 4.552 | 7.395 | 14.094 |
| 2 | 10 | 7.428 | 0.252 | 2.577 | 2.030 | 5.399 | 6.893 | 14.321 |
| 2 | 3 | 8.581 | 0.230 | 2.317 | 1.520 | 7.061 | 7.079 | 15.660 |
| 2 | 1 | 12.088 | 0.222 | 2.214 | 2.214 | 9.873 | 4.345 | 16.433 |

| 并发数 | 批次队列中位秒（n=2） | 队列累计秒 | 队列加验收中位秒 | 队列加验收累计秒 | 相对 1 路的队列时间比 |
|---|---|---|---|---|---|
| 1 | 13.509 | 27.019 | 17.760 | 35.521 | 1.00× |
| 3 | 9.469 | 18.939 | 15.940 | 31.881 | 1.43× |
| 10 | 7.064 | 14.128 | 14.208 | 28.415 | 1.91× |

单次直接串行假 CLI 基线：10 个进程累计 **3.719 秒**，
含启动、人工延迟和假执行，不含 ccx/Git/check，不能作为功能等价的替代方案。

Worker median 为本批 10 个 worker 区间中位数，sum 为累计；union 将重叠区间只计一次。
非 worker 剩余 = 队列 CLI 墙钟 − worker union，包含暴露出来的启动、路由、记录、Git、调度，
**不是纯调度 CPU，也不是内部开销的全部总和**。CLI 墙钟从启动子进程前到退出后。
accept 包括逐项合并、联合 check、verify 和记账；纯 Git merge 时间 **Unknown**。
版本/login 探针不计 worker 区间，若执行则仍包含在队列总墙钟内。

### 必须保留的路径限制

`ccx.workspace.worktree_repo` 按路径组件识别 worktree。
本单工作区在 `.ccx-worktrees` 下，因此独立 fixture 根也被当成 ccx worktree。
1 路每项在同一 `diagnosis` fixture 分支记提交，accept 重复做已落地/同分支的无操作合并与 check，
**不是十个独立分支的合并**。3/10 路十项均有真实独立 fixture worktree。
因此 1 路 accept 是收尾/check 基线，端到端比值混入了 Git 拓扑差异。
普通目录下的对应时间未重测，为 Unknown，不能隐去这条负面发现。

### 隔离调度器补充诊断

完整路径结束后、补充诊断开跑前固定方案：用真实 `_refill` 和持久队列，10 个 read 项；
仅替换 `_one`，由回调启动计时假 CLI 子进程并更新 doing/done。不走路由、Git、账本、审查或合并。
相关测试结束后，两轮各跑 1/3/10。子进程区间在外部量，包含启动与管道处理。
剩余 = dispatcher wall − subprocess union，代表暴露的调度/队列状态开销，
不是总 CPU，也不包括被其他运行中任务遮住的开销。这是组件检查，不是产品端到端行为。

| 轮次 | 并发数 | 调度器墙钟秒 | 子进程区间并集秒 | 暴露的调度/状态开销秒 |
|---|---|---|---|---|
| 1 | 1 | 3.6978 | 3.4234 | 0.2744 |
| 1 | 3 | 1.6443 | 1.5143 | 0.1299 |
| 1 | 10 | 0.7251 | 0.6424 | 0.0826 |
| 2 | 1 | 3.6094 | 3.3429 | 0.2665 |
| 2 | 3 | 1.5107 | 1.4443 | 0.0663 |
| 2 | 10 | 0.5693 | 0.5064 | 0.0629 |

### 瓶颈与可选改进：只列出，不实现

完整路径中，每项 worker 只有约 0.22–0.26 秒，但队列总墙钟的大部分在这些区间以外。
10 路的 worker union 仍约两秒，没有收敛到一次 worker 时长。
串行 worktree 准备及逐项 Git/状态处理是可能原因（`workspace._worktree_lock`、`_place`、
`_tree_fields`/`lanes.commit_block`）；各项因果占比 **Unknown**，不能把剩余全归罪调度器。
隔离探针只量小队列暴露出来的调度开销，不能从完整路径中直接相减做精确归因。

accept 则明确逐项串行合并、check、记录，是后续吞吐上限。
`scripts/eval/batch.py` 量的是带真实主导、隐藏测试、合并验收及唤醒的整个评测；
其 `--jobs` 指并行评测单元，不是 q 的 worker 宽度。本次不执行它的 `cmd_run`，
因为会启动付费 lead/canary。调它到 10 会改变另一个层次，也违背正式评测一次一个的规则。

| 候选 | 风险与保留条件 | 本次处理 |
|---|---|---|
| 默认关闭的分阶段单调时钟诊断，量 resolve、队列回放/锁等待、worktree、worker、commit、merge、check | 低风险，只增字段，检查兼容与计时自身开销 | 最值得先做的诊断改动；未实现 |
| 文档提示/检查 `.ccx-worktrees` 内嵌独立仓库 | 文档风险低；改识别规则需 nested-repo 回归测试 | 报告限制，不悄改语义 |
| 单次有边界操作内复用队列快照 | 必须保留跨进程写入、锁、依赖、gate、backpressure | 先定位；尚非已证实低风险提速 |
| 同一 refill 减少重复 Git status/clean 探针 | writer 启动仍须核对干净状态与基线 | 有分段证据后考虑 |
| 已落地分支减少重复 Git merge 步骤 | 每项 check、verdict、账本、依赖释放、回滚边界均保留 | 需专项验收测试 |
| 十分支最后只测一次、去 gate、直接加默认并发 | 改失败隔离或负载压力 | 不据此做 |

不改代码即可做：保留当前 3 路默认但不称最优；按真正独立任务与验收能力限制并发；
复用已有多项 accept 命令。没有已证明可以直接低风险提速的产品补丁。

## 复现与验证

英文报告附完整标准库 driver 与补充 dispatcher driver，输入、函数调用与断言均可检查。
新 worktree 上将代码分别保存到 `.diagnosis-local/diagnose.py`、`scheduler_probe.py`；
先跑前者，相关测试与完整路径全部结束后再跑后者，勿复用旧 fixture 目录。
时间受机器负载、文件系统和杀毒影响，不设时间测试断言。
本地原始结果与脚本保存在忽略目录 `.ccx/tier-queue-diagnosis-20261105/`；
含本机路径，不可直接对外发布，以上数字表为去个人信息的交付。

相关测试：`python -m pytest -q tests/test_task_routing.py tests/test_queue_pipeline.py
tests/test_queue_accept.py -k 'tier or parallel_writers or pieces_sharing or accept'`，
**19 passed、52 deselected**，真实退出码 0，用时 123.17 秒；按要求未跑全量。
`python scripts/collect_changes.py --check`：13 个 notes、9 个 decision notes 格式通过，退出码 0。
本单只交付报告和 changes；产品命令、选项、JSON 字段含义、
退出码、判定、默认值与配置结构均未改。真实模型、远端 CI、跨平台、科学结论均未验证。
