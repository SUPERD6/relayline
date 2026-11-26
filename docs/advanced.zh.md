# 高级：所有命令和开关集中一页

[English](advanced.md) · 中文 · 回到 [README](../README.zh.md)

README 和 `ccx -h` 只给最短的路：安装、`ccx setup`、`ccx run`、`ccx show`、`ccx verify`。其余都在这一页。**一个都没删**：
下面每个命令、选项和配置项都照常能用，只是不放在默认路径里。本页内容以 `python ccx.py -h`、各命令的 `-h` 和
`config/tiers.toml`（ccx 0.7.0）为准；和本页不一致时，以它们为准。

## 标签怎么读

| 标签 | 意思 |
|---|---|
| **实测** | 这个选项或它的默认值有公开的测量结果，来源已链接或写明 |
| **实验性** | 已发布、默认关（或没真跑过）；效果是 Unknown，或只测了一部分 |
| **已测不推荐** | 测过，候选没过门槛（或证据是 Unknown）；留着供复现 |
| **普通功能** | 日常辅助或管线，不对效果做任何声明 |

Pass / Fail 的说法沿用[功能详解「实验性、已测不推荐」](features.zh.md)和[实测](measured.zh.md)。它们是旧代码上的历史结果，
不是对今天 main 的测试。

## 在哪里设置

- `ccx -h`：日常命令。`ccx advanced`（等于 `ccx -h --all`）：所有分组。`ccx dev`：开发者命令（`ccx dev trial` 就是
  `ccx trial`）。`ccx <命令> -h`：单个命令的完整说明。`ccx --version`。
- `ccx config list | get | set <键> <值>` 改下面表里的键，写进你的个人配置（`~/.ccx/config.toml`，或 `CCX_CONFIG`
  指向的文件）。默认值在 `config/tiers.toml`；`<hub>/ccx/tiers.toml` 用同样的结构，只写你要改的键。`config set`
  不认识的键（分级表、角色表、provider、`[review] also` 等）直接改这个文件。
- 项目级设置：项目里的 `.ccx/`（`ccx project init`）、`.ccx/roles.toml`（角色）、`.ccx/autonomy.toml`
  （项目只能把自主档位调低）。

## 命令

### 日常（`ccx -h` 显示的）

| 命令 | 做什么 | 标签 |
|---|---|---|
| `setup` | 引导首次运行：check、hub、init、sync（先问）、doctor、selftest。`--yes`、`--hub` | 普通功能 |
| `doctor` | 检查安装、登录和接线。`--verbose`、`--codex-lead`、`--backfill-kinds`（一次性，见下） | 普通功能 |
| `doctor --codex-rule` | 打印一条规则，让沙箱里的 Codex 主导能在沙箱外运行 ccx | 实验性（还没在真实运行里核对过） |
| `run` | 把一件事交给另一个智能体（全部选项见下） | 实测：见[实测](measured.zh.md) |
| `ask` | 快速只读的第二意见（`--to`、`--from`、`--cwd`、`--brief-file`） | 普通功能 |
| `resume` | 在同一个子会话里接着做。`--bg --wait`、`--env-fixed`、`--model --effort`、`--review`、`--check`、`--tier`、`--no-escalate`、`--budget`、`--max-usd`、`--namecheck`、`--from`、`--brief-file`、`--user-task-file` | 普通功能 |
| `stop` | 停掉正在跑的委派（整棵进程树）。`--wait` | 普通功能 |
| `undo` | 把可写运行改过的文件放回去；不带 `--apply` 只演练；`--wrong` 同时记一个判定；`--piece` 用于合并批次的运行 | 普通功能 |
| `verify` | 记录你的判定（`--ok 1/0`、`--note`、`--reason`、`--dismiss`）；抽查和扫描选项见下 | 普通功能 |
| `show` | 查看一次运行：`--full`、`--wait [秒]`、`--any`（多个 id） | 普通功能 |
| `q` | 项目的工作队列：`add`、`ls`、`tree`、`budget`、`done`、`accept`、`run`、`resume` | 普通功能 |
| `ui` | 实时页面：`--project`、`--no-open`、`--port`、`--days`、`--export FILE`、`--demo`、`--keep` | 普通功能 |
| `mem` | 共享记忆：`add`、`verify`、`search`、`stale`、`delta`、`show`、`status`、`compact`、`kinds`、`report`、`suggest`、`suggestions`、`accept`、`reject` | 普通功能 |
| `handoff` | 把接力棒交给另一个主导；`--from-transcript` 从旧会话文件拼出来 | 普通功能 |
| `lead` | 主导每一轮重读多少：`--breakdown`、`--cache`、`--suggest`、`--hours`、`--limit`、`--session`；`--hint`、`--threshold`、`--as` 给钩子用 | 普通功能 |
| `demo` | 用虚构数据看 `ccx ui`，不需要账号：`--no-open`、`--port`、`--export`、`--dir`、`--keep` | 普通功能 |

