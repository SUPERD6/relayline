# 按任务写测试的审查（实验性）

[English](test-review.md) · 中文

用 `ccx config set review.mode tests` 开启。默认 `read` 保持原有只读审查的提示和触发规则。

`review.tests_model` 也接受 `vendor:model[:effort]`，如 `claude:sonnet:medium` 或
`codex:gpt-6.1-sol:medium`；空值继续沿用候选。指定厂商仍须满足跨厂商审查，
不能绕过独立性检查。单独的 `review.tests_effort` 优先于 model 中的 effort。

测试型审查会附上改动前的 Python 接口：普通运行从 undo snapshot 读取，回放明确读取
已提交的原始 stub。保留签名、注解、继承、装饰器、字面量默认值和 docstring，
不含函数实现或测试；优先放改动文件，上限 24,000 字符。缺 snapshot、解析失败和
超限未展示部分标 Unknown，不把当前实现当作接口标准，也不补造返回值契约。
审查员先写 `behaviors.json`，列原文引用、接口假设、返回类型/形状/单位、计划测试和
未覆盖/Unknown，再读实现写测试。接口和清单保存在 `review-tests/interface.md`、
`behaviors.json`；新增 `interface_path`、`behaviors_path` 指向证据。清单只辅助审查，
不新增正确率或通过条件。Markdown 链接的显示文字可省略 URL，其他原文校验仍保留。
旧配置 `auto/on/off` 继续有效，含义不变；`--review auto/on/off` 仍控制何时审查。
没有删除命令或选项，没有改已有退出码。

复用现有的跨厂商审查员选择。同厂商候选明确标 `independent=false` 和 Unknown，不运行。
`review.tests_model`、`review.tests_effort` 仅覆盖测试审查候选的模型和 effort，默认均为空，
沿用原候选。模型必须属于已选审查员厂商；不会开启测试模式，也不影响 read 审查。
测试审查先传已保存的 `user-words.md` 原话，再传已记录的 `user_task`；没有
`user_task` 才回退原始 brief，修复轮仍回到原任务。两份分别标明来源，内容相同
也保留两份，不合并、不去重。原话标明采集来源和保留字符数，保留原有截断提示，
不增加任务截断上限。写测试和失败确认两次调用均使用这些来源；续跑复用保存的
原话快照，不重新读外部原话文件。引句必须在任一来源内匹配，不能跨来源拼接，
来源标签和采集提示不作为任务要求。
共享上下文和实现者自写测试的结果不作为任务标准。
`ccx run --user-task-file original.txt` 可单独提供 UTF-8 原话，与实现者 brief 分开。
不提供时，run 入口在附加角色模板和项目说明前保存输入任务。测试模式将它写入
`run.json.user_task`，修复轮和续跑继承；`ccx resume --user-task-file original.txt` 可显式更新。
程序调用传 `Request.user_task`；回放从收据经隔离任务文件传入该字段，不再只依赖实现者 brief。

审查员拿到临时源码副本，其中没有 Git 历史、`.ccx`、项目指令或实现者测试。
它在 `checks/` 写独立 Python unittest，在工作目录根部的 `manifest.json` 写文件名和任务原文引句。
兼容此前有歧义的 `checks/manifest.json`，但仅在根部 manifest 不存在时回退。
引句必须在规范化空白和标点（含 Markdown 反引号）后仍为原文子串；不接受改写、修改词语或数字、
纯标点引用。同一文件的每条引用都要校验，允许对应多个有效引句，文件只执行一次。
ccx 在独立 Python 进程里实际执行。断言失败或测试方法内抛异常后，审查员先检查测试是否只测任务明确要求的行为、
测试的预期和准备工作是否正确。只有确认的实现错误才进入原有修复和拦截流程。
没写出测试、收集或导入错误、跳过、超时、审查员不可用、失败未确认均为 Unknown。
自写测试通过只说明这些检查通过，不能证明题目做对。首版支持 Python unittest，其他环境记 Unknown。

