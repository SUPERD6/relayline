# B3 子智能体精简开关：计划与评测组（2026-10-30）

[English](2026-10-30-b3-lean-switches-plan.md) · 中文 · 返回[研究报告](README.zh.md)

**状态：只是计划，什么都还没跑；下面没有任何数字是结果。** 开关已经在 ccx 里，出厂都是今天的做法；测量它们的评测组在 `scripts/eval/r5.py` 里。

## 为什么要新基线

到目前为止评测过的 ccx2 单元（r5、hc1），Codex 子智能体都跑在专用的评测 Codex home 里，带 `--ignore-user-config`、`--ignore-rules`、关 memories；Claude 子智能体不加载用户设置和技能。用户日常真正用的配置（Codex memories、AGENTS.md、技能）从没测过。B3 的多数开关是让子智能体*向*已测过的配置靠拢，所以拿它们和评测过的 ccx2 比，什么也比不出来：需要一个"日常配置"基线。

## 开关（config/tiers.toml 的 `[subagent]`，出厂都是今天的做法）

| 键 | 改了以后 | 预期（从对话记录估算，未实测） |
|---|---|---|
| `codex_memories`（true） | false：每一档 Codex 加 `-c features.memories=false -c memories.use_memories=false -c memories.generate_memories=false` | 每次请求少约 6.8k，每次运行少 25–35k |
| `clean`（false） | true：Codex / dsh 用空 HOME（只少了 `~/.agents/skills`；CODEX_HOME 里的 AGENTS.md、技能、memories 仍在），Claude 不加载技能和用户设置，提示加一句总结用什么语言，Agent 工具只在 `--parallel` 时给 | Claude 每次运行少 5–8k；Codex 只省 `~/.agents/skills` 那部分（之前估的每次请求 4–6k 假设个人技能和规则全去掉，这个开关做不到） |
| `codex_lean_tools`（false） | true，只对写入任务：关网页搜索、图片生成、goals；直连 OpenAI 时关 apps / plugins | 每次请求少约 3–4k |