### 记忆和上下文

| 命令 | 做什么 | 标签 |
|---|---|---|
| `ctx` | 每个子智能体都读的项目上下文文件：`init`、`show`、`add` | 普通功能 |
| `project` | 项目层（`.ccx/`）：`init`、`status`、`compact` | 普通功能 |
| `fresh` | 把一段很长的对话交给同一工具的新对话：`--as`、`--session`、`--note`、`--no-model`、`--max-chars`、`--launch`；`--minutes`、`--b`、`--risk` 只在开了 `lead.model_by_task` 时才有用 | 普通功能；按任务选模型那部分是已测不推荐（Unknown） |
| `inbox` | 把用户给你的文件或邮件存进 `.ccx/inbox`，加一行日志：`--file`、`--name`、`--by` | 普通功能 |
| `skills` | `find`（搜共享库）、`install`（`--apply`、`--replace`）、`stats` | 普通功能 |

### 账目和报告

| 命令 | 做什么 | 标签 |
|---|---|---|
| `stats` | 按智能体和档位看 token 与用时：`--summary`、`--days` | 普通功能 |
| `report` | 静态 HTML 看板；`--days`、`--out`、`--no-lead`、`--publish`、`--include-evals`；`--daily [日期]`（加 `--tz`、`--quota-events`、`--quota-workspace`、`--quota-split`、`--real-use`）写某一天的一页 Markdown | 普通功能；只有 `ccx trial` 量出来了才显示节省 |
| `quota` | 按节奏看订阅额度：`--probe`、`--refresh`、`--backfill` | 普通功能 |

### 智能体之间（开着的会话互相调用）

| 命令 | 做什么 | 标签 |
|---|---|---|
| `peek` | 只读查看本项目里另一个工具的开着的会话（`--session`、`--turns`、`--max-chars`、`--json`、`--cwd`） | 普通功能 |
| `board` | 看未读的对话板消息：`--as`、`--thread`、`--all`、`--limit`、`--peek`、`--init`、`--sync`、`--force`、`--cwd` | 普通功能 |
| `say` | 给其他开着的会话留言：`--to`、`--thread`、`--from`、`--now`、`--codex-thread`、`--wait`、`--resume`、`--cwd` | 普通功能 |
| `reply` | 回复一条对话板消息：`--from`、`--cwd` | 普通功能 |

### 进阶（hub、多个项目、接线）

