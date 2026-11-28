# 优势重测工具（实验性）

[English](strength-tools.md) · 中文

证据：工具仅为 **engineering check**；当前版本真实模型结果为 **not run**。
不改现有默认值、命令、选项、JSON 含义或判定；只用标准库。

## 清单与预算

```text
python scripts/eval/strength_retest.py plan context --dry-run --out context-plan.json
python scripts/eval/strength_retest.py plan memory --dry-run --out memory-plan.json
```

仓库外使用脚本绝对路径。两个入口只生成清单，不能调用模型。清单含 HEAD、工作区是否有改动、题目、分组、
轮数、历史成本估价、上限、中断规则和指标。`--unit-usd` 替换单单元估价，估价超上限退出 2。
估价不保证实际花费上限；真实执行前，统筹须预登记门槛、干净独立 clone/pin、最终题选择和运行时花费控制。
另有下述显式开启的串行 runner。

```text
python scripts/eval/strength_retest.py execute context --dry-run
python scripts/eval/strength_retest.py execute memory --dry-run
python scripts/eval/strength_retest.py execute context --run --budget 4 --out FRESH_CONTEXT_DIRECTORY --codex-home EVAL_CODEX_HOME
python scripts/eval/strength_retest.py execute memory --run --budget 3 --out FRESH_MEMORY_DIRECTORY --codex-home EVAL_CODEX_HOME
```

`execute` 默认只估价。付费执行必须同时给出 `--run`、有限正数 `--budget` 和全新输出目录；
不带 `--tasks` 时 context 上限 $4、memory 上限 $3，带 `--tasks` 时上限是 min($10, 单元数 × $0.15)。dry-run 分别显示本次预算与任务上限，估价超过本次预算时退出 2；
冻结清单在开跑前记录实际总预算和单元预留。复用 `seven_func` 的 ccx 命令与隔离 hub，每个单元有全新的
repo、客户端 home 和配置，不寻找或复制凭据。有 Codex 单元时必须给 `--codex-home EVAL_CODEX_HOME`：
一个你自己登录过一次的专用目录（`CODEX_HOME=<dir> codex login`），检查方式同 `p4_long_session.py`
（preflight 的 `check_codex_home`：绝对路径、不和你自己的 home 重叠、只看登录文件是否存在、没有
AGENTS.md/rules/plugins）。不给时，有 Codex 单元的运行在第一个单元前就停（新建的空目录没有登录，见 issue #320）。
检查通过后按 p4 的做法准备这个目录：没有 `config.toml` 就写一份（Windows 上设 unelevated 沙箱），删掉同步进来的
`plugins/`。只传路径；所有 Codex 单元都把它当作 `CODEX_HOME` 和 `CODEX_SQLITE_HOME`，所以 Codex 会话记录集中在
这个目录，不在单元目录里，而且跨运行保留（之后的运行检查时可能要求你清理）。DeepSeek 的认证真跑前通过 CLI 环境显式提供。
每次调用传入 `--budget`，串行单元预留由 `--unit-budget` 控制（默认 $0.05），关闭升档、
回退、子智能体和审查。要作受控模型比较，必须先预登记隔离 home 的提供方设置和计价。