细节和风险见[功能说明](../features.zh.md#实验性子智能体精简开关subagent实测前不开)。

## 评测组（手动选，`--arms ...`）

四组和 ccx2 一字不差（同一个主导、同样的措辞和命令行），区别只在子智能体启动用的 home，以及写进单元自己 hub 的 tiers.toml 里的 `[subagent]` 覆盖（主导开始前按 ccx 的读法读回确认；每组代码相同）。

| 组 | 子智能体 |
|---|---|
| `ccx2daily` | 日常配置基线：Codex 用每个单元自己的 home，里面是用户 `~/.codex` 的 memories/、AGENTS.md、skills/ 和 `~/.agents/skills`（作为它的 HOME）的副本，不加 `--ignore-user-config` / `--ignore-rules` / 不关 memories；Claude 子智能体加载 `user,project,local` 三层设置，技能开着 |
| `ccx2daily_nomem` | 基线 + `codex_memories = false` |
| `ccx2daily_clean` | 基线 + `clean = true` |
| `ccx2daily_leantools` | 基线 + `codex_lean_tools = true` |

每个单元的 home 怎么做（`scripts/eval/daily_home.py`）：

- 登录用评测 Codex home 自己的 `auth.json`，复制进单元的文件夹。只复制已知文本类型的文件（`.md`、`.txt`、脚本、`.json`、`.toml`、`.yaml` 等）。凡是带用户登录或密钥的，任何深度都不复制：`auth.json`、凭据文件、密钥和证书（`id_*`、`*.pem`、`*.key`、`*.p12`）、secrets、`.netrc` / `.npmrc` / `.pypirc`、`.ssh` / `.aws` / `.git` 文件夹、`config.toml`（hooks、信任状态、profiles、MCP 服务器）、sessions、日志、历史、数据库、rules、hooks、plugins。链接（包括 Windows junction，技能文件夹常常就是）会跟进目标，因为 Codex 加载的就是目标，里面的文件过同样的筛选；副本里只有普通文件。复制完再把文件夹走一遍，出现这类名字、链接或其他类型的文件就停掉这个单元。
- ChatGPT 登录会在单元的副本里刷新 token，而刷新 token 只能用一次。单元文件夹删除前，刷新过的副本会写回评测 home（原子替换，且只在评测 home 的文件仍是当初复制的那份时写；否则这一行判为不干净，这一轮应停下）。所以日常组必须 `--jobs 1`，r5 会拒绝更大的并发。
- 它的 config.toml 是写出来的，不是复制的：只有 ccx 精简启动时保留的设置（`windows.sandbox`）、评测关掉的功能（apps、plugins、remote_plugin：不接账号连接器）和用户自己的 memory 设置。所以这几组测不到 `codex_lean_tools` 里 apps / plugins 那部分；网页搜索、图片生成和 goals 测得到。
- 在 Windows 上，这个 config.toml 还写入 `[windows] sandbox = "unelevated"`，四个日常组都一样（替换用户自己的 `windows.sandbox`）；其他系统不加任何东西。原因：Codex 在 Windows 上的 elevated 沙箱用全机共享的沙箱账户（`CodexSandboxOffline` / `CodexSandboxOnline`）跑命令，密码存在每个 CODEX_HOME 的 `.sandbox-secrets` 里。每个单元新建的 home 没有它，Codex 就启动需要 UAC 的安装助手；机器前没人点，安装被取消，所有命令都失败，子智能体停在 blocked、一个文件都没改（2026-10-30 实测，codex-cli 0.164.0）。从任何一个 home 重跑安装都会轮换共享账户，让其他 home 失效。换成 unelevated 沙箱后，同一个 home 不需要 UAC、也不需要密钥，就能跑命令、写文件。局限：用户真实的日常配置用的是 elevated 沙箱；这几组是在 unelevated 沙箱下比较各开关之间的差别，测的不是 elevated 沙箱本身。每行记为 `daily.windows_sandbox`（以及 `isolation.daily_windows_sandbox`），`daily-check` 也会打印。
- 它在单元的 `x-` 文件夹里，单元结束后随之删除。
- 评测 Codex home 不会得到用户的任何东西（唯一的写入是它自己刷新后的登录），所以其他各组的预检和单元间检查（那里出现 memories、AGENTS.md 或技能就拒绝）一点没变。每个单元自己的 home 是日常组写明的例外；另有两条审计例外：日常单元的 Claude 子运行可以加载技能、斜杠命令和插件（按运行记在 `audit.sub_skills`，不算问题；主导照 ccx2 审计），子智能体读单元自己的日常 home（memories 副本、`$CODEX_HOME`）在 `harness_audit` 里不算读私有上下文。Claude 子智能体仍用单元的设置文件（hooks 关、自动记忆关、禁止读真实 home），主导的隔离和审计和 ccx2 一样。在 `--claude-isolation flags` 模式下，用户设置层就是用户真实的 `~/.claude/settings.json`（hooks 仍关，用户级 CLAUDE.md 仍排除）；在 `config-dir` / `ccx-home` 下是单元的全新 home，所以 flags 模式下 Claude 那一侧更接近日常。
- 每行有 `daily`（复制了什么、来自哪些来源，只记名字；memory 设置；从 hub 读回的开关；副本名字和内容的 `sha256`，用来识别配对单元用的是不是同一份用户配置快照；登录的处理结果）、`sub_usage`（ccx 子智能体按类别的 token：input、cached、output，评审单列），指纹的 `models.daily`，以及 `isolation` 里 home 记为 `daily`、设置层记实际值；每个 ccx 运行的记录里有 `subagent_switches`。
- Codex 这边 `clean` 只换 HOME。这几组的 CODEX_HOME 里有用户 AGENTS.md、技能和 memories 的副本，所以 `ccx2daily_clean` 在 Codex 上只测到 `~/.agents/skills` 副本那部分（外加 Claude 那边、语言那一句和 Agent 工具）。

不花钱的自检：`python scripts/eval/r5.py daily-check --codex-home <评测 codex home>` 在临时文件夹里建一个日常 home，打印里面有什么（只列名字）然后删掉；带日常组的 `run --dry-run` 会列出要复制什么和各组的覆盖。

## 测量（来自 B3 计划；约 $20）

- **M1**（`codex_memories`、`clean`）：A = `ccx2daily`，B = `ccx2daily_nomem`，C = `ccx2daily_clean`。留出集 10 题 × 3 轮 + r5 10 题 × 2 轮：每组 50 个配对单元，每组约 $5。
- **M2**（`codex_lean_tools`）：D = `ccx2daily_leantools` 对同一个基线，题目相同。
- **决策规则（现在就定好）：** 四条全满足才改默认：right_B ≥ right_A（做对数不降：用户定的规则）；输掉的配对（A 对、B 错；McNemar）≤ 2；没有哪道题 B 每轮都错而 A 至少对过一轮；子智能体每个单元的 prompt token 中位数（`sub_usage.prompt` = ccx 工作运行的 input + cached）降 ≥15%，每个开关都用这同一个指标。有单侧缺失的配对或缺 token 数就判 Unknown，开关保持关。`r5.py summary` 在干净的配对单元上套用它（`b3_rules`）。
- 统计功效有限：基线约 95% 时，50 对只能看出 ≥10 个百分点的下降。输掉 2–3 对的边界情况，只对该组再补 50 个单元（约 $5）。
  *2026-10-31 跑完之后的修订（上面保留登记时的原文）：*"输掉 2–3 对"不是第二个门槛：规则下输 2 对算过，输 3 对算不过。上面那句确实要求这样的组再补 50 个单元；这次没有补跑，偏离了计划。它不改变这次任何判定：`clean` 输了 3 对（补跑也翻不回来），其他组都没有输 2 或 3 对。边界情况怎么理解（是对勉强通过的再确认，还是可选）留给下次事先登记，这里不定。现在 B3 规则算到的对数少于登记的 50 对时，`r5.py summary` 会另外打印"registered 50 pairs, counted N"。

命令（没有运行）：

```bash
python scripts/eval/r5.py daily-check --codex-home <评测 codex home>
python scripts/eval/r5.py run --taskset holdout --rounds 3 --arms ccx2daily,ccx2daily_nomem,ccx2daily_clean \
    --tag b3m1 --codex-home <评测 codex home> --budget 20 --jobs 1 --dry-run
```

## 跑第二半之前对评测脚本的改动（只加报告证据，规则原文不变）

留出集那一半按 token 中位数条件判 `codex_memories = false` 通过，但按配对看，单看中位数很脆弱（这一组 prompt 更低的配对不到一半，总量反而更高）。在跑 r5 那一半之前，`scripts/eval/r5.py` 补了更多证据，登记好的规则本身不变：

- **规则里的中位数是真正的中位数**（`statistics.median`：偶数个时取中间两个的平均），与规则原文一致，不再用 wall 字段那种“偏上的中间值”。四个条件和 Unknown 情形都和上面定的一样。这次改动之前报告的 m1h2 token 中位数用的是偏上的中间值（30 对，偶数个）：m1h2 要用真正的中位数重新汇总后才能引用或合并，如果因此改变了结论，以新结论为准。
- **旁边加配对统计，只做报告**（`b3_rules[...].paired`）：这一组 prompt 更低的配对占比、每对比值（这一组 / 基线）的中位数、总量比值，以及中位数之比的配对 bootstrap 95% CI（2000 次重抽样，固定种子），旁边再给一个按题目整体重抽的 bootstrap CI（每次抽题目，带上它的所有配对，和 r5 其他区间一样）：按配对抽把同一题的几轮当成相互独立，每题 2 轮以上时区间偏窄，应看按题目的那个。基线中位数为 0 的重抽样会被计数（`boot.dropped`）。`token_effect` 只在规则的 token 条件通过、总量比 ≤ 0.85、并且 ≥ 60% 的配对更低时才是 `consistent`，否则是 `not shown`。它从不改变 `result`。
- **两半一起判：** `summary --results a.jsonl b.jsonl --tag <留出集标签> --tag <r5 标签>` 读多个结果文件（同一行出现在两个文件里只算一次）和多个标签，登记的 50 对按一条规则判。
- **配对的两个单元快照不同：** 两个单元的 `daily.sha256` 不同，比的是用户的两套配置，不是开关。这一对的两个单元都不进规则的各项条件和配对统计，`snapshot_mismatch` 列出它们。去掉的那一对可能本来是输掉的配对，所以只要有这种配对，“通过”就改成 Unknown（“不通过”仍是不通过），和单侧输掉的不干净配对一样从严；如果所有配对都分开了，规则报告为 0 对上的 Unknown。没有哈希的一侧照常保留。（m1h2 的行早于冻结快照，所以对它们适用。）
- **每次调用只冻结一次快照：** `run` 在开始时把用户的 memories / AGENTS.md / 技能（以及日常 home 从用户 config 里取的那几项设置）复制一次到 `<work>/daily-snapshot`；每个日常单元都从这里复制，行里记 `daily.snapshot`（`frozen` 和它的 `sha256`），跑完删除这个文件夹（冻结失败时也删；被强行结束的运行留下的文件夹，工作目录检查能认出来，下次开始运行时删除）。
- **开关在每次运行里实际做了什么：** 每行有 `switches_applied`，来自这个单元每个 ccx run.json（`subagent_switches`、mode、agents），以及这些开关会给 Codex 加的 memory / 网页搜索 / 图片生成参数。ccx 的 run.json 不记 CLI 的 argv，所以这些参数是推出来的（`argv_recorded: false`），不是读回来的。
- **均衡的组顺序：** `run --arm-order balanced` 在一个带种子的组顺序上按题目和轮次依次取 Williams 设计（平衡拉丁方）的各行：每走完一整轮行，每组在每个位置出现的次数相同，并且排在其他每组（包括基线）前面的次数正好一半（10 题 × 2 轮、4 组时，不论种子都是每组 20 次里 10 次）。`--dry-run` 会打印这些“基线在前”的次数。行里记 `arm_order` 和 `arm_pos`。默认仍是 `shuffle`，以前各次运行的排程不变。第二半应带 `--arm-order balanced` 跑。
- **失败单元的证据：** 没做对的单元记 `hidden_failed`（没通过的隐藏测试 id），并把完整的隐藏 pytest 输出和最终 diff（在放入隐藏测试之前取）保存在 `<结果文件名>-artifacts/<标签>-<单元>/`；diff 保留 git 的原始字节（包括 CRLF 行），可以直接 apply。2026-10-31 起每次运行有自己的子目录 `<结果文件名>-artifacts/<UTC 开跑时间>Z/<标签>-<单元>/`，行里记为 `artifacts.run`；没有这个字段的旧行是平铺布局。
- **事后归因：** 如果运行期间用户真实 hub 的账本变大了，报告列出每条新行的 type、run_id、ts，以及 run_id 是否属于某个单元的 `ccx_run_ids`（评测泄漏），不属于的多半是同时在跑的真实会话；`preflight.json` 里存为 `postflight_ledger`。

## 少跑几趟：M4 / M3 / M5 对照组（2026-10-31 登记，在任何一个单元开跑之前）

B3 的第二批开关（M4 `ccx batch --merge`、M3 `[subagents] fork_turns`、M5 `[shared_context] dedupe`）目标是少发请求，三个都默认关。默认开之前要先测到"做对不低于基线"。评测脚本是 `scripts/eval/b3_arms.py`，每个实验两组：基线 = 今天出厂的做法，另一组只改这一个开关。

| 实验 | 基线 | 开关组 | 题 | 模型 |
|---|---|---|---|---|
| m4 | `ccx batch <plan>` | `ccx batch --merge <plan>` | 4 个 plan，每个 = round 2 十模块题的 4 个小块（`minutes` 2）+ 1 个 TRAPS2 陷阱块（`minutes` 5），每块带 `paths` 和自己的 `--check` | Codex gpt-6.1-sol medium，`--from user`，审查照出厂（auto） |
| m3 | `fork_turns = "all"` | `fork_turns = "none"` | round 2 的 4 道三文件修复（COMPOUND）+ 2 组各 4 个模块 | Codex gpt-6.1-sol medium，`ccx run --parallel`，审查关、不升档、不换家 |
| m5 | `dedupe = false` | `dedupe = true` | 2026-10-25 共享上下文 A/B 的 7 题 + 新题 t8（人重开问题、主导换个说法重申：去重删人的那句、保留主导的） | Codex gpt-6-luna low，`--context on`，审查关，只看第一次 |

公平性：两组的 hub 文件只差开关那一行（基线也显式写 `false` / `"all"`），开跑前按 ccx 自己的读法读回来核对；两组都 `[sessions] archive = "off"`（子会话 rollout 事后要读），单元结束后统一 `ccx archive --apply`。同一对的两组背靠背跑，谁先跑按题目和轮次交替。每个单元有自己的干净环境（`scripts/eval/preflight.py`：独立 TMP、git 身份、CCX_CONFIG、新 hub、评测专用 CODEX_HOME + `CCX_CODEX_ISOLATE=1`，Job Object 收尾）。m4 两组都让 ccx 自己决定 worktree（五个写入块、干净仓库 → 每块/每组一个 worktree），每块在它的运行留下的目录里只跑它自己的隐藏测试。

开关有没有生效，看 ccx 记下来的东西：m4 看 batch 输出的 `merged`；m3 看 run.json 的 `parallel_fork_turns`，以及发给子智能体的 prompt.md 里有没有 fork_turns 那句（换了家的运行 `parallel_fork_turns_moved` 剔除）；m5 看 run.json `shared_context` 有没有 `deduped`，并且确实附上了共享上下文。没生效的单元记 `switch_ok: false`，不进规则。

每个单元记：做对（块数或隐藏测试）、ccx 运行数（账本所有行：子智能体运行、审查、修复轮、拆出去的块）、审查次数和费用、请求数、`first_input` 之和（m3 再加每个子会话的首请求输入，从 rollout 读）、总 prompt token（每次运行的 fresh + cache 写 + cache 读；m3 的账本 usage 已含子会话，不再另加）、$、墙钟；m4 另记每块状态、修复轮、拆出数；m5 记 `est_tokens`、`deduped_chars`。

**判定规则（先登记）**，每个实验只在两组都跑完且开关都生效的配对上算：

1. 开关组做对数不低于基线（m4：全部块和陷阱块分别都不低于）；
2. 开关组的 ccx 运行数或 `first_input` 之和更低；
3. 开关组的总 prompt token 不更高（m5 只报告不判：去重每次请求只省几十 token，多一轮就多约 2 万前缀，而且后面每次请求都带着前面的轮次，总量和均值都由轮数决定；m5 的节省按第 2 条的 `first_input` 之和判）；
4. 只对 m3：不能有"开关组错、基线对、开关组的运行开过子会话"的配对（子会话缺上下文、父会话没兜住）。

全部满足 = 通过；任何一条不满足 = 不通过。完成的配对不到计划的 80%（计划对数由 `run` 写进每行），有单元开关没生效，或（m3）超过一半的配对两组都没开子会话（开关没机会起作用）= Unknown。单元运行失败（行里有 error）算缺失，不算开关没生效，再跑一次 `run` 会重跑它；预算只在一对开始前检查，不会停在一对中间。墙钟只报告，不判（M4 合并后预期更慢）。拆出去的块会从低档重新升档，比基线多一次机会，报告时注明。通过只说明可以考虑默认开，开不开另行决定。

**三条正式命令**（`--dry-run` 先看排程）。预估：m4 16 单元约 $3.8、m3 12 单元约 $2.8、m5 32 单元约 $0.6，合计约 $7.2。依据：2026-10-31 预跑 1 单元（m4 mp1 合并组，标签 b3pre，不计入正式结果）5/5 做对、2 次运行（合并 + 1 次审查）、$0.10、129 s、开关生效、无残留；其余是按 round 2 的估计。`--arms` 只用于预跑，要用单独的标签。

```bash
python scripts/eval/b3_arms.py run --exp m4 --tag b3m4 --codex-home <评测 codex home> --budget 5
python scripts/eval/b3_arms.py run --exp m3 --tag b3m3 --codex-home <评测 codex home> --budget 4
python scripts/eval/b3_arms.py run --exp m5 --tag b3m5 --codex-home <评测 codex home> --budget 1.5
python scripts/eval/b3_arms.py summary --tag b3m4   # 每个标签各看一次
```