| 命令 | 做什么 | 标签 |
|---|---|---|
| `init` | 创建共享 hub：`--hub`、`--snapshot`、`--external-sync`、`--force` | 普通功能 |
| `projects` | 你的项目目录：`scan`（`--root`）、`show` | 普通功能 |
| `where` | 一句话说的是哪个项目：`--limit` | 普通功能 |
| `intake` | 你在自己的私有 GitHub 仓库里提 issue 当任务：`status`、`list`、`pull`、`ask`、`done`（`--pr`、`--branch`、`--cost`、`--unverified`、`--close`） | 普通功能（需要 `intake.github`） |
| `sync` | 把技能、记忆、钩子、MCP 接进两个工具；不带 `--apply` 只演练；`--only skills,memory,hooks,mcp` | 普通功能 |
| `config` | `set`、`get`、`list` | 普通功能 |
| `uninstall` | 移除 ccx 的钩子、标记块和链接；不带 `--apply` 只演练 | 普通功能 |
| `repair` | 重算修正计数方式之前写下的账本行；不带 `--apply` 只演练 | 普通功能 |
| `agents` | 每个智能体 CLI：厂商、能做什么、测过的版本 | 普通功能 |
| `ability` | 按任务看模型证据和你的偏好：`show`、`rebuild`、`set 厂商.模型 任务 prefer\|avoid\|clear`、`--json`；只作参考 | 普通功能（偏好暂时不影响路由） |
| `roles` | 可选的角色分配：`show`、`set`、`unset`、`--cwd`、`--project`、`--ability` | 普通功能；默认为空 |
| `relay` | 额度接力：`capture` 和 `continue`（`--to`、`--budget-seconds`、`--old-stopped`、`--launch`、`--force-unconfirmed`、`--check`、`--use-packet-check` 等） | 实验性（需主动开启，不做透明接管；见 [relay](relay.zh.md)） |

### 维护（`ccx -h --all` 只列名字）

| 命令 | 做什么 | 标签 |
|---|---|---|
| `task` | `status`、`resume`（`--same`、`--from`）有断点的任务 | 普通功能 |
| `send` | 往开着的 Codex 对话里推一条消息：`--to codex`、`--thread`、`--list`、`--wait`、`--force` | 普通功能 |
| `plan` | 拆任务：`size`、`check`、`template`、`record`、`show` | 普通功能 |
| `batch` | 跑一个计划文件：`--lanes N`、`--merge`、`--no-merge`、`--force`、`--from` | 普通功能；`--merge` 实验性，`--lanes` 已测不推荐当默认 |
| `route` | 哪个智能体、模型、强度来做，要不要派 | 普通功能 |
| `propose` | 同上，做成一个让人点头的提议（`--no`、`--stats`、`--days`） | 普通功能 |
| `way` | 一件事，一到两个做的人：`--with`、`--check`、`--yes`（约两倍花费）、`--dry-run`、`--stats`、`--risk`、`--kind`、`--label`、`--force` | 普通功能 |
| `discuss` | 多个模型的简短讨论：`--with`、`--rounds`、`--tier`、`--dry-run`、`--confirmed`、`--bg`、`--show`、`--list`、`--context-file` | 普通功能 |
| `turn` | 每轮钩子的那一行：`--as`、`--threshold` | 普通功能 |
| `sum` | 跑一个命令，只留一个简短摘要：`--kind`、`--max-chars`、`--shell`、`--ask` | 普通功能 |
| `archive` | 归档已结束的会话：`--older-than`、`--apply`、`--restore` | 普通功能 |
| `autonomy` | 总管档位：`set [L0\|L1\|L2] --project --auto-merge`、`merge 运行ID --apply` | 普通功能（默认 L1） |
| `selftest` | 测每个已安装的智能体：`--agents`、`--provider` | 普通功能 |

### 开发者（量 ccx 自己；也可以写成 `ccx dev <命令>`）

| 命令 | 做什么 | 标签 |
|---|---|---|
| `trial` | 一周里一半自己做、一半委派：`start`（`--days`、`--rate`、`--note`）、`stop`、`tag`、`report`（`--markdown`） | 普通功能 |
| `ab` | `done --ok 0\|1 AB编号`：关闭一个 A/B 自己做的样本 | 普通功能 |
| `bench` | 路由用的公开基准数据：`sources`、`refresh` | 普通功能 |
| `improve` | 给技能或工具记一个问题和修法：`add`、`list` | 普通功能 |
| `namecheck` | 查改过的 Python 函数里没有任何作用域定义的名字：`--run`、`--base`、`--json`；命中退出码 1 | 实测：见[配置注释](../config/tiers.toml)（本仓库和标准库 0 误报，r5 文件里唯一一次命中是真 bug） |