测试源码和真实输出保留在运行目录 `review-tests/`，不进入实现改动；账本不存测试源码。
`run.json` 新增 `review_test_mode="tests"`，`review` 中新增 `review_mode`、
`tests_written`（收集到的测试用例数）、`tests_run`（扣除跳过后的执行数）、
`tests_failed`（断言失败和运行时异常数）、`unknown_reasons`、`independent` 和测试文件/输出证据路径。
**已有顶层 `review_mode` 仍表示 auto/on/off 触发策略**，供续跑使用。
Unknown 是新的审查结果，收据有 `needs_lead` 提示，既不是 pass，也不新增拦截退出码。
执行超时或机器可读的结果丢失时，计数写 `null`，不把未知数量写成 0。
生成的测试与原有验收命令一样，以当前用户的 Python 权限执行；源码副本是证据边界，不是操作系统沙箱。
测试子进程仅继承运行环境白名单：PATH、Windows 系统和命令查找变量、临时目录、语言与时区变量，
再加 `PYTHONDONTWRITEBYTECODE=1`；不继承父进程的 API key、token 或其他任意变量。
审查员不再自行跑测试，由控制器负责执行。证据保留 manifest、拒绝诊断和确认请求错误。
新增 `reviewer_calls` 记录每次请求的模型、effort、权限模式、run ID 和结果；
`native_usd` 累加 CLI 报告的原生费用，任一次费用未知则为 null。
既有 `usd` 仍是配置价格算出的 API 等价估算，CLI 实际换模型时可能与原生费用不同。

## pg3b 回放

先检查材料，不调用模型 CLI：

```console
python scripts/eval/p2_review_replay.py --dry-run --budget 3 --exercise-source /path/to/exercism-clone
```

默认读取 `.ccx/eval/r5/pg3b-results.jsonl` 和 `pg3b-results-artifacts/`。
逐行核实最后一张收据类型、实际实现者、隐藏测试结果、完整改动、隐藏 pytest 输出、
固定版本原始 stub 和题面；逐项报告缺件，不从主导厂商猜实现者。不会下载 benchmark。
worktree 中没有被忽略的结果文件时，自动读取主检出的对应数据。
对公开报告指定的 pg3b 30 行，报告说明其中 29 张为自检收据，唯一一张审查失败。
行内 ccx 记录可定位这张例外：pg-bowling 的最后一个实现者运行仍有未修复的 issues。
据此推定 29 张的成员资格，并以 `receipt_basis` 标明推定来源，不声称恢复了缺失的收据原始字节。
无法唯一识别最后一次失败审查时，缺类型的行仍为 Unknown；不是 29 张时阻止付费回放，不悄悄换分母。

2026-11-04 离线核实：30 行结果和 30 个 artifact 目录存在；选中的 29 张均有完整改动和隐藏输出，
隐藏测试 14 过、15 不过，实现者记录均为 Codex。28 份补丁含缓存块，回放先过滤这些块和实现者测试，
再应用 solution 补丁。指定的本地缓存位置没有找到克隆；dry-run 为 29 单元、0 就绪、最高预留估价 $2.90。
仍缺固定版本题面和原始 stub，需要本地克隆。
随后使用统筹提供的 `polyglot-benchmark.git` 缓存，核实完整 pin
`7e0611e77b54e2dea774cdc0aa00cf9f7ed6144f`，同一审计已达到 29/29 就绪，全程未调用模型。
沙箱账户读取统筹账户拥有的克隆时，可能需要仅对该路径临时设置 Git `safe.directory`；不改全局配置。
可传 `--exercise-source CLONE`，或与 r5 相同的 `--ext-cache DIR`（其下放 `polyglot`、`polyglot.git`，
也接受 `polyglot-benchmark` 或 `polyglot-benchmark.git`）。
缺材料时打印一条供统筹执行的 `git clone --bare` 命令，脚本不执行。以上审计步骤没有调用模型；
随后首轮真跑的结果见下文诊断。