**单元里的 agent 不能打开什么（#454）。** 每个单元都禁读：本人的各个 home、hub 和配置（同 `p4_long_session.py`，
即 preflight 的 `forbidden()`）、运行所在的检出及其 git worktree、该检出的 `scripts/eval/`（题目生成器和隐藏测试，
如 `round2_a/`）和 `docs/research/data/`（冻结的题目文件，如 `round2-tasks/`）、`--tasks` 文件本身，以及每个
`--hide PATH`（可重复，例如正式运行用独立 clone 时的日常开发检出；按启动目录转成绝对路径并去重，git 检出会把它的
其他 git worktree 一起加进来，不存在的路径或包含运行单元所用 Python 的路径会被拒绝）。这是默认行为，不带 `--tasks`
也生效：#454 之前单元能读到上面全部内容。每个路径按已知的所有写法列入：原样（保留 junction 或符号链接）、resolve
之后，以及 Windows 上的 8.3 短名。**评测目录放哪：**`--out` 必须在 clone 之外、日常检出（任何 `--hide` 路径）之外、
本人的 home/hub/配置之外，否则拒绝；`--out`、`--claude-home`、`--codex-home` 的路径里也不能带下面的内容模式字样，
否则同样拒绝。Claude 单元对每个路径有 Read/Edit 拒绝规则（Claude Code 2.1.316 文档：Read 规则也尽力作用于
Grep 和 Glob，Edit 规则作用于所有改文件的工具）。Codex 单元无法限制读取：`workspace-write` 只限制写，`codex exec`
（codex-cli 0.164.0 `--help`）没有禁读选项，所以只能审计、不能拦截。每个单元结束后审计它 ccx 日志里的全部工具调用
（行里的 `path_audit`）。先屏蔽单元自己的目录、登录用的 home 和 Python 解释器的目录（包含禁读路径的不屏蔽），所以处理自己的文件、运行 Python
（以及本检出的 `ccx.py`）都不算命中。命中包括：工具调用任何位置出现 preflight `path_hits` 认识的任何写法的禁读路径
（绝对路径里的 `..` 解析后再比一次）；工具调用任何位置（包括 Write/Edit 写入的正文，防"先写脚本再执行"）出现与路径
写法无关的内容模式（`round2_a`、`round2_bc`、`round2-tasks`、`round2~N`、`l5_memory`、`shared_context_ab`，能抓到
`cd ../.. && cat scripts/eval/round2_a/x.py` 这类相对读法）。只在导航字段里看（命令、文件路径、Grep/Glob 的 path 或
pattern，不看写入的正文，所以代码里写 `tree` 或 `../..` 不算命中）：任何命令里以 `..` 或 `./..` 开头的相对路径落到
单元目录之外，按这次运行的工作目录判断（run.json 的 `cwd`：repo，或 ccx worktree `<unit>/.ccx-worktrees/repo/<run id>`，
从那里 `cd ../../..` 仍在单元内）；`cd`/`pushd`/`Push-Location`/`Set-Location`（跳过 cmd 的 `/d`）不带参数、到 `~`、
或到单元外某个包含禁读路径的上级目录；解析不了的 `cd` 目标（变量、子 shell）只要带 `..`（cd 只在命令开头的位置才算，`echo cd` 不算；`cd ~`、`cd $HOME`、
`cd %USERPROFILE%` 会命中，因为它们到达 home，而 home 是禁读路径的上级目录；`cd "$CODEX_HOME"` 这类其他变量不展开，
只有带 `..` 才算命中）；对禁读路径的上级目录做递归
搜索（`rg`、`grep -r`、`Get-ChildItem -Recurse` 等）或 Grep/Glob。命中时该行记为无效（`--on-invalid continue`）或停止
整组（默认）。dry-run 带 `--tasks` 或 `--hide` 时输出 `isolation` 字段：`--hide` 路径、第一个单元实际禁读的全部路径和
内容模式。

**答案文件和其他单元（#467）。** 不该拿到答案的臂，单元目录里不放答案级文件：context 的 off 臂不写 lead 转写
（`--context off` 时 ccx 根本不读它；会话 id 和环境变量与 on 臂相同），`nomem` 只有干扰笔记。第一轮把转写（即商定的
答案）写进了每个 off 单元的 `claude-home/projects/lead/`。Claude 单元的转写放在共用的登录 home 里
（`<claude-home>/projects/ccx-strength-synthetic/`），这个目录现在对每个单元都是禁读路径（deny 规则加审计），不再被
home 屏蔽规则放过，只有 on 单元读自己的那份不算命中。每个单元也不能读 `--out` 里的其他内容：先屏蔽本单元目录，工具
调用里剩下的任何 `--out` 写法都算命中（别的 `unit-*`，里面有 on 臂的 `shared-context.md` 或 mem 臂的笔记，以及
`manifest.json`、`results.jsonl`、`report.json`），绝对路径、相对路径、junction、8.3 短名的处理同其他禁读路径；
`--out` 及其上级目录也算禁读路径的上级目录（`cd` 过去、递归搜索都算）。Claude 单元对这些运行文件和本单元之前的单元
另有 Read/Edit 拒绝规则，写成少量目录通配（`unit-00*`、`unit-010*`、`unit-0110`）：单元按顺序跑，后面的还不存在；
每个单元一条规则会让 settings 很长；自 #588 起 ccx 把长 `--settings` 写进文件，不再撑爆命令行，也不再因长度拒绝启动（#589）。`--out` 放在登录 home 里面会被拒绝（审计把那个 home 当成单元自己的而屏蔽）；`--out` 也不要放在系统 TEMP 下，那里有别的程序的文件，单元自己的临时文件也会写到那里。读本单元自己的 repo、`shared-context.md` 或记忆都不算命中。
dry-run 的 `isolation` 字段还列出每个臂的答案级文件（`answer_files`）和每个单元在 `--out` 里被挡住的内容
（`siblings`），开跑前核对。