## `ccx run`：全部选项

多数运行只要任务、`--check`，偶尔加 `--mode`、`--worktree`、`--bg`。其余是用来控制的。

| 分组 | 选项 | 标签 |
|---|---|---|
| 任务 | `brief ...`（或 `--brief-file`、标准输入）、`--user-task-file`、`--label`、`--cwd`、`--project`、`--rules-ok` | 普通功能 |
| 做什么、在哪做 | `--mode read\|write`、`--worktree`、`--no-worktree`、`--base head\|upstream`、`--new`、`--fork`、`--seat 名字`、`--mcp` | 普通功能 |
| 验收 | `--check CMD`、`--review auto\|on\|off`、`--namecheck warn\|fail\|off`、`--strict-brief` | `--check`：实测（跑的测试点名了改动代码的检查算“强证据”，七核心 r2）；`--strict-brief` 实验性；其余普通功能 |
| 后台 | `--bg`、`--wait 秒` | 普通功能 |
| 谁来做 | `--to`、`--from`、`--provider`、`--role`、`--model`、`--effort`（只和 `--model` 或 `--provider` 一起才生效）、`--tier T0..T4`、`--tradeoff save\|balanced\|fast\|cheapest`、`--no-escalate`、`--no-fallback` | 默认 `--tradeoff save`：实测（七核心 A/B，PR #30） |
| 路由评分表 | `--files`、`--independent-parts`、`--coupling`、`--clarity`、`--risk`、`--novelty`、`--b`、`--minutes`、`--kind` | 普通功能 |
| 上限 | `--budget 美元`（它自己的子智能体）、`--max-usd 美元`（整次委派）、`--allow-subagents`、`--no-subagents`、`--subagents auto\|off\|N`、`--parallel` | 普通功能 |
| 上下文 | `--context auto\|on\|off`、`--user-words-file 路径` | `--context` 普通功能；`--user-words-file` 实验性 |
| 自主和队列 | `--autonomy L0\|L1\|L2`、`--approved`、`--proposal`、`--task`、`--step`、`--quota 智能体=已用`、`--force`、`--no-ab` | 普通功能 |
| 先看看 | `--dry-run`：显示会试哪几档；什么也不跑 | 普通功能 |

上面表里没写的其他命令选项：`ccx q add`（`--brief --dep --parent --check --minutes --mode --kind --to --budget --plan`）、
`q run`（`--max --once --lanes --gate --from --force --bg`）、`q accept`（`--all-ready --check --dry-run --into-protected`）、
`q done`（`--ok --note`）、`verify` 的抽查（`--sweep --after-h --sample --list --days --project --state --include-evals
--builtin --b --agent-id`）、`route` 和 `propose`（`--lead --ctx-files --ctx-tokens --lead-ctx --turns-left --requests
--needs --quota`）。都是**普通功能**，详见 `ccx <命令> -h`。

## 配置项（`ccx config set <键> <值>`）

默认值是 `config/tiers.toml` 里发布的值。

### 路由和谁来做

