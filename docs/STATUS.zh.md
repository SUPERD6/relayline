# 进度

[English](STATUS.md) · 中文 · 更新于 2026-11-28 · 0.7.0 已打 tag 并建 GitHub Release（没发 PyPI，PyPI 上仍是 0.6.0，2026-11-28 核实）；main 已是 0.8.0，还没打 tag 也没发布

供接手时读的一页，由统筹维护。历史见[归档](STATUS-archive.zh.md)；
改动见 [CHANGELOG](../CHANGELOG.md) 和[各 PR 记录](../changes/README.zh.md)。

## 现在

**已发布：** 0.7.0，2026-11-16：`v0.7.0` tag 打在 #357 的发版提交上（该提交全矩阵 CI 和打包检查全绿），[GitHub Release](https://github.com/SUPERD6/relayline/releases/tag/v0.7.0) 附 wheel 和 sdist；CHANGELOG 的 0.7.0 一节折入了到 #354 为止的 `changes/` 记录；#355、#356、#363 的代码在 tag 里，但记录没折，留在 `changes/` 等下次发版。**还没发 PyPI**（由维护者决定）：`pipx install relayline` 装到的仍是 0.6.0，要用 0.7.0 请从 Release 附件安装。tag 之后合入、尚未发版的：#352、#361、#364、#366、#368、#369，以及 #382 起的全部（见归档和下面“此后合入”）。目标不变（[工程标准](engineering-standards.zh.md)、[优化计划](research/2026-11-04-optimization-plan.zh.md)）：默认不变差，并找到一个可复现的正效果场景。共享上下文和记忆在一轮、用过的最好情况题目上在第一轮（用过的最好情况题目，见下方统一测试）和第二轮（新的、更难的题，见下方 A 组）都有正面结果；下面其他新开关的实际效果仍为 **Unknown**。

**统一测试 G1–G4（2026-11-11 至 11-13，[报告](research/2026-11-14-unified.zh.md)）：** 按[预登记](research/prereg/2026-11-07-unified.zh.md)跑完，花费约 $5.2。**G1 共享上下文 Pass**（codex gpt-6-luna 4/21 → 20/21；42 对 b = 16、c = 0，p = 3.1×10⁻⁵；每次成功花费只报 Codex：0.22 倍；dsh 臂为 Unknown：它的 `off` 臂读到了答案，之前合并的 0.46 倍撤回，#468）。**G2 记忆 Pass**（nomem 2/18 → mem 16/18；b = 14、c = 0，p = 1.2×10⁻⁴）。**G3 便宜首轮 Fail**（做对：self 3/6，cheap_first 2/6，花费 0.60 倍，墙钟 2.72 倍）。**G4 长任务两对都 Fail**（只作诊断；ccxlong 做对数和 self 一样，但花费 1.39 倍、墙钟 4.98 倍，Claude 自己的花费只有 self 的 24%）。题目都用过、属于最好情况设计：只说明机制有效，不改默认值。有 4 次尝试判 Unknown 后从头重跑（3 次是基础设施问题，由 #322、#323、#328、#331 修好；1 次是本机忙），每次都写进预登记修改记录。原因：主导的 `--check`（整套已有测试）测不到新要求，它在改动前就通过，或者改动前后失败得一样，所以便宜档漏掉的部分没人发现（#325、#326）；ccxlong 输在交接开销（写简报、启动 CLI、检查、审查）。 **2026-11-19 更正（#468）：** 只读泄题核查发现 dsh `off` 臂 18 个非中性单元全部读到约定答案；G1、G2 的 Pass 结论不变（b、c 全部来自 Codex，污染只会让 Pass 的方向被低估）。

**0.7.0 之后合入（2026-11-19 至 11-27；都未发版，没改默认值，各开关效果均为 Unknown）。** #440–#507 见[归档](STATUS-archive.zh.md)。11-25/26，跨家接力（[路线图](ROADMAP.zh.md)阶段 2，R1–R6 和 R8；#520–#527）：#569 真实额度事件登记模板（R1），#573 技能让主导登记接力目标（R2），#570 接力包带显式 `--check`，ccx 自己跑并出回执（R3），#574 另一家会话开场提示未处理的接力包（R4），#576 新旧两家用量各写一行账本（R5），#578 ccx 自己启动的 Codex 会话撞额度时存接力包，写明 Codex 无额度钩子（R6），#579 `docs/relay.zh.md` 开头改成三步（R8）。R7（#526，每日额度事件页）不在其中。另有 #577 `ccx report --daily --real-use`、#575 `--check` 超时杀整棵进程树、#572 活路线图、#568 第二轮 PIN 与 B 组预算记录、#517/#518 以及 P4 修复 #512、#513、#516。11-27：#580 0.8.0 发版准备（版本号四处同步，`changes/` 并入 CHANGELOG；**还没打 tag、没建 GitHub Release、没发 PyPI**：2026-11-28 核实，最新 tag 是 `v0.7.0`，PyPI 上是 0.6.0；打 tag 和发布由维护者做），#581 `ccx setup` 默认只问一个问题、逐步提问放到 `--advanced`，#582 [docs/advanced.md](advanced.zh.md) 全部命令和开关一页并标实测/实验性/已测不推荐，#583 肥上下文诊断的三个评测臂 `fatself`/`fatnative`/`fatccx`（没跑），#584 分流器 v0 `lead.route_map`，**默认关**、实验性（已证明的格子为空，等 #544 回放），#587 子 agent 启动失败的行计入无效行停机上限，`unified_summary p4` 口径对齐（#586），#588 超长 `--settings` 改走文件，启动失败按环境错误返回（#585），#590 B 组停机与重跑的预登记记录，#591 第二轮报告。

