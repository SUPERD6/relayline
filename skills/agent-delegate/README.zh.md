# agent-delegate（中文说明）

[English: SKILL.md](SKILL.md)

**作用**：通过 ccx 执行已获授权的跨智能体委派，并验收结果；或者在一块大而能检查的活之前，用一句话提议委派（由用户决定）。仅要求拆任务或省 token 不触发委派。

**和另外两个技能的分工**：
- **task-routing**：决定谁做、用哪个模型、用哪档强度、要不要拆开。
- **agent-delegate**（本技能）：负责怎么写简报、怎么派、怎么收、怎么验收。
- **task-checkpoint**：长任务中途断了，从断点接着做。

找不到 ccx 命令时才看 `ccx -h --all` / `ccx run -h`。

**最大的花费是主导自己的上下文**：每一轮都要把整段对话重读一遍。大块阅读（很多文件、长日志、查资料）用只读派出去，只拿回结论。输出很长的命令（跑测试、看日志、`git diff`）用 `ccx sum -- <命令>`：只拿到失败项或按文件的摘要，全文留在磁盘上。`ccx lead` 看你现在每一轮花多少，`ccx lead --breakdown` 看每轮重读的都是什么。

**主导是 DeepSeek 时**：ccx 从环境判断谁在当主导，不用 `--from`。Windows 上的 dsh 用的是 Windows PowerShell 5.1：用 `& "<python>" "<ccx.py>" run ...` 调用，超过一行的简报写进文件（`--brief-file`）。dsh 要用 `DSH_PERMISSION_MODE=danger-full-access` 运行（否则 ccx 写不了运行记录）；这会让每条命令都带上用户的权限，开口要之前先说明。

## 步骤