真跑必须显式加 `--run --pin-commit SHA --budget USD`；`--wait-quiet MINUTES` 复用 r5 空闲等待。
每个单元开跑前保留 `--unit-cap`（默认 $0.10），丢失响应也不退还保留额。
最多两次 Claude 请求，各自用原生 `--max-budget-usd` 限制在单元上限的一半；
没有原生美元上限的 CLI 记 Unknown。脚本限制启动保留额并传递厂商原生上限，不能承诺比 CLI 自身
更严格的计费上限。金额为 API 等价美元，不是订阅账单；修复后配置的真实预算和隔离行为尚未实测。

可用 `--reviewer-model sonnet --reviewer-effort medium` 固定模型和 effort，默认均为空。
保留数字写法 `--unit-cap 0.10`，也支持重复指定模型上限，如
`--unit-cap 0.10 --unit-cap sonnet=0.40`。模型上限必须搭配 `--reviewer-model`，防止按错模型预留预算。
包括未运行和 Unknown 单元在内，每行均记录请求覆盖值和实际单元上限；运行后 `by` 和
`reviewer_calls` 记录选中的审查员。回放确认使用 `dontAsk` 加 Read/Grep/Glob，替代 `plan`：
首轮 4 次 plan 确认的原生事件均显示实际用了 Sonnet，虽然请求的是 Haiku。
新参数已由假 CLI 检查；真实模型是否仍会变化，需要另行授权回放验证。
详见[第一轮诊断](research/2026-11-04-p2-r1-diagnostics.zh.md)。

回放从原始 solution stub 加**仅 solution 文件的补丁**重建，不把实现者测试、隐藏测试或隐藏输出
放进审查员的任务或目录。结果 JSONL 保留完整原始行，以及所有失败和 Unknown。
输出已存在就拒绝覆盖，防止丢证据或重置预算；证据目录保留。
抓错率＝错误中被拦的数量／全部错误；误拦率＝正确中被拦的数量／全部正确，打印分子、分母。
Unknown 单列，并打印“按最坏算”：错误中的 Unknown 全算没抓到，正确中的 Unknown 全算误拦。
分母为零仍是 Unknown。

r5 增加可选 `--arms ccx2rt`：主导和提示与 `ccx2` 相同，单元 hub 写入并读回断言
`review.mode="tests"` 后才启动。默认组不变。
历史首轮为 4 Pass、25 Unknown、0 issues，见上文诊断。修复版目前只有假 CLI 工程检查，
pg3b 抓错效果仍是 Unknown。

## 第二轮诊断与新接线

历史第二轮 `b7f9463`：确认抓错 0/15；8 张错收据 pass，7 张错收据 Unknown；
正确收据 9 pass、5 Unknown。最好假设也只有 7/15，仍 Fail。
[逐单诊断](research/2026-11-05-p2-r2-diagnostics.zh.md) 区分接口/覆盖缺口、错误测试和
Markdown 链接引句误拒。本次修改只有工程检查；题目、判分、≥50%/≤20% 门槛、默认
`read` 及现有 verdict/退出规则不变。两轮失败后，本次工作不授权付费开第三轮。

`--review-model` 是 `--reviewer-model` 的兼容别名，可传带厂商的 model。
例如 `--dry-run --review-model claude:sonnet --unit-cap claude:sonnet=0.40`：
29 单启动预留为 $11.60，这是选定的预留上限，实际预期费用 Unknown。
`--review-model codex:gpt-6.1-sol` 可解析并选择 Codex，但本回放不会付费调用：
这批实现者均为 Codex，同厂商不算独立；脚本也没有 Codex 原生美元预算上限。
产品审查可用 Codex 审 Claude 的实现，本次只通过假 CLI 验证接线。
