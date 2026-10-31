# ccx 做什么、怎么做

[English](features.md) · 中文 · 回到 [README](../README.zh.md)

## 七件事

| | 做什么 | 现在的状态 |
|---|---|---|
| **1. 互为主子** | Claude Code 当主、Codex 干活，或者反过来；DeepSeek 也能当主导（`dsh`，或跑 DeepSeek 模型的 Claude Code），也能接活（经 Claude Code、经 Codex 或 `dsh`）；Gemini CLI 可以接活（实验性，未实测）。每家一个适配器，`ccx agents` 列出每家能做什么、测过哪个版本、官方还是社区。 | 两个方向真机跑通；DeepSeek 当主导（dsh、跑 DeepSeek 的 Claude Code）和当子智能体（三条路）都真跑过；Gemini 实验性、未实测 |
| **2. 两个模型直接对话** | `ccx ask` 让另一家快速给个第二意见；`ccx resume` 在同一个子会话里追问；`ccx send` 把消息发进正在运行的 Codex 会话；`ccx say` / `ccx board` 让同一项目里开着的 Claude Code、Codex、DeepSeek 会话互相留言（每轮只看到给自己的新内容；Claude Code 桌面端只能下一轮看到，DeepSeek 会话要自己跑 `ccx board`）；`ccx discuss` 让 2–3 家不同厂商的模型把选错代价高的决定讨论清楚（出方案、挑错、裁判，最多 3 轮），在 `ccx ui` 里显示成对话。从外面派活：手机用 Remote Control，或用 `ccx intake` 把你在私人仓库开的带标签 issue 当任务取走、做完在 issue 里回报（[说明](intake.zh.md)）。 | 前三个真机可用；`ccx discuss` 真跑过两次，先两家、后三家（Codex、Claude、DeepSeek；[记录](research/2026-10-25-discuss-three-vendors.zh.md)）；`ccx intake` 实验性：只用假 `gh` 测过，没对真实 GitHub 跑过 |
| **3. 共享记忆** | 个人层（你的 hub：记忆、技能、MCP、账本）和项目层（`.ccx/`：背景、日志、交接、断点）。开局 hook 只推对方新写的几行；`ccx handoff` 换主导接力，`ccx fresh` 把长对话交给同一工具的新对话。**共享工作上下文**（[说明](shared-context.zh.md)）：用代码从各家会话记录摘出“最近在做什么”，派活时附上（`ccx run --context`）、按需看（`ccx peek`）、每轮推一行——各家仍各有自己的上下文。 | 真机可用；共享工作上下文：在专门需要它的任务上一次做对 36/36，不带 7/36（[A/B](research/2026-10-25-shared-context-ab.zh.md)） |
| **4. 分工合作** | 5 个问题打出难度 → 选智能体、模型、强度并给出成功率；算下来自己做更划算或该先拆，就直接说不派。`ccx batch` / `ccx q` 并行（`--lanes N`，默认关：同一家的小活续在几个热会话里，不再每块开新会话），长任务断了 `ccx task resume` 接着做。 | 选模型真机可用，但先验没校准；队列只有模拟测试 |
| **5. 省和高效** | 子智能体精简启动；`ccx lead` 看主导每轮重读多少（`--breakdown` 拆开看、`--cache` 找缓存断在哪、`--suggest` 给主导自己的档位建议）；`ccx sum` 只把大段输出里要紧的给主导。 | 工具都在；省多少取决于主导怎么用（见实测） |
| **6. 不掉质量** | ccx 自己重跑验收命令（`--check`）；另一家的模型独立审查改动（`--review`）；每次记对错（`ccx verify --ok 0 --reason wrong`），没人判的 12 小时后按证据记“大概对/错”；`ccx trial` 做一周正式对比。 | 真机可用；自动结论还没被抽查过 |
| **7. 不丢可控** | 改配置先预演、真改前备份；`ccx undo` 撤回某次运行的改动；`--mode read` / `--worktree` 不动工作区；子智能体不能再派子智能体；`ccx ui` 在本机显示谁在干什么、什么等你拍板，按钮（停下、记对错、再改一轮、改预算）先给你看要运行的 `ccx` 命令，再点一次才运行。 | 真机可用；`ccx ui` 在 Edge 和桌面端内置浏览器里开过 |

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/architecture-dark.svg">
  <img alt="架构图：Claude Code、Codex、DeepSeek 都连到 ccx，谁都能当主导或接活；主导把简报交给另一家在后台跑、交回 JSON；ccx 选模型、重跑验收、请另一家审查，每次派活写一张收据（花费、验收、审查、结论、撤回）进账本，并从各工具自己的会话文件读出共享工作上下文；下面是个人层（hub：共享记忆、技能、MCP、账本）、项目层（.ccx：context.md、日志、对话板、交接、断点、撤回快照、队列）和本机页面 ccx ui（收据、token 去向）。Gemini CLI 只有子智能体适配器，没真跑过" src="assets/architecture-light.svg" width="100%">