0. **提议委派，用户决定**：没人要求委派、但下一块活大（熟练工程师约 15 分钟以上）且能检查时，先 `ccx propose --lead <你的档> --minutes <n> "一句话任务"`。`authorized: true`（总是和 `worth_offering: true` 一起出现；只在用户自己在设置里选了档位 `ccx config set policy.picked <档>` 时才有，你传的任何参数都不会产生它）表示档位已经决定，不用问：把它的 `say` 那句告诉用户，照它的 `next` 为这个任务跑一次（带你提议时给的估计），并按它说的验收（task-routing「档位」）；项目自主级别 L0/L1 仍可能在改文件前停下，那时按输出去问。`worth_offering: false` 就自己做、不提；`worth_offering: true` 但没有 `authorized` 就用它给的那一句话问用户并等待。同意 → `ccx run --proposal <id> ...`（不要加 `--no-ab`），验收后一定 `ccx verify`；不同意 → `ccx propose --no <id>`，自己做，本对话不再提这类活。**派活总开关**（`ccx config set routing.mode off`；出厂 `auto`）：关掉后 `ccx route` / `ccx propose` 一律回答 `do-it-yourself`（`routing_mode: "off"`），`ccx run` / `batch` / `q run` / `q resume` / `way` 不带 `--force` 就拒绝。这时每块活都自己做、不提议派。跨厂商审查和对话照常：`ccx ask`、`ccx discuss`、`ccx run --mode read --to <另一家>`（审你的草稿或 diff，不改文件）、`ccx mem`、对话板，以及已开始的运行用 `ccx resume` 接着做。只有用户点名要这一次时才用 `--force`。**小活自己做**（用户执行 `ccx config set routing.small_self on` 才开，默认关）：给 `ccx propose` 带上 `--lead` 和 `--files`（预计改的源文件数，不算测试；能估出自己要几次请求就加 `--requests N`）；不经提议就要派的活，先跑 `ccx route --lead <你的档> --files N`。自己做比派活在你这边的固定开销（写简报、等、验收；`ccx config set routing.small_self_by cost` 时两者都在 `small_self.self_cost` 里；默认按文件数，`small_self_files`（1）个以内）便宜时，返回 `small_self.applied: true` 和 `do-it-yourself`：就在这里做、不提议派（暂定，等一轮实测）。`applied: false` 写明为什么照派（自己做更贵、你选的档位、`--needs`、你的上下文大、你的额度紧）。用户自己的 `ccx run` 和已获准的委派不论大小照派。
1. **沿用已确定的选择**：保留获准的目标、模型、强度和读写范围。指定模型时跳过路由；确实需要选模型才用 task-routing，需要拆任务才用 task-split。必须固定目标/模型时使用 `--no-escalate --no-fallback`。并行也须在授权范围内。自己做、自带子智能体还是 ccx，见 `references/three-way.md`；自己定档（`--tier`）见 `references/rubric.md`。
2. **派得省**（第 5 轮评测，2026-10-26：大任务上用 ccx 的主导请求数中位 8 次，用自带子智能体 6 次，多出来的就是下面这些习惯）：
   - **简报 = 用户原话照抄**（尤其接口、名字、精确字符串、数字）+ 你已经知道的文件路径 + 验收命令。不要转述接口（“第一个匹配的提示”被改写成“最早的位置”，结果做错）；不要为了写简报先读代码库或 README/STATUS/文档，子智能体自己读（还会读 `.ccx/context.md`），花的是便宜模型。复用已有 `.ccx/context.md`；只有上下文维护属于本次授权时才更新它。格式见 `references/brief-template.md`。
   - **大活或多文件：一次调用** `ccx run ... --bg --wait 540`，shell 工具超时设 600000 毫秒（Claude Code 的 Bash 上限是 10 分钟；Codex 或 DeepSeek 当主导时，把 `--wait` 设成比自己的工具调用超时少一分钟左右）。它立刻（在 stderr）打印 run_id，同一次调用里给出最终结果，和普通 `ccx run` 一样。到时还在跑：`ccx show <run_id> --wait`，显示还在跑就再调一次。还在跑的运行不要 `ccx resume`。不要把 ccx 输出接到 `tail`/`head`。
   - **自己的子智能体和 ccx 同时干活**：你自带子智能体做的块和 ccx 做的块绝不同时写同一批文件；ccx 的写任务和你自己的写任务并行时，用 `--worktree` 或走 `ccx q run`（不然它的 undo 快照、diff 和验收会把它们的改动算进去）。它们的模型用 ccx 给的，填进 Claude Code Agent 工具的 `model`（sonnet / opus / haiku / fable，Claude Code 2.1.309）：先用 `builtin` 选择的 `how`；没有这种选择时才用 `ccx route` 的 `builtin_model`；都没有就不填（跟你同一个模型）。
   - **几块已获授权的活**：先用 task-split `check` 排计划；改同一个文件的块合成一块或你自己做，绝不并行（干净的 git 检出里，`q run` 让并行的写任务各用一个 worktree；否则都在当前检出里跑）。每块 `ccx q add "<标题>" --brief "..." --check "..."`（有先后用 `--dep <id>`），再 `ccx q run --bg`。自己的块从短到长做，不要碰排队块的文件（它的 undo 快照和验收会把你的改动算进去）。
   - **流水线：交出去，不干等。** 互不依赖的块一起交出去（同上），然后 `ccx show <live ids> --any --wait` 谁先结束先交回谁（`live` 的 id 在 `ccx q ls` 里，一块一行）。在 worktree 里做完的块显示 `unmerged`：别的块还在跑时就用 `ccx q accept <id>`（或 `--all-ready`；`--dry-run` 只看计划；没有验收或审查证据时先给结论 `ccx q done <id> --ok 1`，和 `ccx q ls` 提示的顺序一样）把它落地。它按依赖顺序合并，每合并一块就跑一次联合验收（`--check "<各块验收命令的并集>"`，不给就用该块自己的），验收失败就撤回这次合并；拒绝的块（no_changes、失败、审查没过或还在跑、没有验证证据）和冲突都会说明原因。没有用户同意不合进 main。`q run` 输出里 `waiting` / `unmerged` 下的就是这些块；在当前检出里做的块用 `ccx q done <id> --ok 1`（一次给多个 id 时，没有通过的验收的块各加一条 `--note "<id>: 你查了什么"`）。`dep_blocked` 的块在等一个失败的块（见 `references/three-way.md`）。`last_run` 是 `stopped: backpressure`（额度/登录）时，在额度恢复前不再开新活。
   - **`--review` 保持默认（auto）**；只有高风险或用户能直接看到的改动（以及需要审查通过的 L2 自动合并）才 `--review on` / `--risk visible`。
   - **不要让子智能体提交**（Codex 沙盒禁止写 `.git`）；你验收后自己提交。
   - **用户说到某个项目但没给路径**：先 `ccx where "<用户原话>"`；一个 `pick` 就 `ccx run --project <名字>`，几个候选就问。项目规则讲到审批时 ccx 停下并列出（`approval_rules`）：按规则判断或问用户，之后才加 `--rules-ok` 重跑。细节见 project-manager。