**第二轮（2026-11-27），[报告](research/2026-11-27-round2.zh.md)，[预登记](research/prereg/2026-11-16-round2.zh.md)。** **A1、A2、A1x、A2x 四组全部 Pass**（Holm 校正；共享上下文和记忆，Claude `haiku` 子 agent 与 Codex `gpt-6-luna` 子 agent 各一遍；有效对 47–48/48，b/c 为 41–44 / 0，校正后 p ≤ 9.1×10⁻¹³），总花费 $1.447790。限制：只有 Claude 主导；A1/A2 的 Pass 在 Claude 侧只有一轮（引用其中的数字需要第二轮）；不改默认值。**B 组（便宜首轮 v2 对 self）：第一次正式跑（tag `r2-b`，2026-11-26）跑了 120 行中的 77 行后停机，判 Unknown**：委派臂一次都没启动子 agent（`WinError 206`，由 #588 修；无效行上限由 #587 修），所以它的比值不能说明便宜首轮好坏；花费 $7.578454。**重跑已获用户批准**（2026-11-27），预算 $30（偏离记录在预登记，#590），**等机器空闲**再跑（期间没有别的会话跑 pytest、评测或 Codex CLI）；还没有结论。评测累计上限 $450（2026-11-16）。

**已有默认：** 路由 auto，配额感知/审查开；`small_self`、精简开关、记忆去重、无历史子会话/batch 合并、复现门禁关/实验性；worktree 默认 `sibling`，`inside` 自选/实验性；预算 0/不限，计费 `api`；`memory.by_kind` 关/实验性；`run.stall_minutes` 0/关/实验性；`worktree.base` 为 `head`；`routing.cold_start`、`review.skip_when_clean`、`brief.slim` 关/实验性；`lead.route_map` 关/实验性。

| 证据 | 结果与限制 | 出处 |
|---|---|---|
| hc2 收据 | 普通 `ok` 误报 0/19，95% 上界约 15%；`done` 仅 6 张，不足以测 2% 门槛；自带子智能体未重跑 | [hc2](research/2026-11-04-hc2-holdout.zh.md) |
| pg3b | 普通 `ok` 收据 0 张；29 张 `ok_self_checked` 中 15 张隐藏测试不过，审查全部给 pass | [pg3b](research/2026-11-03-pg3b-receipts.zh.md) |
| hc1，历史旧代码 | self 29/30、$0.090、21 秒；自带 27/28、$0.103、123 秒；ccx 29/30、$0.063、61 秒；逐点规则，非统计非劣效；“便宜约 30%”不描述 0.6.0 | [hc1](research/2026-10-29-hc1-holdout.zh.md) |
| Polyglot pg1 | self 25/30，ccx2 12/30；小而接口严格的题，一种配置，三行不干净 | [pg1](research/2026-10-31-polyglot-pg1.zh.md) |
| B3 | nomem Unknown；clean Fail；leantools 按规则 Fail / 事后未定；精简侧均关，未证明可靠节省 | [B3](research/2026-10-31-b3-lean-switches.zh.md) |
| #158 后、#223 前误报 | 8/209 = 3.8%；排除主导续跑成功后 8/191 = 4.2%，超过 2%；#223 后没有样本足够的重测 | [审计](research/2026-10-31-verdict-audit.zh.md) |

## 接下来三件

1. 机器空闲时重跑 B 组（预算 $30，tag 按 #590），不论结果如何都如实报告。
2. 分流器的离线回放脚本和神谕上界（#544，进行中），让 `lead.route_map` 能填上已证明的格子。
3. 用重跑结果补全第二轮报告里标 `PENDING` 的 B 组一节（#537）。

## 把握有多大（简版）

