# project-manager（中文说明）

[English: SKILL.md](SKILL.md)

**作用**：给“统筹其他会话的主会话”当项目总管。用户说一句话，总管找到项目、决定怎么分工、派给 Claude / Codex / DeepSeek、验收、收尾，最后用一两句话汇报。用户不想被打扰：常规、能撤回的事直接做，档位不允许的和第 6 节那几类才问。

**和 agent-delegate 的分工**：agent-delegate 管“一块活怎么写简报、怎么派、怎么验收”；本技能管“派什么、派到哪个项目、用什么形状派”。目标已经定死的单次委派直接用 agent-delegate。

别为了做计划去读项目的 README、STATUS 或文档：`--project` 会把项目的规则文件放在简报开头。

## 1. 听懂这句话

用一行复述：要什么结果、怎样算做完（一个测试、一条命令、一个文件）、用户有没有提速度或花钱。完全没法检查“做完”时，先问这一个问题。

## 2. 定位项目

`ccx where "<用户原话>"`（只用代码，不花钱）。
- 只有一个 `pick` → 用这个名字；
- 几个候选或一个都没有 → 问用户是哪个（第 6 节），不要猜；
- 只有在需要路径或规则文件来做判断时，才 `ccx projects show <名字>`。

## 3. 选形状（先看默认）

依据是第 2 轮七个核心实测（2026-10-25，说明写清楚的中等任务；更难或更含糊的活没测过）：

| 形状 | 什么时候 | 为什么 |
|---|---|---|
| **一个便宜模型做 + 另一家便宜模型审**（默认） | 几乎所有时候 | 做对率和更贵的分工方式一样，花费约为 `ccx way` 的 7%（审查每个任务约 $0.006） |
| **并行** | 只有用户要快、而且活能拆成互不依赖的块 | 更快但不省：每多一路约多 9.3 万 token 输入（固定前缀每次请求重发、一次运行约 5 次请求，不是一次性启动开销），10 路的 token 是 1 路的约 4.7 倍。选它时要跟用户说“更快但不省” |
| **先出分工草案，再审草案** | 大活（很多文件、几个小时、边界不清） | 先把拆法定下来，再花钱做 |

默认命令：
```
ccx run --project <名字> --minutes <n> --tradeoff save --review on --check "CMD" "简报..."
```
`--review on` 让另一家的便宜模型看每一次改动（见 docs/DECISIONS.md；和 auto 不同，它没有每天的次数上限，L2 自动合并也需要它）。`--tradeoff save` 让路由选便宜的；那一轮里 15–30 分钟的任务路由仍选中档模型，而最便宜的模型在这类任务上做对 97%，所以说明写清楚的活可以直接用 `--model <模型> --effort low` 指定便宜档。

并行：每块一条 `ccx run --project <名字> --bg --worktree ...`（每块都带项目规则文件和审批停顿），再用 `ccx show <run_id> --wait` 等结果。`ccx batch plan.json` 和 `ccx q run` 也能并行，但每个任务只给普通的 `"cwd"`（路径来自 `ccx projects show`），不会附上规则文件，所以只在项目没有审批规则时用。不到 5 分钟的小块合并成少数几路：小块的花费主要是启动开销，不是活本身。

大活：自己用 task-split 技能出草案（必须先读代码时，用只读的 `ccx run --project <名字> --mode read`），再让另一家的便宜模型只读审草案：`ccx run --project <名字> --mode read --to <另一家> --tier T1 --brief-file draft.md`。改掉它标成 must 的问题，再按默认方式一块一块派。除非做错代价很高（agent-delegate 第 7 节），不要用 `ccx way` 或 `ccx discuss`：在这类任务上它们贵 20–39 倍，做对率一样。

共享工作上下文：`ccx run --context auto`（默认）会给每次写任务附上这段对话最近在做什么。只读任务（比如审草案）如果依赖这段对话，加 `--context on`。

## 4. 验收

