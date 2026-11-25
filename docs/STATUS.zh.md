# 进度

[English](STATUS.md) · 中文 · 更新于 2026-11-24 · 0.7.0 已打 tag 并建 GitHub Release（尚未发 PyPI，PyPI 上仍是 0.6.0，2026-11-18 核实）；main 已领先

供接手时读的一页，由统筹维护。历史见[归档](STATUS-archive.zh.md)；
改动见 [CHANGELOG](../CHANGELOG.md) 和[各 PR 记录](../changes/README.zh.md)。

## 现在

**已发布：** 0.7.0，2026-11-16：`v0.7.0` tag 打在 #357 的发版提交上（该提交全矩阵 CI 和打包检查全绿），[GitHub Release](https://github.com/SUPERD6/relayline/releases/tag/v0.7.0) 附 wheel 和 sdist；CHANGELOG 的 0.7.0 一节折入了到 #354 为止的 `changes/` 记录；#355、#356、#363 的代码在 tag 里，但记录没折，留在 `changes/` 等下次发版。**还没发 PyPI**（由维护者决定）：`pipx install relayline` 装到的仍是 0.6.0，要用 0.7.0 请从 Release 附件安装。tag 之后合入、尚未发版的：#352、#361、#364、#366、#368、#369，以及 #382 起的全部（见归档和下面“此后合入”）。目标不变（[工程标准](engineering-standards.zh.md)、[优化计划](research/2026-11-04-optimization-plan.zh.md)）：默认不变差，并找到一个可复现的正效果场景。共享上下文和记忆在一轮、用过的最好情况题目上已有正面结果（见下方统一测试；还需要在新题上跑第二轮确认）；下面其他新开关的实际效果仍为 **Unknown**。

**统一测试 G1–G4（2026-11-11 至 11-13，[报告](research/2026-11-14-unified.zh.md)）：** 按[预登记](research/prereg/2026-11-07-unified.zh.md)跑完，花费约 $5.2。**G1 共享上下文 Pass**（codex gpt-6-luna 4/21 → 20/21；42 对 b = 16、c = 0，p = 3.1×10⁻⁵；每次成功花费只报 Codex：0.22 倍；dsh 臂为 Unknown：它的 `off` 臂读到了答案，之前合并的 0.46 倍撤回，#468）。**G2 记忆 Pass**（nomem 2/18 → mem 16/18；b = 14、c = 0，p = 1.2×10⁻⁴）。**G3 便宜首轮 Fail**（做对：self 3/6，cheap_first 2/6，花费 0.60 倍，墙钟 2.72 倍）。**G4 长任务两对都 Fail**（只作诊断；ccxlong 做对数和 self 一样，但花费 1.39 倍、墙钟 4.98 倍，Claude 自己的花费只有 self 的 24%）。题目都用过、属于最好情况设计：只说明机制有效，不改默认值。有 4 次尝试判 Unknown 后从头重跑（3 次是基础设施问题，由 #322、#323、#328、#331 修好；1 次是本机忙），每次都写进预登记修改记录。原因：主导的 `--check`（整套已有测试）测不到新要求，它在改动前就通过，或者改动前后失败得一样，所以便宜档漏掉的部分没人发现（#325、#326）；ccxlong 输在交接开销（写简报、启动 CLI、检查、审查）。 **2026-11-19 更正（#468）：** 只读泄题核查发现 dsh `off` 臂 18 个非中性单元全部读到约定答案；G1、G2 的 Pass 结论不变（b、c 全部来自 Codex，污染只会让 Pass 的方向被低估）。

**此后合入（PR #472–#507，2026-11-19 至 11-24）。** 都未发版，没改默认值，各开关效果均为 **Unknown**。#440–#471 见[归档](STATUS-archive.zh.md)。已合入：#472 strength 单元不能读共用登录 home 里其他单元的会话记录（#470）；#474 STATUS；#476 A 组隔离补充的预登记修改记录。三条评测规则决定（#411，维护者 2026-11-19，[正文](research/2026-11-17-eval-rule-decisions.zh.md)）及其代码：#481 `receipt_fp.py` 加 `verdict`（点估计 ≤ 2% 且上界 ≤ 5% 才 Pass；#478），#479 和 #485 工程标准，#482 `ccx report --daily --quota-events`（默认关），#486 和 #488 relay 接续记录写 `ended_at` 和 `postprocess_error`（#483、#487）。第二轮 B 组题目集：#489 tabula 10 道，#490 cronlite 8 道，#492 B 组冻结（60 = 上游 42 + 新写 18；#375），#496 冻结记录，#499 断言计数认 `eq_`、`expect_warnings`、`deprecated_call`（#491），#494 personal-data 检查放行 `pytest-of-<用户名>`（#493），#498 预登记写全 A1/A2/A1x/A2x/B 的命令（#497），#502 更正：B 组选题环境是 prepare-v4（`extpy4`），不是 `pip-list-v3.json` 那份文件（#501）。2026-11-24 合入：#503 无头浏览器渲染测试等明确的“画完”信号，没画完就把虚拟时间预算翻倍重试，到期按 `render timeout` 失败（#500）；#504 `round2_tasks select --skip-c`：顺序 B 再 B-dev，不收 C（#449）；#505 钉版本时看 `requires_python`，只钉 `--ext-python` 能装的发行（#446；**验收未完成：** 第三轮重跑 `prepare` 时要确认 numpy 和 scipy 装上了）；#507 测试不再往仓库 `.ccx/eval/` 写文件，并加了会话结束检查，那里有任何变化就让整次测试失败（`CCX_TEST_ALLOW_EVAL_WRITES=1` 时只警告）（#506）。