**共用的登录 home（#470）。** 各单元共用的 home 里有每个单元的会话记录：Codex home 的 `sessions/`、
`archived_sessions/`、`history.jsonl`、`session_index.jsonl`（按首条提示词生成的标题）、`memories/` 和状态/日志
数据库（`*.sqlite`；`CODEX_SQLITE_HOME` 就是这个 home），Claude home 的 `projects/<cwd slug>/`（会话转写和工具
结果）、`file-history/`、`todos/`、`shell-snapshots/`、`session-env/`、`history.jsonl` 等。on 臂和 mem 类臂的
提示词与工具结果里有答案。先屏蔽本单元自己的部分，之后工具调用里只要还剩共用 home 里面的任何写法，对每个单元都算
路径审计命中：记录文件、通配（`sess*`、`*/...`）、只写到 home 这一层（`ls <home>`）、新出现的目录、Python 对它的
`os.path.join` 或 `glob`，home 的各种写法都算，home 被屏蔽时也算；只放过 CLI 启动要读的 `auth.json`、
`config.toml`、`.credentials.json`。匹配前先展开单元的 home 变量：`$CODEX_HOME`、`${CODEX_HOME}`、
`$env:CODEX_HOME`、`%CODEX_HOME%` 和 `os.environ['CODEX_HOME']`（`CODEX_SQLITE_HOME`、`CLAUDE_CONFIG_DIR`
同理；还有 `${env:X}`、`${X:-默认值}`，但 `$CODEX_HOME_X` 这类更长的变量名不算）都换成它指向的 home，所以指向
单元内部的变量仍算自己的；连 `echo $CODEX_HOME` 也算命中（单元本来就没理由关心共用 home）。`cd` 进 home 或搜索
home 也算命中。本单元自己的部分
是：它的 Claude 项目目录（repo 和各 ccx worktree 对应的 slug；超过 200 字符的 slug 会被 Claude Code 截断并加哈希，
按前 200 个字符匹配），以及它自己的 Codex rollout（按运行记录里的会话 id 找）。Claude 单元另有 Read 拒绝规则：所有
`projects/*/*.jsonl` 转写（包括自己的，它用不到）、子 agent 目录和 memory、其他记录目录（包括 `plans/**`，所以
headless 运行里的 plan mode 可能受影响），以及本次运行之前单元的项目目录（少量通配）；其他运行的项目目录交给审计。
这些规则和 `--out` 里其他单元的规则都只加 Read（写进去不会泄题，事后审计兜底），为了让 `--settings` 命令行够短；
证据文件 `manifest.json`、`results.jsonl` 另外保留 Edit 规则，防止被篡改。`--out` 放在开着 8.3 短名
的 C 盘 Temp 下时，A2 最后一个单元的 settings 约 19000 到 21500 字符。`execute` 开跑前按真实的 `--out` 和
`--claude-home` 算出最后一个单元的 settings 长度并报告（不再因长度拒绝开跑，#589）；最后一个单元的编号落在 Claude Code 保留的项目
目录名前 200 个字符之外时也拒绝开跑；`execute --dry-run` 同时给了这两个参数时会输出它
（`claude_settings_chars_last_unit`）。Codex 单元只能审计。Codex memories（codex-cli 0.164.0 中
`features.memories` 为 stable、默认开启）在每个单元里已经关掉（`CCX_CODEX_ISOLATE`），所以不会不经工具调用就
跨单元注入。没有选择每个单元各用独立会话目录：那要把登录文件复制或链接进每个单元的 home；不保存会话
（`codex exec --ephemeral`、`claude -p --no-session-persistence`）又会打断 ccx 在几次尝试之间的 resume。

