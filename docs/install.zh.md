# 安装和命令

[English](install.md) · 中文 · 回到 [README](../README.zh.md)

## 安装

需要 Python 3.11+（只用标准库），并且 `codex` 和 `claude` 两个 CLI 都已登录；`dsh`（DeepSeek Harness）可选；`gemini` 可选，且只能当子智能体（适配器按它的文档写的，没真跑过）。

**不克隆仓库**（技能和配置都打在包里）：

```bash
pipx install git+https://github.com/SUPERD6/relayline
ccx setup        # 向导：hub、接线、体检；每次改动前先问
ccx run --to codex --mode read "Summarise README.md in three lines for a new user: what this project does, how to install it, and the first command to try"
```

最后一行是第一次派活（和 README、`ccx setup` 给的是同一条）。不用向导、一步步来：`ccx init --hub <你的个人hub路径>`、
`ccx sync`、`ccx sync --apply`、`ccx doctor`。hub 是你自己的一个文件夹，放共享记忆、技能和每次运行的记录。
本机已经有 hub 时，`ccx init --hub` 换一个文件夹会停下并显示正在用的 hub，确实要换就加 `--force`（旧 hub 里的文件原样留着）。
`--snapshot` / `--external-sync` 要改掉内容不同的 `layout.toml` 时也一样。

没有 pipx？给它单独建一个虚拟环境一样能装：

```bash
python3 -m venv ~/.relayline && ~/.relayline/bin/python -m pip install git+https://github.com/SUPERD6/relayline
```

```powershell
python -m venv "$env:USERPROFILE\.relayline"; & "$env:USERPROFILE\.relayline\Scripts\python.exe" -m pip install git+https://github.com/SUPERD6/relayline
```

然后从这个环境的 `bin`（Windows 上是 `Scripts`）文件夹运行 `ccx`，或者只把 `ccx` 一个文件链接到 PATH 里的某个文件夹
（把整个文件夹加进 PATH，会让它的 `python`、`pip` 排到前面）。

**从插件市场装**（仓库本身就是一个插件市场，名字 `relayline`）：

```bash
claude plugin install relayline --marketplace SUPERD6/relayline     # Claude Code 2.1.275+，一步装好
# 旧版 Claude Code：claude plugin marketplace add SUPERD6/relayline && claude plugin install relayline@relayline
codex plugin marketplace add SUPERD6/relayline && codex plugin add relayline@relayline   # Codex 0.164，实验性
```

Claude Code 这条真跑过（用临时配置）。从 GitHub 地址装 Codex 插件是**实验性**的：按 Codex 的插件文档写；测试只检查插件清单文件，安装命令本身没跑过。

- **Claude Code** 得到五个技能（名字是 `relayline:agent-delegate`、`relayline:task-routing`、`relayline:task-split`、
  `relayline:task-checkpoint`、`relayline:project-manager`）和 ccx 的两个 hook：开局的共享记忆增量、每轮的留言板/共享
  文档提示。hook 运行插件里自带的 ccx（`bin/ccx`，经 `sh` 运行；Windows 上就是 Claude Code 跑 hook 用的 Git Bash），所以要有 Python 3.11+，但不用另装。
  没 `ccx init` 之前它们什么都不输出。
- **Codex** 只得到五个技能。它的 hook 仍由 `ccx sync` 写（Codex 的插件 hook 要用户手动信任，这里不提供）。
- **DeepSeek Harness（`dsh`）** 目前没有插件市场或技能安装方式（看的是它的 README，2026-10-25）；`dsh` 在 PATH 上时，主导说明照旧由
  `ccx sync` 写。只在已安装的桌面应用里找到的 `dsh` 默认不接入；sync 只提一次，说明是可选的（把它加到 PATH 后再跑 `ccx sync`）。
- **ccx 本体仍要装**（`pipx install git+https://github.com/SUPERD6/relayline`，再 `ccx init` 或 `ccx setup`），才能在
  终端或 Codex 里派活。插件已启用、但 ccx 没单独装时，`ccx doctor` 会提示。