</picture>

## 命令：日常的在前，一个不删

`ccx -h` 只列日常命令：`setup`、`doctor`、`run`、`ask`、`resume`、`stop`、`undo`、`verify`、`show`、`q`、`ui`、
`mem`、`handoff`、`lead`（以及 `demo`）。`ccx advanced`（等于 `ccx -h --all`）列出所有分组：记忆和上下文、账本和报告、智能体之间
（开着的会话互相调用的 `peek`、`board`、`say`、`reply`）、进阶（hub、多个项目、安装接线：`init`、`projects`、`where`、
`intake`、`sync`、`config`、`uninstall`、`repair`、`agents`）、维护，开发者用的放最后。`ccx dev` 列出开发者命令
（`trial`、`ab`、`bench`、`improve`、`namecheck`）；`ccx dev trial ...` 就是 `ccx trial ...`。`ccx run -h`、
`ccx resume -h`、`ccx verify -h`、`ccx lead -h` 里不常用的选项放在 "advanced" 标题下。只改帮助排版：每个命令和选项
名字不变、照旧解析（`tests/data/cli_surface.json` 冻结了完整清单，有测试核对）。

## 实时看：`ccx ui`

**首页是一个项目一张图**（P2-10）：中间是这个项目里的智能体和它们之间的往来（谁给谁派活、对话板话题、`ccx discuss` 讨论；被机器连续条数上限停下的话题、在问你的消息列为待办）；左边是共享记忆，连到说明里带了便签的那几次派活（从派活说明本身读出，不靠猜），以及这些派活最后对没对（你的判断；运行本身失败算错，被你停下、超预算、环境问题不算）；右边每次派活一张收据（谁派给谁、档位和实际用的模型档、花费、check 覆盖了哪些测试、这次派活有没有改自己的测试、审查结论、你的判断）；顶上是本周的 API 等价花费（记录里的 token × 价格表，不是账单；测试和评测不算），按实际用到的档位分开，其他做法只列已发布的实测表，不估算；底下是能力表（谁擅长什么），记过对错的活不够时显示“数据不足”。下面这些页面都还在原处：带全部待办和按钮的总览在 `#/all`。

<img alt="ccx ui 首页：一个项目一张图——顶上花费，共享记忆、智能体和对话、收据（演示数据）" src="assets/ui/map-zh.png" width="100%">