**第二轮现状（2026-11-24）。** 设计见[预登记](research/prereg/2026-11-16-round2.zh.md)，修改记录到 #502。第二轮跑 A + B（C 组推到第三轮，#448）。A、B 两组都已冻结并预登记：A 组题目集（#407），B 组 60 道（#492；环境更正 #502）。隔离已堵上（#453、#455、#460、#471、#472；记录 #476）。开发单元成本检查：dry-run 五组（A1、A2、A1x、A2x、B）全部通过。**真跑在等 Claude 评测 home 登录，所以实际花费是 $0**；这次检查的上限是 $13.2。评测累计上限 $450（维护者，2026-11-16），截至 2026-11-16 约花 $165（总会话报告）。

**已有默认：** 路由 auto，配额感知/审查开；`small_self`、精简开关、记忆去重、无历史子会话/batch 合并、复现门禁关/实验性；worktree 默认 `sibling`，`inside` 自选/实验性；预算 0/不限，计费 `api`；`memory.by_kind` 关/实验性；`run.stall_minutes` 0/关/实验性；`worktree.base` 为 `head`；`routing.cold_start`、`review.skip_when_clean`、`brief.slim` 关/实验性。

| 证据 | 结果与限制 | 出处 |
|---|---|---|
| hc2 收据 | 普通 `ok` 误报 0/19，95% 上界约 15%；`done` 仅 6 张，不足以测 2% 门槛；自带子智能体未重跑 | [hc2](research/2026-11-04-hc2-holdout.zh.md) |
| pg3b | 普通 `ok` 收据 0 张；29 张 `ok_self_checked` 中 15 张隐藏测试不过，审查全部给 pass | [pg3b](research/2026-11-03-pg3b-receipts.zh.md) |
| hc1，历史旧代码 | self 29/30、$0.090、21 秒；自带 27/28、$0.103、123 秒；ccx 29/30、$0.063、61 秒；逐点规则，非统计非劣效；“便宜约 30%”不描述 0.6.0 | [hc1](research/2026-10-29-hc1-holdout.zh.md) |
| Polyglot pg1 | self 25/30，ccx2 12/30；小而接口严格的题，一种配置，三行不干净 | [pg1](research/2026-10-31-polyglot-pg1.zh.md) |
| B3 | nomem Unknown；clean Fail；leantools 按规则 Fail / 事后未定；精简侧均关，未证明可靠节省 | [B3](research/2026-10-31-b3-lean-switches.zh.md) |
| #158 后、#223 前误报 | 8/209 = 3.8%；排除主导续跑成功后 8/191 = 4.2%，超过 2%；#223 后没有样本足够的重测 | [审计](research/2026-10-31-verdict-audit.zh.md) |

## 接下来三件

1. Claude 评测 home 登录后，跑开发单元成本检查，把实测花费写进预登记修改记录。
2. 按 A1、A2、A1x、A2x、B 的顺序逐组正式跑。
3. 第三轮准备时重跑 `prepare`，确认 #446 的验收：numpy 和 scipy 钉到 `--ext-python` 能装的版本，并显示已安装。

## 把握有多大（简版）