3. **运行**：`ccx run`（带打分参数时自动选模型；默认允许改文件）、`--model/--effort`（自己指定，加 `--minutes` 才能用来校准路由）、`--mode read`（只分析）、`--check CMD`（验收命令，子智能体跑完 ccx 再跑一遍）、`--risk visible` / `--review on|off`（由另一家的便宜模型审改动；auto 时风险高、代码改动 50 行以上、子智能体没把握、说的和实际改动对不上，或证据弱（没有 `--check`、check 不跑测试、跑的测试没提到改动的文件或函数、或验收命令放过过做错的结果；只用另一家最便宜的一档，每天最多 20 次，`weak_daily`）才审）、`--worktree`（在单独的分支上改）、`--bg --wait 540`（一次调用拿结果；还在跑再 `ccx show <run_id> --wait`）、`ccx stop <run_id>`（停掉正在跑的委派，之后可 `ccx resume`）、`--task/--step`（会话 ID 写进 task-checkpoint）、`ccx batch`（并行）、`ccx resume`（同一个子会话里追问或接着做）、`ccx way --risk low|visible|critical`（按风险选做法；critical 约贵一倍，先问用户）。
   - 额度用完/限流：自动换另一个智能体再试一次（`--no-fallback` 关掉）。
   - 超时、崩溃或 `ccx stop`：会话 ID 已经存下，`ccx resume <run_id>` 接着做。