- **real（Windows，已登录 CLI）：** 双向派活、检查/审查、停止/续跑/记账、归档、DeepSeek 主导、discuss、对话板/叫醒、共享上下文 A/B、hc1/pg3b/hc2 和阶段 0、batch/worktree/undo、非 ASCII 路径/隐藏控制台、Windows Codex hook、交互式 Codex 每轮 hook、dsh 排队归档、临时 Claude 插件市场安装、UI 隐藏测试、Codex 实现/审查流程。
- **只有 fake / 工程检查（含 #271 之后合入的内容），例如：** 席位、配额排序/改派、额度接力、模型满载换模型、角色、就绪/刷新、一行结果、看板、收据 UNVERIFIED 显示、超时收据、Git 未完成步骤列表、简报/模式矛盾检查、self_first、slim_context、Claude 侧凭据禁读、汇总脚本、check 敏感度（#333）、卡住检测（#339）、worktree 基准（#341）、未提交文件回执（#340）、选档理由和 `--dry-run`（#398）、每日报告（#406）、计时字段（#409）、relay 时间字段（#419）、冷启动起步表（#426、#437）、干净时跳过审查（#427）、简报瘦身（#428）、分流校准和 `ab` 规模信号（#429、#433）、`branch_landed` 的 squash 判断（#420）、`autonomy merge` / `q accept` 的合并分支核对（#388、#401）、#382–#432 里的评测脚本（选题含 #422、#425 的泄漏扫描只在这台 Windows 机器上跑过）。**部分真实：** Codex 侧凭据禁读（#352，`codex-cli 0.164.0`，用假凭据文件）：elevated 的 `codex sandbox` 读被禁路径返回拒绝，unelevated 沙箱直接拒绝运行，开关打开时 `ccx run --to codex` 在启动前拒绝；elevated 沙箱会在这些路径上留下持久的 DENY ACL（撤销：`icacls <路径> /remove:d CodexSandboxUsers`）。**真实样本回放：** #245 Claude 限额事件/四条探针读数；Codex 拒绝样本仍为合成，不证明真实自动改派（[样本](../tests/data/real_signals/)）。
- **未验证：** 在 elevated 沙箱下开着 Codex 侧凭据禁读完整跑一次 `ccx run`（已登录又是 elevated 的只有用户自己的 `~/.codex`，会加持久 ACL，由维护者决定）；真实 Codex 子 agent 在 `--worktree` 里是否遵守不提交的规则（#340，只用假 CLI 测过）；真实限额改派、macOS 钥匙串就绪（缺凭据 = Unknown）、真实离线/慢网络 fetch 超时、已安装 `gpt-6.1-terra` 计价；macOS/Linux 真机（只有 CI）、Gemini CLI、Codex 桌面 `say --now`/doctor 规则/叫醒 hook、dsh 后续写归档、从 GitHub 装 Codex 插件、真实子智能体上限、`--review auto` 触发率、真实 hook 超时、GitHub intake、L2 自动合并整条链、评测外路由；除共享上下文和记忆外，上面列出的各开关对成本或成功率的影响（Unknown）。
- **已知问题：** 开着的：#375（第二轮主线）、#537（第二轮报告 B 组一节）、#545（分流器 v0）、#544（回放）。2026-11-19 以来已修复并关闭：#585/#588、#586/#587、#470/#472、#449/#504、#500/#503、#506/#507、#468、#446/#505（已关闭，验收还没完成，见接下来三件）。**局限：** 上游选题产出低且偏 Windows。本机系统性排除：需编译的仓库、时区名本地化（dateutil，12 个候选）、pytest 插件冲突（14）、werkzeug 文件占用（39）、内嵌副本检查（idna、urllib3；泄漏风险是真的，规则保留），以及受 numpy/scipy 钉版本问题影响的 69 个候选（#446，#505 之前）；题目集不是所有 Python 项目的样本，建议第三轮在 Linux 上重新选题。审计是兜底：Codex 单元无法限制读取（`codex exec` 没有读取拒绝选项），只能事后审计；Claude 的 deny 通配匹配没有用真实 CLI 验证。PyPI 仍是 0.6.0（0.7.0 和 0.8.0 等维护者）。此前仍未验证：没有本地 plan-review；CI 对 `/private/var`、8.3 短名和 `\\?\` 前缀的修复没复查；真实子智能体上限（F11 未触发）。

### 待本人验证（2026-11-28）

- 你决定后给 0.8.0 打 tag 并发布（GitHub Release、PyPI）；发版准备已合入（#580），维护者清单在里面（2026-11-28）。
- 额度接力：StopFailure 钩子已装，模拟事件正常（2026-11-10）；桌面 app 真实限额时会不会触发，要等一次自然限额，目前 **Unknown**（[docs/relay.zh.md](relay.zh.md)）。
- 决定要不要设用户环境变量 `PYTHONUTF8=1`（Windows），让通过管道打印 ccx JSON 的 Python 脚本输出 UTF-8 而不是 GBK；属于个人环境，ccx 不改（#335）。
- 决定要不要用你自己的 `~/.codex` 做 Codex 侧凭据禁读的真实验证（#289/#352；会在那里加持久 ACL）。
- 选 2–3 个项目开始真实使用 ccx（阶段 2；2026-11-18）。