| 键（默认） | 作用 | 标签 |
|---|---|---|
| `routing.mode`（`auto`） | `off`：ccx 不派新活；审查、`ask`、`discuss` 和对话照常。`--force` 可绕过 | 普通功能 |
| `defaults.tradeoff`（`save`） | `save`、`balanced`、`fast`、`cheapest`，或 0..1 旋钮 | `save`：实测（七核心 A/B，PR #30） |
| `policy.picked`（空） | 你为所有活选的档位；预先授权这一档会派的活；空 = 先提议 | 普通功能 |
| `routing.require_ready`（`true`） | 优先已安装且有本地登录证据的 CLI | 普通功能 |
| `routing.default`（`auto`） | `self_first`：先自己做的派活门（[self-first](self-first.zh.md)） | 实验性（未实测） |
| `routing.small_self`（`false`） | `route` 和 `propose` 建议小活自己做（[小任务](small-tasks.zh.md)） | 实验性（等实测一轮支持） |
| `routing.small_self_by`（`files`）、`routing.small_self_files`（1） | “小”按什么量：文件数，或 `cost` | `cost`：实验性 |
| `routing.small_self_overhead_usd`（0.035）、`routing.small_self_quota`（0.9） | `cost` 的门槛，和用到多少额度后小活照旧委派 | 实验性（0.035 是 pg1 账本中位数） |
| `routing.small_self_run`（`false`） | 对主导拒绝小活的 `ccx run`；`--force` 可绕过 | 实验性 |
| `routing.strict_escalate`（`false`） | 没验收的写入或严格接口跳过最便宜的一档 | 实验性 |
| `routing.cold_start`（`false`） | 候选都没有学到的结果时，首档从 `[cold_start]` 查 | 实验性（阈值是暂定值） |
| `defaults.ab_self_rate`（0.1），环境变量 `CCX_AB_RATE` | 可派任务里让主导自己做、用来量节省的比例；0 = 关 | 普通功能 |
| `defaults.max_escalations`（1） | 验证失败后最多再升几档 | 普通功能 |
| `defaults.capacity_fallback`（`true`） | 跳过容量不足的模型，最多换两次 | 普通功能 |
| `defaults.focused_retry`（`false`） | `--check` 没过后的重试续同一会话，带上失败输出 | 实验性（r6a 里这类重试很慢；等实测一轮） |
| `defaults.max_parallel`（3） | `ccx batch` 的并行子智能体数 | 普通功能 |
| `dispatch.cheap_first`（`false`） | 先用便宜档试，需要独立的 `--check`（[dispatch](dispatch.zh.md)） | 实验性 |
| `lead.claude`（`opus`）、`lead.codex`（`gpt-6.1-sol`） | 主导用的模型，用于估算节省 | 普通功能 |
| `lead.model_by_task`（`false`） | 新开主对话时按难度选模型（`[lead_by_task]`） | 已测不推荐（Unknown：每组 n=10，一轮） |
| `lead.slim_small`、`lead.slim_context`（`false`） | 主导侧精简（[lead-slim](lead-slim.zh.md)） | 实验性 |

### 审查和验收

| 键（默认） | 作用 | 标签 |
|---|---|---|
| `review.mode`（`read`） | `tests`：独立写任务衍生的测试；旧的 `auto`、`on`、`off` 仍有效 | `read`：普通功能；`tests`：已测不推荐（Fail：确认抓到 0/15；[测试审查](test-review.zh.md)） |
| `review.tests_model`、`review.tests_effort`（空） | 测试审查员的模型和强度；只在 `mode = "tests"` 时有用 | 已测不推荐（同 `tests`） |
| `review.contract_diag`（`false`） | 离线契约诊断；不改任何判定（[诊断](review-contract-diag.zh.md)） | 实验性 |
| `review.skip_when_clean`（`false`）、`review.skip_max_files`（3）、`review.skip_max_lines`（49） | 运行干净时跳过自动审查 | 实验性（效果 Unknown，#427，见[功能详解](features.zh.md)） |
| `escalate.on_self_checked`（`review`） | `--check` 只在子智能体自己写的测试上通过时：`review`、`rung` 或 `off` | 实测：pg1（30/30 通过、18 道隐藏测试失败）是默认 `review` 的依据 |
| `check.baseline`（`off`）、`check.sensitivity`（`off`） | 在干净的派活树上重跑失败的检查（`on_fail`）；也比较通过的检查（`warn`、`escalate`）（[check baseline](check-baseline.zh.md)） | 实验性 |
| `defaults.namecheck`（`warn`；只能改文件） | `--namecheck` 的 `warn`、`fail`、`off` | 实测（见上面的 `namecheck`） |
| `git.auto_stage_resolved`（`false`） | 主机暂存没有冲突标记的已解决路径；从不提交（[git-pending](git-pending.zh.md)） | 实验性 |
| `security.credential_guard`（`false`）、`security.credential_dirs`（`[]`） | 不让子智能体访问凭据目录（[凭据防护](credential-guard.zh.md)） | 实验性（Claude 是工具拒绝，不是系统级隔离；Codex 是 beta） |