- **real（Windows，已登录 CLI）：** 双向派活、检查/审查、停止/续跑/记账、归档、DeepSeek 主导、discuss、对话板/叫醒、共享上下文 A/B、hc1/pg3b/hc2 和阶段 0、batch/worktree/undo、非 ASCII 路径/隐藏控制台、Windows Codex hook、交互式 Codex 每轮 hook、dsh 排队归档、临时 Claude 插件市场安装、UI 隐藏测试、Codex 实现/审查流程。
- **只有 fake / 工程检查（含 #271 之后合入的内容），例如：** 席位、配额排序/改派、额度接力、模型满载换模型、角色、就绪/刷新、一行结果、看板、收据 UNVERIFIED 显示、超时收据、Git 未完成步骤列表、简报/模式矛盾检查、self_first、slim_context、Claude 侧凭据禁读、汇总脚本、check 敏感度（#333）、卡住检测（#339）、worktree 基准（#341）、未提交文件回执（#340）、选档理由和 `--dry-run`（#398）、每日报告（#406）、计时字段（#409）、relay 时间字段（#419）、冷启动起步表（#426、#437）、干净时跳过审查（#427）、简报瘦身（#428）、分流校准和 `ab` 规模信号（#429、#433）、`branch_landed` 的 squash 判断（#420）、`autonomy merge` / `q accept` 的合并分支核对（#388、#401）、#382–#432 里的评测脚本（选题含 #422、#425 的泄漏扫描只在这台 Windows 机器上跑过）。**部分真实：** Codex 侧凭据禁读（#352，`codex-cli 0.164.0`，用假凭据文件）：elevated 的 `codex sandbox` 读被禁路径返回拒绝，unelevated 沙箱直接拒绝运行，开关打开时 `ccx run --to codex` 在启动前拒绝；elevated 沙箱会在这些路径上留下持久的 DENY ACL（撤销：`icacls <路径> /remove:d CodexSandboxUsers`）。**真实样本回放：** #245 Claude 限额事件/四条探针读数；Codex 拒绝样本仍为合成，不证明真实自动改派（[样本](../tests/data/real_signals/)）。
- **未验证：** 在 elevated 沙箱下开着 Codex 侧凭据禁读完整跑一次 `ccx run`（已登录又是 elevated 的只有用户自己的 `~/.codex`，会加持久 ACL，由维护者决定）；真实 Codex 子 agent 在 `--worktree` 里是否遵守不提交的规则（#340，只用假 CLI 测过）；真实限额改派、macOS 钥匙串就绪（缺凭据 = Unknown）、真实离线/慢网络 fetch 超时、已安装 `gpt-6.1-terra` 计价；macOS/Linux 真机（只有 CI）、Gemini CLI、Codex 桌面 `say --now`/doctor 规则/叫醒 hook、dsh 后续写归档、从 GitHub 装 Codex 插件、真实子智能体上限、`--review auto` 触发率、真实 hook 超时、GitHub intake、L2 自动合并整条链、评测外路由；除共享上下文和记忆外，上面列出的各开关对成本或成功率的影响（Unknown）。
- **已知问题：** 开着的：#375（第二轮主线）。2026-11-19 以来已修复并关闭：#470/#472、#449/#504、#500/#503、#506/#507、#468、#411（决定已合并）、#446/#505（已关闭，验收还没完成，见接下来三件）。**局限：** 上游选题产出低且偏 Windows。本机系统性排除：需编译的仓库、时区名本地化（dateutil，12 个候选）、pytest 插件冲突（14）、werkzeug 文件占用（39）、内嵌副本检查（idna、urllib3；泄漏风险是真的，规则保留），以及受 numpy/scipy 钉版本问题影响的 69 个候选（#446，#505 之前）；题目集不是所有 Python 项目的样本，建议第三轮在 Linux 上重新选题。审计是兜底：Codex 单元无法限制读取（`codex exec` 没有读取拒绝选项），只能事后审计；Claude 的 deny 通配匹配没有用真实 CLI 验证。PyPI 仍是 0.6.0（0.7.0 等维护者）。此前仍未验证：没有本地 plan-review；CI 对 `/private/var`、8.3 短名和 `\\?\` 前缀的修复没复查；真实子智能体上限（F11 未触发）。

### 待本人验证（2026-11-24）

- 登录 Claude 评测 home（开发单元成本检查卡在这里；2026-11-24）。
- 额度接力：StopFailure 钩子已装，模拟事件正常（2026-11-10）；桌面 app 真实限额时会不会触发，要等一次自然限额，目前 **Unknown**（[docs/relay.zh.md](relay.zh.md)）。
- 决定要不要设用户环境变量 `PYTHONUTF8=1`（Windows），让通过管道打印 ccx JSON 的 Python 脚本输出 UTF-8 而不是 GBK；属于个人环境，ccx 不改（#335）。
- 决定要不要用你自己的 `~/.codex` 做 Codex 侧凭据禁读的真实验证（#289/#352；会在那里加持久 ACL）。
- 选 2–3 个项目开始真实使用 ccx（阶段 2；2026-11-18）。