**隔离的已知缺口（#454-#472）。** 审计是检测手段，不是拦截，只看工具调用里写出来的东西。认不出来的有：间接读取
环境变量（`Get-ChildItem Env:`、`[Environment]::GetEnvironmentVariable`、`printenv` 再传下去），运行时拼出来的路径
（脚本里拼接字符串、单元 home 变量以外的变量、子 shell），8.3 短名和长名混写的路径，以及超出已解析格式的 DSH 日志。
Codex 单元什么都禁不了，只能审计。Claude 的拒绝规则是尽力而为：通配依赖 Claude Code 按 gitignore 规则匹配 `*`，
之前单元的项目目录规则只按 `--out` 的绝对路径和 resolve 写法生成，没有 8.3 短名写法；这两点都没有用真实 CLI 验证。
`--out` 里其他单元的目录和其他运行的 Claude 项目目录只有 Read 规则或没有规则，靠审计兜底。命中会让该行无效，但拦不住
那次读取。以后发现的绕过方式写进这里，不再逐个加规则。

**几层保护的关系。**真正的保护是 Claude 的 deny 规则，加上正式运行用独立 clone、并把本机每份其他检出都传给 `--hide`；
审计只是尽力而为的兜底，用来事后发现漏过去的读取，主要针对读取拦不住的 Codex 单元。审计看不全所有写法，之后发现的绕过
写进这里的局限，不再一轮轮补。已知抓不到的：短名和长名混写的路径；从文件系统根目录搜索；先在一次工具调用里 `cd` 到单元
外一个本身不含禁读路径的目录，再在后续调用里用相对路径读（每次调用都按运行工作目录判断）；Write/Edit 写出的代码不提
内容模式字样就够到禁读目录（只检查运行它的命令）；运行时拼出来的路径（变量、字符串拼接、读环境变量）；preflight
`tool_inputs` 解析不了的 DSH 日志格式。Codex 的读取只能事后发现。第一次真跑 Codex 单元时，要看 `path_audit` 里有没有
`cd ~` 这类没读任何东西的误报。

`results.jsonl` 保留隐藏测试失败、运行失败和中断。花费未知时保留全部单元预留并停止，不当作零；
总预算耗尽、单次超预留、中断，或 ccx 回执 `status: "error"`（如 `kind: auth`）时也不再启动下一单元；
`unified_summary.py` 把这种行算作无效（Unknown），不算任务失败。已发请求可能超出 token 监控预算，因此不是账单保证。
报告保留计划分母、尝试数和 Unknown 门槛。不自动返工，与历史允许一次修复的结果分开报告。
要求全新输出目录，防止重置花费。本轮只测假 CLI，未跑真实模型或 CI。

| 清单 | 题目和轮数 | 分组 | 单元数 | API 等价美元上限 |
|---|---|---|---|---|
| context | 原有 6 个有利场景 + 1 个中性场景，3 轮，Codex 和 dsh | off/on | 84 | $4 |
| memory | 原有 3 个约定题 + L5 日期、路径、JSON 题，3 轮，Codex | nomem/mem/hubmem/hubstart | 72 | $3 |

来源：[旧上下文设计](2026-10-25-shared-context-ab.zh.md)、`scripts/eval/seven_ab.py` 分组、
`scripts/eval/l5_memory.py` 题目。6 个记忆题都用过，是开发/重测题，不是未见最终集。
前 3 组为扩样后的 6 × 3 × 3，共 54 单元；hubstart 另加 18 单元，不自动成为新主比较。

```text
python scripts/eval/strength_retest.py probe-hook --hub SYNTHETIC_HUB --cwd SCRATCH_PROJECT --as codex
```

以独立进程启动真实命令 `ccx mem delta --as codex --peek`，隔离配置、关闭额度探测。
hub 必须只放合成资料，因为 CLI 可能初始化状态。不调用模型、不安装 hook、不访问客户端 home。
它检查载荷输出，不检查模型做题或原生桌面 SessionStart 执行；后者仍是 **Unknown**。
`execute memory` 的 hubstart 组会把这个真实载荷传入子任务；mem 使用项目上下文文件，hubmem 使用共享记忆，
nomem 只有无关记忆。四组使用相同的无关记忆。原生桌面 hook 是否执行仍为 Unknown。