`ccx ui` 在本机打开一个页面：有什么等你处理（红框 = 要你拍板，橙框 = 要你 review）、谁在干什么（每个智能体一列，新加的自动多一列）、额度按现在的速度够不够。点任何一块，右边显示原因、依据和按钮（因本机环境停下的运行，`kind: env`，显示修复提示和 `ccx doctor`，不给“再试一次”；hub 还是空的时，首页说第一步该运行什么）。它也是总管看板：`ccx projects` 目录里的所有项目（项目里有工作队列，就算这里最近没派过活也会显示；没动静的项目只占一行；项目页摘出它规则文件里讲审批的原句），以及这个月子智能体花了多少；省了多少要等 `ccx trial` 实测之后才显示（到目前为止实测总花费基本持平，见 docs/measured.zh.md；和 `ccx report` 同一规则）。会改东西的按钮——停下运行、记对错、再改一轮、续跑、允许它改、改队列预算——先显示要运行的完整 `ccx` 命令，再点一次才运行；会启动子智能体的按钮会写明要花钱，并在后台跑。页面只告诉服务端“按了哪个按钮”，从不发命令；服务端只运行固定几条 ccx 命令，按参数列表运行（不经过 shell），只接受这个页面自己的请求（同源、口令、一次性确认）。“建议记下的事”每条有同意/拒绝按钮。显示页面只读 ccx 和各工具本来就写下的文件，不调用任何模型；只监听 127.0.0.1，页面关掉约一分钟后自己退出（若当时在后台标签页，最多 5 分钟）。要你 review 的卡片并排显示“它说”（它的总结、它说自己怎么验证的）和“ccx 实际跑了”（验收命令、退出码、最后约 800 字的输出），下面是实际改动的文件和 diff：用 ccx 自己给这次运行记的快照算（运行前的树 `undo.json` 到运行结束时的树 `end.json` 或 `undo.json` 里的 `after`），从不对着现在的目录算；它报的文件和实际改动对不上时，用红框列出差别。diff 太长会截断并写明“已截断”；没有这些快照的旧运行照旧只显示它自己报的文件，并加一句说明。总览（`#/all`）列出所有正在跑的运行（谁在跑、跑了多久、知道的话还有 token 数），每条带“停下它”按钮，同样要再点一次确认。页面在后台标签页时，“还开着”的信号会说明这一点，服务端这时等 5 分钟而不是 1 分钟才退出。待办小标签改成按钮（键盘可达），新待办会通过读屏播报。“智能体对话”页面显示各智能体在对话板上互相写的话（`ccx say`），最新的话题在前；被机器连续条数上限停下的话题、在问你的消息（`@person`）会出现在待办里，你可以直接在页面上回复：先给你看，再点一次才以你的身份写入（via ui），最多 4000 字，永远不会运行（[对话板](board.zh.md#在-ccx-ui-里看和回复)）。`ccx ui --export 快照.html` 生成静态副本；`ccx config set ui.lang zh|en` 选语言。**实测与 token 去向**页面（只读）分三部分。(1) 已发布的数字（留出集和第 5 轮两张表：做法、做对、每次成功的花费、用时中位数；留出集里只看外部仓库的那几行是干净的，单独成一张小表；每张表的限制写成一行，并链接 [实测](measured.zh.md)；有测试按做法和轮次逐格对照 measured.md 和 measured.zh.md 里的表），下面是你自己账本里的数字（运行次数、成功率、每次成功的 API 等价花费，按模式和智能体分），标明“你自己的运行，不是对照比较”。(2) token 去向：Claude 和 Codex 记在同一本账上，按任务分组（没有任务按标签，再没有按单次运行）；每次运行显示新读入、读缓存、写缓存、输出 token 和 API 等价花费（日志里读得到时，还有它自己这段对话发了几次请求、首请求的输入、平均每次请求的输入——也就是每次重发的那段前缀，省 token 的改动要降的就是这几个数；这里不算子会话的请求，而 token 那几列含子会话），下面是它自己开的子会话（Codex 的来自运行记录里的 `codex_children`，Claude 的来自子运行的 `<session>/subagents/*.jsonl`）及其占这次运行的比例；一次运行的总数本来就含这些子会话。续跑或接着做的运行只显示它的子会话新增的部分（减掉前一次运行自己的记录，不受筛选和分组影响）；几次运行共用一个 Claude 会话时，每次运行只算自己那段时间里的子智能体轮次。比例不封顶：超过 100% 时页面会说明两边的数对不上。可按今天 / 7 天 / 全部和项目筛选（用了 `ccx ui --project` 时，“全部项目”也真的是全部）。按智能体的合计大的在前。只列最新的 40 个任务，并写明省掉了多少，以及它们的 token 和金额。(3) 主导对话：派过活的主导会话，最新的在前；打开一个时才读它的会话文件，用的就是 `ccx lead --breakdown` 和 `ccx lead --cache` 的函数：每一轮重读的内容按部分有多大、建议，以及提示缓存断开的那几轮和可能的原因。只读账本里点名的会话；返回内容有大小上限；所有标签和会话文字都转义；hub 为空时说明该先运行什么。每个项目页（以及任务的“经过”下面）有**谁在主导**：现在由谁主导、每段时间由谁主导（来自 `.ccx/handoffs/` 里的交接记录），以及“交给 Codex 继续”/“交给 Claude 继续”（装了 `dsh` 的机器上还有 DeepSeek）。按钮同样要再点一次才运行 `ccx handoff --to <另一个> --by <当前> --cwd <项目>`；当前主导在这个目录的对话文件存在时加上 `--from-transcript <当前> --no-model`（只用代码整理，不调模型）。结果是交接文件和一行话：在那个工具里打开这个项目时贴给它（Claude Code 和 Codex 启动时也会自动显示一次这份交接；DeepSeek 不会，这一行让它去读那份文件）。找不到那个对话文件时，交接是空白模板，页面在确认前和完成后都会说明：先自己填好。任务时间线标出任务开始时由谁主导、之后每次换主导。页面上没有别的新写入。**`ccx demo`**（或 `ccx ui --demo`）不用账号就能看到这些：它在系统临时目录新建一个文件夹，写入编好的数据（两个项目、各种状态的运行且带真实快照 diff、一次派活的完整收据——花了多少、ccx 跑的检查、另一家的审查——审查本身也记成运行、一个工作队列、一个被停下的对话话题和一个 `@person` 提问、一个月的花费，以及给 token 去向页用的每次请求数和一个 Codex 子会话），只让它自己的进程指向那里，用同一个页面显示并标明“演示数据”。离线可用，不启动任何智能体：会启动智能体的按钮只显示命令；记对错或交接只写进演示文件夹，页面关掉后文件夹会删掉（`--keep` 或 `--dir` 保留；`--export 文件` 生成静态副本，之后同样删掉文件夹）。`--dir` 只接受新的或空的文件夹，或以前的演示文件夹。评测和测试（eval-* 标签、`--no-ab`、ccx 自己的探针、在临时目录或项目 `.ccx` 目录里跑的）默认不显示，点“显示评测与测试”才出来；`ccx verify RUN --dismiss --note 原因` 把测试残留从“等你处理”里清掉，不算对也不算错，路由也不从它学习。

截图：`ccx demo` 的数据，用 `python scripts/make_shots.py` 拍。

<img alt="ccx ui 总览：所有项目里等你处理的事（提问、要你拍板、看结果）、正在跑的（演示数据）" src="assets/ui/overview-zh.png" width="100%">

<img alt="ccx ui 任务页：一件任务画成组织图，每个干活的一列；右边是一次派活的收据：谁做的、花费、ccx 重跑的验收、审查、结论、实际改动的文件（演示数据）" src="assets/ui/task-zh.png" width="100%">

<img alt="ccx ui 总管看板：各项目、现在的主导、这个月的花费（实测省多少之前只显示花费）、谁在哪类活上更靠谱（演示数据）" src="assets/ui/k6-month-zh.png" width="100%">

<details><summary>英文界面（判断卡、token 去向）、深色</summary>

<img alt="ccx ui decision card in English: a run whose review still finds problems, what the agent says beside what ccx ran (demo data)" src="assets/ui/judge-en.png" width="100%">

<img alt="ccx ui, where tokens go, in English (demo data)" src="assets/ui/tokens-en.png" width="100%">

<img alt="ccx ui task page in English, dark theme (demo data)" src="assets/ui/task-en-dark.png" width="100%">

</details>

上面的截图用的是 `ccx demo` 编好的数据（`python scripts/make_shots.py` 拍）；`python scripts/ui_demo.py` 仍可生成临时 hub、用模拟命令行跑真实的 ccx 运行，不含任何人的真实工作。

## 它怎么工作（一个例子）

你在 Claude Code 里说："把 `loader.py` 支持自定义分隔符，并补测试。"

1. Claude（主）按 5 项给任务打分（改 2 个文件、单模块、目标清楚、风险低、有现成写法），写一段不到 200 字的简报，只写目标、要看的文件、怎样算完成。
2. 执行 `ccx run --from claude --files 2 --coupling one --clarity goal "…"`。ccx 调用 task-routing 技能，算出每个“智能体:模型:强度”的成功率和每次成功的花费，挑出 `codex:gpt-6.1-sol:medium`。如果算下来自己做更划算、或者应该先拆开，就直接告诉主导，不派。
3. ccx 在后台调用 `codex exec -m gpt-6.1-sol -c model_reasoning_effort="medium" …`。会话 ID 一出现就存盘。Codex 自己读文件、改代码、跑测试，这部分 token 花的是 Codex 账号的额度。