- **不会接两遍：** 插件启用的工具里，`ccx sync` 把 Claude 的 hook 和这五个技能交给插件，并删掉它以前写的那份
  （`settings.json` 里 ccx 的 hook、各工具 `skills/` 里的链接）；Codex 的 hook 块不动。hook 仍有两份时 `ccx doctor` 会警告。

**从克隆的仓库装**（要改代码，或者想让 `git pull` 直接升级接进 hub 的技能）：

```powershell
git clone https://github.com/SUPERD6/relayline
cd relayline
.\install.ps1 -Hub <你的个人hub路径>     # Windows；macOS/Linux（实验性，只在 CI 里跑过）：./install.sh <hub路径>
```

安装脚本会：有 pipx 就 `pipx install --editable .`（之后直接用 `ccx`），没有就提示把 `bin\` 加进 PATH；然后 `ccx init`（只新建，不改已有文件；本机已经在用另一个 hub 时会停下并显示它，确实要换就加 `-Force`，macOS/Linux 是 `./install.sh <hub路径> --force`）和 `ccx doctor`（体检：CLI、登录、接线，不确定的写 Unknown；routing prior、tier policy、hub layout 这类 ccx 内部的行只在有问题时显示，`--verbose` 全部显示）。接着运行向导 `ccx setup`（每一步都说明、改东西前先问），或者一步步来：

```powershell
ccx sync            # 预演：列出将要做的改动，不改任何文件
ccx sync --apply    # 真改；被改的文件自动备份为 *.ccx-backup-YYYYMMDD
ccx selftest        # 每个已安装的智能体用最便宜的模型跑一个小任务：登录、解析、启动开销一次看清
```

之后在 Codex 里打开 `/hooks`，信任 "ccx: shared memory delta" 这个 hook（只需一次）。

已经有自己的共享配置（比如一个 AGENTS.md 两边都读、自己的同步脚本）？用 `ccx init --hub <路径> --snapshot AGENTS.md --external-sync "<你的同步命令>"` 接进去，ccx 不再改两边的说明文件，技能和 MCP 交给你的脚本。本机已经有另一个 hub，或 `layout.toml` 里是别的值时，它会停下说明，要替换就加 `--force`。

## 常用命令

```text
ccx run "任务" --from claude --files 3 --coupling cross --clarity goal   # 按打分自动选（推荐）
ccx run "任务" --model gpt-6.1-sol --effort high                       # 自己指定模型和强度
ccx run "任务" --tier T2                                               # 按固定分级
ccx run "任务" --check "pytest -q" --review on                        # ccx 自己重跑验收；另一家的模型独立审查改动
     [--mode read] [--check CMD] [--review auto|on|off] [--worktree] [--task <id> --step <n>] [--minutes 60] [--no-fallback] [--force] [--no-ab]
ccx verify <run_id> --ok 1|0 [--note "说明"]  # 主导验收结论：校准选模型/拆分，并关掉 checkpoint 这一步
ccx resume <run_id> "追问"          # 在同一个子会话里继续；中断后也用它接着做
ccx stop <run_id>                   # 停掉正在跑的委派（连同它开的所有进程）；resume 能接上
ccx task status | resume <任务>     # 长任务：一条命令接着做中断的那一步（额度用完时自动换另一边）
ccx handoff --by claude --to codex "做完了什么/定了什么/接下来做什么" [--next "任务5" ...]   # 换主导接力
ccx lead                                     # 主会话每一轮要重读多少 token、花多少钱
ccx lead --breakdown | --cache | --suggest   # 每轮重读的东西逐项拆开 / 缓存断在哪 / 主导自己该用哪档
ccx sum -- python -m pytest -q               # 跑命令，只给主导看要紧的（测试只看失败），完整输出留在 .ccx/sum/
ccx fresh [--launch]                         # 长对话交给同一工具的新对话：从这段对话的文件生成交接
ccx propose --lead claude:opus:high --minutes 30 "…"  # 提议派活前：估算、一句话怎么说、记一笔（--no ID、--stats）
ccx trial start | stop | report              # 一周正式对比：一半可派的活主导自己做，一半派出去，同样口径量
ccx trial tag --arm native --session ID      # 把用了 Claude Code 自带子智能体 / workflow 的对话记为第三组
ccx agents                                   # 每家命令行：厂商、能做什么、测过的版本、官方还是社区
ccx way "任务" --risk low|visible|critical   # 按风险选合作方式：一家做 / 规划+实现+验收 / 两版比较（--yes）
ccx way --stats [--include-evals]           # 每类活每家（分档位）的一次做对率和返工率，默认不算评测
ccx discuss "问题" [--dry-run]              # 2-3 家不同厂商讨论选错代价高的决定：出方案、挑错、裁判
ccx verify <run_id> --ok 0 --reason wrong     # 你的判断（没人判断的，12 小时后按证据自动记“大概率对/错”）
ccx verify --sample 5                        # 抽查本周 5 个自动判定：看改动，回答对 / 错
ccx handoff --from-transcript codex --to claude   # 原主导写不了（额度用完）：从它的会话文件生成交接
                                                  # （先用代码提取；格式认不出时交给自动选出的子智能体整理，--no-model 不用模型）