4. **验收**：已经打印出带 `run_id` 的结果就别再派同一份简报，要补充用 `ccx resume <run_id>`。总结只是说法。
   - 结果里有 `needs_lead`、`edited_tests` 或 `namecheck` 时**先看它们**（`namecheck`：改动的函数里没有任何作用域定义的名字，多半是测试没覆盖到的 NameError）。
   - `check` 通过且跑的是相关测试，再看 `files_changed` / `diffstat` 就够了，**不要自己重跑**（H11 实测 2026-10-24）。只有 check 失败、没有、带 `weak`（这个命令在这里放过过做错的结果），或状态是 partial/blocked 时，才自己跑测试或读完整 diff。`check.covers` 列出它实际跑了哪些测试文件：没测到任务要求的行为，就不算"相关测试"；有 `check.basis_changed` 表示它是在子智能体改过的测试上通过的，先看那几处改动。
   - **子智能体自写测试通过 ≠ 做对。** check 跑到的测试文件全是子智能体这次新写或改过的，`kind` 就是 `ok_self_checked`（退出码仍是 0；`check.basis` 和 `needs_lead` 写明"未经独立验证"；默认 ccx 会交给审查、要求对照任务原文核对，见 `[escalate] on_self_checked`）。主导要自己对照任务原文验收（任务里写的每个名字、签名、返回值、错误和情形），或给它一个运行前就有的测试做 check，才算做完。外部基准里 18 道隐藏测试失败的题，全都通过了子智能体自己的 `test_own.py`。
   - `check_broken` = 验收命令什么都没测：`ccx resume <run_id> "要测什么" --check "..."`。任务点名了一个入口（命令、CLI）却没有测试把它当真实进程跑：resume 一次，要求补一个。
   - `no_changes` = 写任务说 done/partial，却什么都没改（没有改文件、没有提交；check 是在没改过的代码上跑的；`ccx q` 把这一块记为失败，依赖它的块会等着）：只有任务本来就已满足才接受，否则 resume。`--worktree` 的结果里有 `base`：它从 HEAD 起步，不含你未提交的改动，所以它的 check 没测到这些改动。
   - `env` = 是机器的问题，不是模型的：子智能体的命令行起不了进程（比如 Codex 在 Windows 上的沙箱助手）。ccx 没往上升级、没重试、也没续跑；把 `hint` 转告用户（不是暂时的，别重试），等用户修好再 `ccx resume RID --env-fixed`（不带这个选项会被拒绝）。状态是 `blocked` 或 `failed` 时 `ok` 一律为 false。
   - `verification: not-run` 就照实说“没验证”。
   - `review` 是独立审查：`pass` 或 `issues`（带文件:行）。ccx 自己会跑一轮修改（`show --wait` 会等它）；之后的 `needs_lead` 由你决定，`review_failed` 见下一条。`kind` 只按最终结果判断：打印出结果的 `ccx run ... --bg --wait`，或 `ccx show <run_id>`（带不带 `--wait` 都会跟到修改轮；显示 `fix_round: starting` 或 `finishing` 说明还不是最终结果：用 `ccx show <run_id> --wait`，不要续跑）。最终仍是 `review_issues`，说明修改轮没跑成（没有可续的会话，或没能启动）：自己改，或重新派。有修改轮时，`cost_chain` 是整条链的花费（tokens 和美元）。
   - `review_failed`（修改轮之后审查仍不过）：对着 diff 逐条核对 `[must]` 项，属实的自己修，不属实的放下。不要为此 `ccx resume`，除非用户要求再改一轮（要多花一次运行）。
   - 然后 `ccx verify <run_id> --ok 1|0 [--reason unfinished|wrong|overreach|other]`：校准路由（给了 `--minutes` 还校准拆分），并把 checkpoint 的这一步标成完成。没人判断的运行，12 小时后验收或自查通过、审查也通过会记成“大概率对”；`ccx undo --apply` 撤回的等你判，加 `--wrong` 同时记成“错”。只要真的看过，就记一下。
5. **换主导**：用户说“交接给 X”时，自己还能写就 `ccx handoff --by <你> --to X "…"`；原主导写不了（额度用完、崩了、窗口关了）就 `ccx handoff --from-transcript <原主导> --to X`。接手方先核对其中的说法。自己的对话太长、下一块又是新活时：先问用户，再 `ccx fresh`（用本对话的记录写交接，新对话开局就能看到）。给下一块活加 `--minutes`：用户开了 `lead.model_by_task` 时，`ccx fresh` / `ccx handoff` 按难度给新主对话选模型。正在跑的对话永远不换模型。
6. **记忆**：只有记忆维护已获授权时，才用 `ccx mem add` 保存必要的长期事实（`--project` 写进本项目 `.ccx/` 的日志；`ccx project status` 看这一层）；委派任务本身不授权写入记忆。
7. **代价高的决定**（难撤回、涉及安全或钱、用户说很重要）：像第 0 步一样先一句话提议 `ccx discuss`（`--dry-run` 给出参与者、最多几次调用、估价和各自用的模型；不带 `--confirmed` 只给估价，不会真跑），用户同意才 `ccx discuss --confirmed "问题"`；结果只是建议，用户可在 `ccx ui` 看讨论过程。
