# 实测

[English](measured.md) · 中文 · 回到 [README](../README.zh.md) · 全部[研究报告](research/README.zh.md)

## 角色模型来源核对（2026-11-01）

本机 `codex-cli 0.164.0 --help` 接受 `-m/--model MODEL`，不枚举模型。2026-11-01 实际打开官方模型页核对；
这只证明文档内容，不证明当前账号可调用，也没有发起真实模型运行。

| 模型 | 输入 / 缓存读 / 输出，美元每百万 token（标准短上下文） | 来源 |
|---|---|---|
| `gpt-6.1-terra` | $1 / $0.05 / $5 | [官方模型与价格页](https://developers.openai.com/api/docs/models/gpt-6.1-terra)，2026-11-01 核对 |
| `gpt-6-astra` | $10 / $1 / $50 | [官方模型页](https://developers.openai.com/api/docs/models/gpt-6-astra)，2026-11-01 核对；上下文 1,050,000 token，最大输出 128,000 |

Terra 支持 none/low/medium/high/xhigh/max 强度。适配器接受其名字，角色测试使用假 CLI。名字支持不等于已有
校准路由先验或账本价格；已安装价格表不认识 Terra 时，运行费用仍保持 unknown。工作流示例及其来源见
[功能说明](features.zh.md#参考角色表示例不写入默认配置)。

## README 里的对比：自己做、内置子智能体、ccx

### 留出集（hc1，2026-10-29）

README 留出集那一行，出自[留出集报告](research/2026-10-29-hc1-holdout.zh.md)：做 ccx 时没用过的 10 个任务（本仓库 5 个、两个外部
仓库 5 个）× 3 轮，Sonnet medium 主导，隐藏测试，规则预先登记；计入 90 个单元，汇总只算干净行，中位为真中位数。
题目、结果行和重跑脚本见 [bench/](../bench/README.zh.md)（公开在那里之后，这套题就不再是留出集）。

| | 主导自己做 | Claude Code 内置子智能体（默认用法） | ccx → Codex（luna low） |
|---|---|---|---|
| 做对 | 29/30 | 27/28（2 行因环境不干净被剔除；算上是 28/30） | 29/30 |
| 每次成功的花费 | $0.090 | $0.103 | **$0.063** |
| 用时中位数 | 21.0 秒 | 123 秒 | 60.7 秒 |
| 主导 token 中位数 | 62k | 56k | 36k |
| 只看外部仓库（5 个任务） | 15/15、$0.036 | 14/14、$0.052 | 15/15、$0.030 |

按预登记的规则，ccx 未见更差（29 ≥ 29 − 2；这是逐点规则，不是统计意义上的非劣检验：按任务的差值区间约 ±3/30），而且更省：
比自己做每次成功少 $0.027（95% CI −0.054 至 −0.004），比内置子智能体默认用法少 $0.040（−0.086 至 −0.015），约低 30% 和 39%。
用时约为自己做的 3 倍。这些数字必须带着的限制：内置子智能体是默认用法（被要求跑全量测试；开发集上比 ccx 便宜的精简做法
builtin2 不在这次运行里）；本仓库 5 个任务的答案可能就在 ccx 所运行的代码里，所以外部仓库那一行（−15% / −42%）才是干净的；
只有 10 个任务、一种主导模型；金额是 API 等价价。全部 8 条限制见报告。

### 第 5 轮，开发集

README 里开发集的几行，出自[第 5 轮报告](research/2026-10-26-r5.zh.md) §1 和 §7，以及下面 r5h 那一行。
**开发集**：这些任务也在修 ccx 时用过；上面的留出集运行没有改动这几行。

| | 主导自己做 | Claude Code 内置子智能体 | ccx → Codex（luna low） |
|---|---|---|---|
| 算进来的轮次 | r5（一轮，ccx 版本更旧） | r5 builtin、r5d builtin2（精简做法）、r5f builtin | r5e、r5f、r5g、r5h（修完之后） |
| 做对 | 19/20 | 19、17、17（满分 20） | 19、20、18、19（满分 20） |
| 每次成功的花费 | $0.211 | $0.155、**$0.114**、$0.202 | $0.131、$0.116、–、**$0.135** |
| 用时中位数 | 94 秒 | 278、276、316 秒 | 251、267、–、236 秒 |

精简做法的内置子智能体（builtin2，$0.114）每次成功比 r5h（$0.135）便宜；第 5 轮修之前的第一轮 ccx 是 17/20、$0.248、
460 秒。小一些的任务上的用时：第 1 轮自己做 10.9 秒对 ccx 33.7 秒，第 3 轮自己做 14 秒对 ccx 63 秒。和主导自己做比总花费：第 1 轮
基本持平（比值 1.02），第 4 轮也差不多（每次成功 $0.595 对 $0.567），第 3 轮更贵（$0.071 对 $0.045，主导是新开的短会话；
那一轮和内置子智能体一样，比值 1.02），第 5 轮更便宜（见上表）。

## 外部基准（polyglot pg1，2026-10-31）

aider polyglot 基准的 30 道 Python 题 × 1 轮，Sonnet medium 主导，隐藏测试只给一次机会：

| | 主导自己做 | ccx → Codex（luna low），主导派活 | Codex luna low 直接做，没有主导 |
|---|---|---|---|
| 做对（全部 30 / 干净 29） | 25/30 / 24/29 | 12/30 / 12/29 | 9/30 / 9/29 |
| 每次成功（全部 / 干净） | $0.037 / $0.036 | $0.115 / $0.112 | $0.021 / $0.019 |
| 用时中位数（全部 30） | 11 秒 | 57 秒 | 44 秒 |

按全部 30 题：ccx2 没做对而自己做对的有 13 题，反过来 0 题（p = 2.4e-4）；ccx2 每次成功是自己做的 3.1 倍（95% CI 2.2–5.4），
其中 82% 花在主导侧；干净口径是 12 / 0（p = 4.9e-4）、3.1 倍（2.1–5.2）。不经主导（direct），同一档每次成功是自己做的 0.57 倍
（95% CI 0.37–1.14；干净配对 0.51，0.34–0.99），但只做对 9/30。这些题没有现成测试，所以 ccx 的 check 是子智能体自写的测试，
在 ccx2 的 18 个失败里全部通过。小而接口严格的题不值得派；目前只在自己做较贵的仓库任务（hc1，版本和任务都不同，与 pg1 不配对）
上见到省钱。方法、失败原因和全部 12 条限制见 [pg1 报告](research/2026-10-31-polyglot-pg1.zh.md)。

## 子智能体精简开关（B3，2026-10-31）

`[subagent]` 的三个开关对着用户日常配置测过，都保持默认值、仍是实验性：关 Codex memories 结论 Unknown，干净子智能体
Fail，少给 Codex 工具按登记规则 Fail（事后解读为未定）。数字、方法和限制见 [B3 报告](research/2026-10-31-b3-lean-switches.zh.md)。

## 单个功能的最好情况（原 README 的四根柱子）

每个都来自专门测一个功能的 A/B，都不是一般情况下用户该期待的节省。

| 柱子 | 数字 | 出处 | 局限 |
|---|---|---|---|
| 省钱 | 总花费少 63%；返工 0 次对 29 次 | [共享工作上下文 A/B](research/2026-10-25-shared-context-ab.zh.md)（2026-10-25，Codex luna low + DeepSeek flash low，42 对） | 任务专门设计成需要主导的上下文：按设计就是这个功能的最好情况 |
| 更准 | 一次做对 36/36 对 7/36（McNemar p ≈ 4e-9） | 同一个 A/B | 同上；中性任务两组都是 6/6 |
| 分工 | 主导每个任务都少 1 次请求，21/21 | [七核心 A/B](research/2026-10-24-seven-cores-ab.zh.md) §2.2 | 总花费基本持平（比值 1.02），token 3.3 倍，慢约 23 秒；主导是短的无头会话 |
| 共享 | 项目记忆被照做：9/9 对 0/9（McNemar p = 0.004，Holm 0.016） | [七核心 A/B](research/2026-10-24-seven-cores-ab.zh.md) §2.1 | 3 个任务 × 3 次；hub 记忆经开局 hook 这条路没测 |

## 第 5 轮：真实的大任务（2026-10-26/27，开发集）

本仓库 10 个真实改动 × 2，sonnet medium 当主导，隐藏测试；细节和所有组见[第 5 轮报告](research/2026-10-26-r5.zh.md)。
**开发集，只当信号**：这些任务也在修 ccx 时用过，而且这轮早于干净环境检查（[r5 计划 §8](research/2026-10-26-r5-plan.zh.md)）。
它不改上面单个功能的数字。

| 轮次 | 组 | 做对 | 每次成功的花费 | 用时中位数 |
|---|---|---|---|---|
| r5h | ccx2（按 agent-delegate 技能现在教的用法） | 19/20 | $0.135 | 236 秒 |

修完后 ccx2 的四轮（r5e–r5h）分别是 19、20、18、19（满分 20），每次成功 $0.116–0.135；r5h 不是其中最好的一轮。
对照来自更早、ccx 版本更旧的运行（主导自己做在第一轮之后没有重跑）：主导自己做 19/20、$0.211、94 秒，内置子智能体
19/20、$0.155、278 秒（都是第一轮）；用同样精简做法的内置子智能体（builtin2，r5d）17/20、**$0.114**、276 秒，
每次成功比 r5h 的 ccx2 便宜。做对的答案也掩盖了编排层的问题：[编排层审计](research/2026-10-28-harness-audit.zh.md)
发现 r5e–r5h 里每个做对的 ccx2 单元（76/76）都至少有一项编排层标准没过，80 个里没有一个全部通过，编排层宏平均 0.67。
报告 §7 的表停在 r5f；r5h 这一行按同样的定义（20 个单元的总花费 / 做对的单元数；20 个单元用时的普通中位数）
从同一个结果文件算出。

## 实测（2026-10-24，ccx 0.4.0）

全部来自真机上的真实运行，方法、原始表格和局限见[实测报告](research/2026-10-24-h11-e8-f9-measurements.zh.md)和[七核心 A/B](research/2026-10-24-seven-cores-ab.zh.md)。**有利的和不利的都列在这里。** 最后一列写明是测量还是外推。

| 问题 | 结果 | 把握 |
|---|---|---|
| 小任务派给 Codex 省不省？（[七核心 A/B](research/2026-10-24-seven-cores-ab.zh.md) 第 1 轮：7 个 Python 任务（4 小 3 中）× 3，sonnet 主导自己做 / 派给 Codex luna low，配对） | **总花费基本持平：比值 1.02**（中位数 $0.0344 → $0.0351；按任务的符号检验 p = 1）。**总 token 3.3 倍**（3.56 万 → 11.9 万），**慢约 23 秒**（10.9 → 33.7 秒）。主导**每个任务都少 1 次请求**（3 → 2，21/21）。做对：自己做 21/21，派出去 18/21（便宜的子智能体把一个中等任务 3 次都做错）。更早一批（PR #6）：haiku 当主、派完自己再跑测试，请求没省、花得更多。 | **测量**；5–15 分钟的任务、短的无头主导 |
| 换到真实的长对话主导会怎样？ | 少 1 次请求 ≈ 少读 35.2 万 token（下面的中位数）≈ 按 Opus 缓存读价每个小任务**约省 $0.07，多等约 23 秒**，而且可能做错；主导不省请求时，多花约 $0.003。 | **外推，不是测量**（[A/B](research/2026-10-24-seven-cores-ab.zh.md) §2.2） |
| 钱到底花在哪？（本机真实会话，7 天） | Claude 主导每次请求中位数 **35.2 万 token、$0.11**，缓存读占 99%；同期 ccx 子任务一共 $0.42。所以最该省的是主导每轮重读的上下文。 | **测量**（读会话文件，2026-10-17–24） |
| Codex 自带的子智能体会被用上吗？ | gpt-6-luna low 上 **5/5 次都没启动**，连明确要求的那次也没有；开 / 关的花费和用时差别在噪声以内。更高档的模型没测。 | 只对 luna low 有把握 |
| 只凭交接，接手方能说对“做到哪、下一步”吗？ | 受控场景 3/3 说对（含中途被杀）；真实长会话第一次说错（计划读成了过期状态），修好后说对。 | 真实会话只有 1 个 |
| 精简启动一个 Claude 子智能体 | 每次请求的固定上下文 4.6 万 → **1.36 万** token | 单次实测 |
| 记账和 Codex 自己的周额度对照 | 每 1% 额度折算 **$2.8–4.4**，4 个时段都稳定 | 4 个时段 |
| 测试 | 268 个，Linux、Windows、macOS × Python 3.11–3.13 | 只证明逻辑，不证明真机 |

## 省了多少，怎么算

- **AE$（API 等价美元）**：token × 官方价格表，按 4 类分别计价（新输入、写缓存、读缓存、输出）。订阅制不按 token 收费，所以用它做统一尺子。实测与 Claude 自报费用差 1.5%。
- **估计节省（模型估算，不是实测）**：每个派出去的任务 = 子智能体 token 里活本身那部分（新读入的和输出的，减掉它的读缓存和写缓存（第 2 轮约每次 93k token——这是整次运行的输入，大部分是读缓存，不是一次性启动开销：固定前缀（Codex 中位约 1.8–2.5 万、Claude 约 1.3–1.5 万）每次请求重发，一次运行约 5 次请求）；Codex 不报写缓存，它每次启动、碰到任务之前还要新读约 2 万 token，见 docs/research/2026-10-25-warm-lanes.md；Gemini 先假定一样）按主导模型的价格算 − 子智能体实际花费 − 写简报和验收的开销；附 95% 置信区间。2026-10-29 之前是把子智能体全部 token 都按主导的价格算，演示页因此在花了 $0.49 时显示约省 $2.97，而实测总花费基本持平，所以旧算法只留作对照（`saving_old_model`，有 trial 实测值时不给）。它不是上限：对话很长的主导每次请求都要重读整段上下文，自己做一件活可能比这两个数都贵。`ccx ui`、`ccx report`、`ccx stats --summary` 都先给花费，再在后面给这个带标签的估算。`ccx trial` 实测够了就换成实测值。
- **A/B 实测**：约 10% 本可以派的任务，随机让主导自己做（`defaults.ab_self_rate`，可设为 0 关掉），按同样难度对比实际花费，用来检验上面的估算。
- 主导自己的用量从两边工具自带的会话记录里读（Claude `~/.claude/projects`，Codex `~/.codex/sessions`），子智能体的会话会排除，避免重复计算。

## 测试

```bash
python -m pytest -q tests        # 或 python -m unittest discover -s tests
```

测试用模拟的 codex/claude/gemini（`tests/fakes/`）检查：命令参数、流式解析、升级、续会话、额度回退、超时、防套娃、增量记忆、同步的幂等和备份、学习回路、看板。GitHub Actions 在 Linux/Windows/macOS × Python 3.11–3.13 上跑。
**测试只证明这些逻辑本身是对的，不能证明在真实 CLI 和你的电脑上跑通**。在你自己的电脑上请跑 `ccx selftest`，验收清单见 [docs/DESIGN.zh.md](DESIGN.zh.md) 的“验收”。

## 已核对的外部事实（2026-10-22/24）

- codex-cli 0.164.0 `exec --help`：`--json`、`-m`、`-c`、`--output-schema`、`-o`、`--ignore-user-config`、`--ephemeral`、`exec resume <id>`（resume 不接受 `-s`，所以沙箱统一用 `-c sandbox_mode=…`）；精简启动（`--ignore-user-config`）必须带上用户的 `windows.sandbox`，否则 Windows 上只读模式会拒绝所有命令
- Claude Code 2.1.309 `--help`：`-p --output-format json|stream-json`（stream-json 必须加 `--verbose`）、`--model`、`--effort low..max`、`--json-schema`、`--resume`、`--strict-mcp-config`；实测：第一条事件带 session_id，最后的 result 事件带 `structured_output`、`usage`、`total_cost_usd`；`--resume` 报的是单次用量；默认参数无头启动约 4.6 万 token，写入 1 小时缓存；用 ccx 的精简参数约 2 万，一小时内再次启动（哪个项目都行）只新写入约 650–2000 token
- OpenAI GPT-6 文档：`gpt-6-astra` / `gpt-6.1-sol` / `gpt-6-luna`；6.1-sol 的 effort 为 low/medium/high/xhigh/max
- Codex hooks 文档：`[[hooks.SessionStart]]`，stdout 作为开发者上下文注入，新 hook 需要在 `/hooks` 里信任
- Gemini CLI 0.65.0 `--help` 与内置源码：`-p`（无头，附加在 stdin 之后）、`-o stream-json`（init / message / tool_use / tool_result / error / result 事件）、`--approval-mode plan|auto_edit`、`--session-id`、`--resume <uuid>`、模型别名 `flash-lite / flash / pro`
- DeepSeek Harness（`dsh`，github.com/deepseek-ai/deepseek-harness，标签 dsh-v0.2.1-rc.3，2026-10-24 读源码，本机未安装）：`dsh --profile headless "任务"`（或用 `-` 从 stdin 读）跑一个任务；`--json` 输出 session / status（step_end 带用量、turn_end 带结束原因）/ text / tool_call / tool_result / final / error 事件；`--session-id <id>` 续接。token 计数互不重叠（input 不含缓存命中）。rc.3 没有模型和权限参数：模型写在 `--patch` 覆盖文件里（`agent-default-model` 行），沙箱用 `DSH_PERMISSION_MODE`。基础配置默认会把会话日志随请求上传给 DeepSeek，ccx 跑它时关掉。
- Codex 自定义 model provider（Codex 配置参考，2026-10-24 读）：`model_provider` 加 `[model_providers.<id>]`，字段 `base_url`、`env_key`、`wire_api`（只支持 `"responses"`）；`openai`、`ollama`、`lmstudio` 是保留名。DeepSeek 的 Codex 接入页用 `base_url = "https://api.deepseek.com/"`、`wire_api = "responses"`。codex-cli 0.164 实测：走自定义 provider 时 `apps` 和 `plugins` 会把所有连接器的工具定义整份发出去（“回复 OK”首请求 21.9 万输入 token，加 `--disable apps --disable plugins` 后 1 万），所以 ccx 经 provider 跑 Codex 时关掉这两项和 Codex 自带子智能体。Codex 会提示找不到 `deepseek-flash` 的模型元数据、改用默认元数据，但能跑完。
- 较新的 API（Claude Code 用的 Anthropic 兼容端点，2026-10-24 读，都没真跑过）：
  - Kimi：`https://api.moonshot.ai/anthropic`，`kimi-k3.1-pro`；价格表是网页脚本渲染的，没读到数字，所以在你写上价格之前 ccx 拒绝运行它；
  - GLM（Z.ai）：`https://api.z.ai/api/anthropic`；GLM-5.3-Flash $0.15 / $0.03 / $0.50，GLM-5.3 $1.4 / $0.26 / $4.4；
  - Qwen（阿里云百炼按量付费）：地址是 `https://{WorkspaceId}.<地域>.maas.aliyuncs.com/apps/anthropic`，所以 ccx 从 `DASHSCOPE_ANTHROPIC_BASE_URL` 读；qwen3.7-plus $0.4 / $1.6，qwen3.7-max $2.5 / $7.5（新加坡，没给缓存价，按输入价算）；
  - OpenRouter：`https://openrouter.ai/api`；没有默认模型，要给 `--model` 和它的价格。
  - 各家文档把密钥放在 `ANTHROPIC_AUTH_TOKEN`；ccx 用 `--bare` 跑 Claude Code，只认 `ANTHROPIC_API_KEY`（以 `x-api-key` 发送）。DeepSeek 接受这种方式，其他几家还没确认。
- DeepSeek 文档：Claude Code 用 `ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic` 加密钥；ccx 用 `ANTHROPIC_API_KEY` 加 `--bare` 传入，调用方自己的 Claude 登录不会被发到 DeepSeek（2026-10-24）；闲时半价；价格（高峰）deepseek-flash 输入 $0.30 / 缓存 $0.006 / 输出 $1.20，deepseek-v4-pro $1.32 / $0.044 / $3.96（每百万 token）
- Gemini 价格（ai.google.dev/pricing）：3.5-flash-lite $0.30 / $0.03 / $2.50，3.8-flash $0.75 / $0.075 / $3.75（到 2026-12-31），3.1-pro-preview $2.00 / $0.20 / $12.00