ccx undo <run_id> [--apply] [--wrong]   # 撤回某次可写运行改动的文件（新建的挪到一边）；--wrong 同时记成做错
ccx ask "问题"                       # 让另一个模型快速给个第二意见（只读、低强度）
ccx archive [--apply] | --restore <run>   # 归档用完的子会话（结果确定时自动归档；
                                          # sessions.archive = after_run | hours | off）
ccx batch plan.json                 # 互不依赖的任务并行；多个写任务自动分到不同 worktree（有未提交改动时共用项目目录：先提交）
ccx q add "标题" --brief "..." [--dep q1] [--check CMD]   # 项目的待办队列；--plan plan.json 一次加整份计划
                                    # （{"tasks": ...} 或 task-split 的 {"pieces": ...}，认 depends_on、files）
ccx q run [--gate] | resume | tree | done q3 --ok 1   # 就绪的块并行跑；多个写任务各开 worktree（仅限没有未提交改动时），依赖它们的块
                                    # 等你合并并 q done --ok 1；--gate（默认关）让所有下游都等你的结论；
                                    # 依赖失败的块标成 dep_blocked，不再一直卡着
ccx q ls [--long]                   # 一块一行：id、状态、智能体、秒数、$（worktree 里做完还没落地的块显示 `unmerged`，
                                    # 附 `next: ccx q done qN --ok 1, then ccx q accept qN`，先给结论
                                    # 再合并；已给结论的只附 `next: ccx q accept qN`）；--long 是完整 JSON
ccx q accept q1 q2 | --all-ready [--check CMD] [--dry-run]   # 把 worktree 里的块落地：按依赖顺序合并，每合并一块
                                    # 跑一次联合验收，失败就撤回这次合并；没做完、no_changes、没验证的块拒绝，
                                    # 冲突的块停下；从不 push，没有 --into-protected（用户同意）不合进 main；
                                    # 你否决过的 run（verify --ok 0）拒绝；撤回失败或验收改动了已跟踪文件时整批停下
ccx route --files 3 --coupling cross ... [--lead claude:opus:high --ctx-files 日志.txt]  # 只看推荐；加 --lead 还会比较自己做 vs 派出去
ccx plan size --minutes 240 --rung codex:gpt-6.1-sol:medium   # 大任务拆几块（task-split）
ccx show <run_id> [--full]          # 默认只显示压缩结果
ccx show <run_id> --wait [秒数]     # 等它（连同审查后的修改轮）跑完，默认 540 秒；跑完给出和 ccx run 一样的结果，
                                    # 没跑完返回 status=running，再调一次即可
ccx stats [--summary]               # 按 agent×级别统计；--summary 先给花费，再给带标签的节省估算、缓存占比
ccx report [--days 30] [--publish]  # 看板网页（离线单文件）；--publish 提交到你的私有用量仓库
ccx ui [--project 文件夹] [--no-open] [--export 文件]   # 本机实时页面（127.0.0.1，不调用模型；只写“建议记下的事”的同意/拒绝）
ccx demo [--no-open] [--keep] [--export 文件]       # 同一个页面，用临时目录里编好的数据：不用账号，离线可用
ccx config set ui.lang zh          # ccx ui 和 ccx 写进会话的提示用中文
ccx config set defaults.tradeoff 0.3   # 省钱↔快 的旋钮：save / balanced / fast，或 0..1
ccx config set routing.mode off       # 不派活：活都自己做；ccx ask / discuss / run --mode read（跨厂商审查）、mem、
                                      # board 照常；run / batch / q run / q resume / way 不带 --force 就拒绝（auto = 出厂）