按 agent-delegate 第 4 节（看多少、`needs_lead`、审查后的修改轮），每个看过的运行都 `ccx verify <run_id> --ok 1|0`。有好几块时，每块都验过才说做完。

## 5. 收尾和汇报

- 已结束的运行用 `ccx archive --older-than 1 --apply` 归档（不确定会动哪些就先不加 `--apply` 看一遍）；客户端有自己的会话列表时，自己开的会话在它的活合并后归档。
- 汇报一两句：现在什么成立了、在哪里（分支、PR、文件）、花了多少、哪些**没验证**。不讲过程。

其他工具：`ccx ui`（本机实时页面：谁在做什么、什么在等用户）、`ccx say` / `ccx board` / `ccx peek`（给本项目其他打开的会话留言、看它们在做什么）、`ccx intake pull`（取回用户在自己私有仓库里以 issue 提的任务；`ccx intake ask` / `done` 会以用户身份在这些 issue 上留评论，属于往本机以外发消息，按第 6 节先问用户）、`ccx stats` / `ccx report`（花费和节省）。要给某块活新开主对话：`ccx fresh` / `ccx handoff` 加 `--minutes`（用户开了 `lead.model_by_task` 时按难度选模型）；自带子智能体的模型见 agent-delegate 第 2 节。

## 6. 自动档位，以及始终要问用户的事

`ccx autonomy --project <名字>` 给出当前适用的档位（不花钱；默认 L1）。只有用户能调高（`ccx autonomy set L2 --project <名字> --auto-merge on`，或在用户要求的命令里带 `--autonomy`），总管自己永远不调高。`ccx run --project`（以及带 `--autonomy` 的运行）按档位行事；停下时返回 `delegated: false` 和 `plan`（派给谁、模型、读/写、`expected_usd`、验收命令、预算）。

| 档位 | 不用问直接做 | 停下来问 |
|---|---|---|
| L0 | 找项目、选形状、写简报 | 每次派活：用一句话把 `plan` 告诉用户；同意后同一条命令加 `--approved` |
| L1（默认） | 只读任务（`--mode read`，如审分工草案）、审查、已同意任务的改一轮、归档 | 可能改文件的任务：一句话说 `plan`；同意后加 `--approved` |
| L2 | 读写都直接派；带 `--worktree --check "CMD" --review on` 时由 ccx 自己合并分支（见下） | ccx 拒绝合并的：报告分支和 `autonomy.merge.why_not`，用户说合才合 |

L2 自动合并（ccx 全部检查；`ccx autonomy merge <run_id>` 只检查不合并）：用户允许了这个项目合并；运行正常结束；`--check` 通过且没被标成弱；独立审查 pass；改动最多 `max_lines` 行、`max_files` 个文件（默认 80 / 5）；项目没有审批规则；风险不是 visible / critical；项目当前分支不是受保护分支（`main`、`master`、`trunk`、`release/*` 和远端默认分支）。只在本机合进项目当前所在的分支；推送和任何进主分支的 PR 仍由用户决定。撤回：看返回里的 `undo` 那一行。续跑过的运行合的是最初那次运行的分支（`ccx/<最初 run_id>`，续跑沿用它的 worktree）；worktree 被切到别的分支时拒绝合并。

`ccx batch` 和 `ccx q run` 不读档位：L0、L1 下要用户同意了那份计划才启动。

无论哪一档，下面这些都要问用户（`--approved` 不能代替）：

- 往本机以外发东西：邮件、聊天、issue、给别人的 PR 评论、发布；
- 合并进主分支（项目允许时，推功能分支、开 PR 不用问）；
- 花钱超上限：某家的 `daily_usd`、`--budget`，或 `ccx way --risk critical` / `ccx discuss`；
- 科研审批：`ccx run --project` 因 `approval_rules` 停下时，先读规则；明确允许这件事才加 `--rules-ok`，否则问。派出去不等于放宽项目的冻结或审批；
- 判断不出是哪个项目（第 2 节）。

档位允许的其他事——选形状、便宜的审查、改一轮、归档——都直接做，不用问。