## 跨家账本多次校验

```text
python scripts/eval/ledger_reconcile.py --run run-a.json --run run-b.json --ledger ledger.jsonl --cli-reports observed.jsonl --out reconciliation.json
```

只读明确文件。CLI 归一化观测行含 `run_id`、从 0 开始的 `attempt`、`vendor`、`model`、`usage`、可选 `cost_usd`。
usage 是新输入 `input_tokens`、缓存写 `cache_write_tokens`、缓存读 `cached_input_tokens`、输出 `output_tokens`。
缺失保留 Unknown；重复行或观测判 Fail，不静默覆盖。每个 attempt 用自己的 agent/model，
不按 `record.to` 推断跨家重试后的厂商。`--providers` 接受归档、不含凭据的 JSON providers 表；
自定义 provider 来源不足保留 Unknown。实际原生模型另列，请求别名与原生模型 ID 不同也可能是 Unknown。

可用 `--streams stream-manifest.json` 替代 `--cli-reports`：

```json
[{"run_id":"example","attempt":0,"cli":"codex","path":"events.0.log","usage_scope":"attempt"}]
```

路径相对清单；离线原生事件读取支持 Codex、Claude、dsh，不复用生产 adapter 解析器。
确认是单次 attempt 总量才写 `usage_scope: attempt`，Codex resume 可能是会话累计量，否则保留 Unknown。
不会自动找 home/会话。Claude modelUsage 提供原生模型 ID，Codex/dsh 常缺此项。
`observed_vendor` 可填独立归档来源，单凭 CLI 不能证明厂商。
CLI 自报金额只对 attempt `cost_usd`；账本的 `ae_usd`、`cost_usd` 分别对同名 attempt 总和，
与 `ccx/ledger.py` 一致。不把账单与 API 等价价格混比；只验证算术和来源一致，不证明账单准确。
退出 1 是明确不一致、重复或孤立观测；退出 0 仍可能含 Unknown。

## 模型适配榜第一版

```text
python scripts/eval/model_fit_board.py --results docs/research/data/2026-10-25-l5-memory.json --out board.json
```

可重复给 `--results`，支持 JSON/JSONL 与 `rows`/`results` 导出。按任务类型 × 模型分组，分开来源、版本和 arm。
内置本轮上下文/记忆题类型；其他题用 `--task-types types.json` 提供题号到类型映射，缺失保留 Unknown。
`--outcome ok|ok_first|ok_final` 明确选隐藏测试字段，不把状态、自报当成功。
报告样本数、成功数、通过率、已知花费、缺失结果/成本数、每成功成本。失败计入分母和花费。
结果缺失则通过率 null；成本缺失或成功为零则每成功成本 null。主导/子 agent/审查分项须完整；
总额 `usd` 须已含修复。跨模型重试按组合分组，不只归功于最后一个模型。
存在 `env_clean=false` 时同时报全部行和明确干净行，各有分母。样本 <10 标 **样本少**。
这是历史描述，不是当前受控模型排名。

## A 组与 `--check`（脚手架默认值）

A 组（`strength_retest.py`）运行 ccx 时带 `--check "python -m pytest -q"`。这不是 A 组的设计选择：
`scripts/eval/seven_func.py` 对所有调用方固定了这个写法（2026-10-25 起，第一轮也是）。A 组的题没有可见测试，
检查收集不到测试（pytest 退出码 4 或 5），ccx 对几乎每个单元记 `check_broken`。`check_broken` 不触发重试或升级，
也不进自动学习；runner 本来就固定了 `--no-escalate --no-fallback --no-subagents --review off`；两臂提示词里有同一句
验收说明。对错只来自隐藏测试。

读数规则：分析 A 组时不用 `kind` 和 `rc`（`rc` 只反映收据的退出码），也不把 `check_broken` 当作“声明成功”。
正式跑完后核对每个单元是否恰好 1 行账本、1 次 attempt。记录在第二轮预登记修改记录里（2026-11-25，#511）。
只是 48 个开发行上的工程检查，不说明模型质量。