只能改文件的 `[review]` 键，除非点名，都是**普通功能**：`min_lines`（50）、`weak`（`true`）、`weak_daily`（20）、
`fix_rounds`（1）、`max_diff_chars`（12000）、`by`、`also`、`coverage_rubric`（`true`）。下面都默认关，属于已测不推荐或实验性：
`fix_rereview = "focus"`（Fail：回放 40 对）、`context = true`（回放：28 次已知 bug 只抓到 11 次，不附时 19 次）、
`must_needs_repro`（结论未定）、`cache_ttl`（没做 A/B 实测）。

### 上限、时间和会话

| 键（默认） | 作用 | 标签 |
|---|---|---|
| `defaults.timeout_sec`（1800） | 每次尝试的超时（[timeouts](timeouts.zh.md)） | 普通功能 |
| `defaults.timeout_reminder`（`false`） | 告诉做的人时限，接近时先写阶段结果 | 实验性 |
| `run.stall_minutes`（0） | 这么久没有任何事件就结束这次尝试，标 `stalled` | 实验性 |
| `run.max_usd`（0） | 默认的 `--max-usd`；0 = 不限 | 普通功能 |
| `sessions.archive`（`after_run`）、`sessions.auto_archive_hours`（2） | 结束的子会话何时归档（`after_run`、`hours`、`off`）；环境变量 `CCX_NO_AUTO_ARCHIVE=1`、`CCX_NO_START_ARCHIVE=1` | 普通功能 |
| `worktree.location`（`sibling`）、`worktree.fetch`（`true`）、`worktree.fetch_timeout`（15）、`worktree.base`（`head`） | worktree 放哪、从哪开始 | 普通功能 |
| `lanes.default`（0）、`lanes.max_tokens`（200000）、`lanes.max_blocks`（5） | `batch` 和 `q run` 的热车道 | 已测不推荐当默认（比十次新运行便宜约 40%，是一次合并运行的 4–5 倍；[报告](research/2026-10-25-warm-lanes.zh.md)） |
| `wake.enabled`（`true`）、`wake.trust_socket`（`true`） | `--bg` 运行结束时给主导一行 | 普通功能 |
| `output.lead`（`line`） | 主导拿到什么：一行 JSON，或完整结果 | 普通功能 |
| `hooks.timeout_s`（2.0） | 会话钩子最多跑几秒 | 普通功能 |

### 提示、上下文和记忆

| 键（默认） | 作用 | 标签 |
|---|---|---|
| `prompt.slim`（`true`） | 对 `--mode write` 且没有 `--check` 的运行，去掉“只要回答”那句 | 实验性（没在真实子智能体上测过） |
| `brief.slim`（`false`） | 精简第一条消息，其余写进 `guidance.md`（见[功能详解](features.zh.md)） | 实验性（Unknown） |
| `delegate.user_words`（`false`）、`delegate.user_words_max_chars`（8000） | 附上主导最近一条真实用户消息（[user words](user-words.zh.md)） | 实验性 |
| `shared_context.run`（`auto`）、`.max_chars`（5000）、`.turn`（`true`） | 附上最近的对话上下文（[共享上下文](shared-context.zh.md)） | 普通功能（只能改文件） |
| `shared_context.dedupe`（`false`） | 去掉“已经定下的事”里的重复句 | 实验性（等 M5） |
| `memory.by_kind`（`false`）、`memory.start_scene`（`false`） | 会话开局和简报带什么 | 实验性（H11 试用已作废；等确认实验） |
| `memory.suggest_expire_days`（14） | 未处理的建议多少天后过期；0 = 不过期 | 普通功能 |
| `merge.*`（只能改文件：`default`、`max_pieces`、`piece_minutes`、`total_minutes`） | `ccx batch --merge` 的设置 | 实验性 |