ccx ab done <id> --ok 1             # 结束一次 A/B 抽样（主导自己做的那 10%）
ccx run "任务" --to gemini --tier T2                       # 派给 Gemini CLI
ccx run "任务" --to deepseek      # 通过 Claude Code 用 DeepSeek flash（密钥放环境变量 DEEPSEEK_API_KEY），思考强度按难度选
ccx run "任务" --provider deepseek-codex   # 同一个模型经 Codex（用 -c 设 model provider，密钥从环境变量读）
ccx run "任务" --to dsh --tier T2          # DeepSeek 自己的智能体 DeepSeek Harness（无头模式）
ccx run "任务" --provider glm              # 较新的 API 经 Claude Code：kimi、glm、qwen、openrouter（要有密钥）
ccx run "任务" ... --bg             # 后台跑，马上返回 run_id；用 ccx show <run_id> --wait 等结果
ccx run "任务" ... --bg --wait 540  # 后台跑并在同一次调用里等：做完就打印最终结果；到时没做完就原样打印 --bg 的输出
                                  # （run_id 马上打到 stderr）。ccx resume ... --bg [--wait N] 同理
ccx send --list | --thread <id> "消息"   # 发消息给正在运行的 Codex 桌面/交互会话（只有 Codex：Claude Code 的终端
                                        # 和桌面会话都没有接收外部消息的入口；Claude 子智能体用 ccx resume <run_id> 追问）
ccx say --to codex|claude|deepseek|all "消息"   # 对话板：本项目开着的会话下一轮就能看到
ccx board [--thread T] / ccx reply <id> "消息"  # 看给我的新留言 / 回某一条（docs/board.zh.md）
ccx peek codex|claude|deepseek        # 共享工作上下文：看另一家在本项目开着的会话最近在做什么
ccx run --context auto|on|off ...     # 派活时附上主导最近的工作（auto：只给可写任务）
ccx say --to codex --now "消息"   # 同时推进开着的 Codex 桌面对话（Claude Code 桌面端只能下一轮看到）
ccx config set board.github owner/repo   # 可选：对话板同步到你自己的私人仓库（ccx board --sync）
ccx skills find pdf 表格             # 先在共享技能库里找，别重复写
ccx skills install [--replace] [--apply]   # 把仓库里的技能链接进 hub（默认先预演），以后 git pull 就是升级
ccx improve add <技能> "遇到的具体问题" --fix "怎么改"   # 只记真实遇到的问题
ccx mem add "一句话" --by claude     # 写入共享记忆
ccx mem delta --as codex            # 拿对方新增的条目（hook 会自动运行）
ccx mem compact                     # 把日志合并进快照
ccx mem search gradle 签名           # 最相关的排前面（BM25）；--all-words：只要每个词都有的
ccx mem add "..." --kind 坑          # 偏好|约束|事实|坑|事件；`ccx mem kinds --list` 看归类
ccx mem compact --by project        # 每个项目一小段场景块，写到 memory/scenes.md
ccx ctx init | add "…" | show       # 项目背景文件
ccx config set projects.roots "目录;目录" ; ccx projects scan   # 本机项目目录（只存在 hub，不进仓库）
ccx projects | projects show <名字>        # 列出项目 / 看一个：路径、简介、先读的规则、最近在做什么
ccx where "改一下那个桌宠"               # 一句话说的是哪个项目：只有一个明显的才直接给，否则列候选和理由
ccx run --project "桌宠" "简报"          # 派进那个项目（先读它的规则；有审批规则先原样列出，看过再加 --rules-ok）
ccx autonomy --project desk-pet         # 总管不用问能做多少：L0 / L1（默认）/ L2
ccx sync [--apply] [--only skills,memory,hooks,mcp]
ccx doctor
```