### 额度、计费、报告

| 键（默认） | 作用 | 标签 |
|---|---|---|
| `quota.routing`（`on`）、`quota.avoid_above`（0.8）、`quota.auto_refresh_min`（60）、`quota.probe_timeout`（15） | 优先还有余量的订阅；环境变量 `CCX_NO_QUOTA_PROBE=1` | 普通功能 |
| `billing.mode`（`api`） | `subscription` 先显示额度单位；路由和美元上限不变 | 普通功能 |
| `report.publish_dir`（空） | 你私有仓库的本地克隆，给 `ccx report --publish` | 普通功能 |
| `ui.lang`（未设） | `ccx ui` 和 ccx 写进对话的那些行用 `zh` 还是 `en` | 普通功能 |
| 环境变量 `CCX_NO_BENCH_REFRESH=1` | 开局不做每周一次的公开基准刷新 | 普通功能 |

### 对话板、项目、自主档位

| 键（默认） | 作用 | 标签 |
|---|---|---|
| `board.github`（空）、`board.max_machine_turns`（6） | 跨电脑的私有仓库后备；机器之间连续几条 | 普通功能 |
| `intake.github`、`intake.label` | `ccx intake` 用的私有仓库和标签 | 普通功能 |
| `projects.roots`（空） | `ccx projects scan` 去哪找 | 普通功能 |
| `autonomy.level`（`L1`） | L0 只给建议，L1 只读的自己派，L2 可合并小分支（文件里：`max_lines` 80、`max_files` 5、`protected`） | 普通功能 |
| `relay.enabled`（`false`） | 额度捕获和显式续接 | 实验性 |
| 环境变量 `CCX_HUB`、`CCX_CONFIG` | 用另一个 hub，或另一个个人配置文件 | 普通功能 |

### 子智能体开关（只能改文件；没有单次运行的选项）

| 键（默认） | 作用 | 标签 |
|---|---|---|
| `[subagent] codex_memories`（`true`） | `false`：Codex 不带 memories | 已测不推荐（**Unknown**：两边都是 29/29 做对） |
| `[subagent] clean`（`false`） | `true`：干净的 HOME，不带用户技能和设置 | 已测不推荐（**Fail**：27/30 对 30/30） |
| `[subagent] codex_lean_tools`（`false`） | `true`：写入运行不带网页搜索、图像生成、goals | 已测不推荐（按登记规则 **Fail**：29/30 对 30/30） |
| `[subagents] fork_turns`（`all`） | `none`：Codex 子会话不带父会话历史 | 实验性（等 M3） |
| `[claude_subagent]` 的 `tools_write`、`tools_read`、`exclude_dynamic`、`mcp`、`skills` | Claude 子智能体启动时加载什么 | 普通功能（启动开销 2026-10-23 实测） |
| `[cold_start]`、`[lead_by_task]`、`[policy.*]` | 上面各键用到的表 | 同对应的键 |
| `[tiers.T0..T4]`、`[permissions.*]`、`[providers.*]`、`[pay_per_token.dsh]`、`[roles]` | 每档的模型和强度、工具权限、其他模型 API（按 token 付费的都有 `daily_usd` 上限）、角色表 | 普通功能；Gemini CLI 适配器是实验性（没真跑过） |

三个已实测开关的来源：[报告](research/2026-10-31-b3-lean-switches.zh.md)。

## 值得知道的一次性选项

| 选项 | 作用 | 标签 |
|---|---|---|
| `ccx doctor --backfill-kinds` | 把旧的已学结果放到各自的任务类别下（只增不改；只跑一次） | 普通功能 |
| `ccx verify --sweep` | 给检查和审查都过的已结束运行记“大概率对”；开局也会安静地跑一次 | 普通功能 |

## 核对没有删任何东西

对比新旧两棵树的命令和选项列表：命令用 `python ccx.py -h --all`，每个命令再用 `python ccx.py <命令> -h`。本页不改任何代码，
所以两份列表和这页出现之前完全相同。
