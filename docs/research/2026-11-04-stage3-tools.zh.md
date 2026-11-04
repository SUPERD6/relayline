# 阶段 3 工具：新题与候选路径

[English](2026-11-04-stage3-tools.md) · 中文

证据等级：**engineering check**，2026-11-04。没有调用真实智能体 CLI、付费 canary 或模型评测。
离线判分检查为 **30/30**：每题原始 stub 均失败，官方示例解均通过。
目标实验仍为 30 题 × 1 轮 × 2 组，共 60 单元；门槛保持：候选组做对数 ≥ self − 1，每成功成本 ≤ self 的 1.2 倍。
本交付不判定门槛；统筹需要在真实开跑前提交代码 pin 和预登记。

## 选题与隔离

来源：[Exercism Python 官方固定版本](https://github.com/exercism/python/tree/6105f6d9d3ef66ce3d5c8f529d2882af3d76b706)。
[fresh_selection.json](../../scripts/eval/fresh_selection.json) 保存完整规则、候选排序与排除原因。
仅选 practice，单个实现文件，有 example/exemplar 和测试；机械检查 stub、测试与参考解的 import，
仅允许标准库及该练习的本地模块。难度同档具体定义为 pg1 那 30 题的官方评分范围 **2–9**，
没有配平难度直方图，也不代表当前模型的通过率相同。
排除固定 aider polyglot 树中的全部 **34** 道 Python 题，同时核对该树与 polyglot_selection.json
（包括它丢弃的四题）完全一致。

74 道符合静态规则的候选，按 UTF-8 `slug + "p3-2026-11-04"`（无分隔符）的 SHA256 升序排列，slug 破同值。
首轮离线判分检查 **28/30**：`ledger` 的 11 项测试与 `markdown` 的 17 项测试在原始 stub 上已经全部通过。
只因这项既定判分条件将它们排除，按顺序补入 `yacht`、`minesweeper`；初次和最终原始结果均保留。
没有依据任何模型结果选题。
用 `fresh_select.py --exercism-repo <bare-clone> --polyglot-repo <bare-clone>` 可重建清单；
这两个离线判分排除项已固定并注明，重建仍得到通过检查的最终清单。

单元仓库只有实现 stub，以及一条新建提交；题面只包含说明文字。隐藏测试、example/exemplar 不进入单元。
复用原有材料提取、预读后移除克隆、缓存与网络拒绝规则，以及独立评分目录；评分仅复制指定实现文件，
智能体自写的测试与 pytest 配置不影响隐藏判分。选题脚本仅机械读取参考解的 import 名称检查依赖，
实际执行参考解的是离线判分器。

## 候选组及提示变化

`ccx2cand` 显式选择才启用，主导模型与 CLI 参数沿用 ccx2，lead_how 沿用 ccx2small：
返回 `state=small_self` 时自己实现、检查并提交，不用 `--force` 重试。
单元 hub 打开并在主导启动前读回断言 `delegate.user_words=true`、`routing.small_self_run=true`、
`routing.strict_escalate=true`，同时断言 `review.mode=read`。没有新增配置键或更改产品默认值。

现有 HOW_CCX2 **没有传 `--files`**，所以候选组命令说明新增
`--files <estimated number of implementation files>`。这确实改变主导提示，不能称为只改开关的比较。
三个开关及新增提示作为整条候选路径比较；原有 ccx2、ccx2small 措辞保持原样。

候选行记录 `candidate.switches`、`small_self`、原始小活决策、`actual_mode`、每次 builder 尝试的
`actual_tiers`（tier/rung/model/effort），以及各 run 的 `user_words` 来源与字数。
来源取自真实 run 记录，不从开关已开推断。small-self 没有 builder 时，档位和来源列表为空；证据缺失写 null/Unknown。
主导模型保留在原字段，`export` 保留新增 candidate 对象。

`--codex-workspace-tmp` 可与 `--arms self,ccx2cand` 共用，只调整 Codex 启动时的临时目录；
self 主导仍使用正常的单元临时目录。假 CLI 子进程测试覆盖 small-self 与实际派活两条路径、
自动读取 Claude 测试会话的 user_words 来源、self 开关不变，以及临时目录位于工作区并在结束后清理。

## 命令与 dry-run

在检出目录运行（缓存内有 `exercism-python.git`）：

```text
python scripts/eval/polyglot_check.py --taskset fresh --ext-cache <cache-directory>
python scripts/eval/r5.py run --taskset fresh --arms self,ccx2cand --rounds 1 --arm-order balanced --dry-run
python scripts/eval/r5.py summary --taskset fresh --results <results.jsonl>
```

指定 dry-run 退出码为 0，也已从仓库外启动验证：**60 单元**，每组 30，self 先做和候选组先做各 15 题。
API 等价估价 **$9.60**：self **$6.00**，候选组 **$3.60**。默认 `--budget 3` 比估价少 **$6.60**，
真实预算由统筹在预登记中指定。候选组没有实测成本，标 `?` 的估价沿用历史 ccx2 均值，
不能当作 fresh 或候选组的实测结果。目前每成功成本、墙钟比较与效果结论均未测。

```text
[estimate] self                    30 units  ~$0.200/unit  ~$6.00 (lead ~$6.00, ccx ~$0.00)  modes self=30
[estimate] ccx2cand                30 units  ~$0.120/unit  ~$3.60 (lead ~$2.30, ccx ~$1.30)  modes ccx2cand?=30
[estimate] total ~$9.60 for 60 units; budget $3.0 with $0.00 of this tag spent leaves $3.00: short by ~$6.60
[estimate] lead prices: sonnet x1.0 of sonnet; token mix assumed (no measured lead token mix in this results file)
[estimate] from measured r5 means with a sonnet lead, split by the measured lead share; another lead model's part repriced at its list prices (PRICES); a ? mode has no measurement and uses ccx2's; tier arms by the mode the shipped tier plans for each task's reference size, so misbanding moves the real cost
```

## 统计与验证

新增 `fresh` 统计保留 `all`、`clean` 两种口径，分别给每组做对数、尝试数、Unknown 数、
所有尝试的花费（含失败及中断）、每成功成本、墙钟中位数与累计墙钟。
缺失成本或零成功时每成功成本为 null；墙钟缺失单独计数。中位数沿用评测器原口径，即偶数样本取中间偏上的值。
all 与 clean 的分母分别报告。
按 tag、轮次、题目及主导模型后缀配对，给出候选减 self 的做对数、每成功成本、墙钟中位与累计差，
并列出已评分、Unknown、未配对数。Unknown 配对明确标识，不悄悄当成做错。
旧统计字段含义保持不变，含全部尝试的口径看新增 fresh 节。

本地测试仅使用本地假上游和 tests/fakes，覆盖确定性筛选、依赖与文件数、exemplar、题面隔离、
启动前全部断言、60 单元 CLI dry-run、假 CLI 子进程路由/临时目录/来源记录，以及失败成本、配对和 Unknown 统计。
相关原有评测测试也通过。全量仓库测试、真实 CLI 行为、CI，以及 Windows/Linux/macOS 跨平台验证由统筹接续。
没有提交、推送、开 PR、发布或改产品默认值。

最后一次相关文件测试：**110 passed in 36.19s**，进程退出码 0：

```text
python -X utf8 -m pytest -q tests/test_eval_fresh.py tests/test_eval_polyglot.py tests/test_eval_small.py tests/test_eval_user_words.py tests/test_eval_sandbox_tmp.py tests/test_eval_r5.py
```

其中 fresh 专用文件贡献 15 项测试。从仓库外调用脚本，用固定版本本地克隆重建选题清单，字节完全一致：
SHA256 `57c65b6eac9b94a33f80621f8458dbd0b4787868c50e08d5dfdb22dad949c718`。
`scripts/collect_changes.py --check` 和 `git diff --check` 也退出 0。

限制：“新题”在这里仅保证排除指定 polyglot 集，不能保证不在模型训练数据或所有历史本地实验中。
官方难度只是近似指标。一轮真实实验也只提供信号，不能直接支撑对外说法。
单文件题可能大量返回 small-self，需按行记录确认实际发生了什么。
候选组组合了开关与提示变化，无法把效果归因给单个开关。

## 最终 30 题

| 序号 | Slug | 官方难度 | 隐藏测试数 |
|---|---|---|---|
| 1 | pythagorean-triplet | 3 | 7 |
| 2 | circular-buffer | 3 | 14 |
| 3 | simple-cipher | 3 | 12 |
| 4 | prime-factors | 2 | 12 |
| 5 | rational-numbers | 5 | 43 |
| 6 | high-scores | 3 | 12 |
| 7 | meetup | 4 | 103 |
| 8 | queen-attack | 2 | 14 |
| 9 | matrix | 3 | 8 |
| 10 | trinary | 4 | 7 |
| 11 | allergies | 3 | 50 |
| 12 | say | 2 | 20 |
| 13 | kindergarten-garden | 3 | 19 |
| 14 | roman-numerals | 2 | 27 |
| 15 | custom-set | 5 | 40 |
| 16 | matching-brackets | 2 | 20 |
| 17 | rail-fence-cipher | 4 | 6 |
| 18 | sublist | 2 | 22 |
| 19 | state-of-tic-tac-toe | 3 | 29 |
| 20 | game-of-life | 3 | 8 |
| 21 | flower-field | 4 | 16 |
| 22 | nucleotide-count | 2 | 7 |
| 23 | luhn | 2 | 23 |
| 24 | pascals-triangle | 4 | 10 |
| 25 | saddle-points | 3 | 10 |
| 26 | linked-list | 4 | 24 |
| 27 | hexadecimal | 3 | 10 |
| 28 | nth-prime | 2 | 6 |
| 29 | yacht | 2 | 29 |
| 30 | minesweeper | 4 | 15 |

## 离线判分原始结果

[首轮 28/30 原始输出](data/2026-11-04-fresh-check-initial.txt) · [最终 30/30 原始输出](data/2026-11-04-fresh-check.txt)。
首轮进程退出码 1，最终退出码 0。两次均从仓库外启动独立进程，使用提供的固定版本本地克隆，未调用真实智能体 CLI。

```text
ok  fresh-pythagorean-triplet      stub: 7 failed in 0.15s                        example: 7 passed in 0.02s
ok  fresh-circular-buffer          stub: 14 failed in 0.17s                       example: 14 passed in 0.01s
ok  fresh-simple-cipher            stub: 12 failed in 0.16s                       example: 12 passed in 0.01s
ok  fresh-prime-factors            stub: 12 failed in 0.15s                       example: 12 passed in 0.05s
ok  fresh-rational-numbers         stub: 36 failed, 7 passed in 0.26s             example: 43 passed in 0.03s
ok  fresh-high-scores              stub: 12 failed in 0.16s                       example: 12 passed in 0.01s
ok  fresh-meetup                   stub: 103 failed in 0.62s                      example: 103 passed in 0.06s
ok  fresh-queen-attack             stub: 13 failed, 1 passed in 0.16s             example: 14 passed in 0.01s
ok  fresh-matrix                   stub: 8 failed in 0.14s                        example: 8 passed in 0.01s
ok  fresh-trinary                  stub: 7 failed in 0.14s                        example: 7 passed in 0.01s
ok  fresh-allergies                stub: 50 failed in 0.27s                       example: 50 passed in 0.03s
ok  fresh-say                      stub: 20 failed in 0.17s                       example: 20 passed in 0.02s
ok  fresh-kindergarten-garden      stub: 19 failed in 0.17s                       example: 19 passed in 0.02s
ok  fresh-roman-numerals           stub: 27 failed in 0.21s                       example: 27 passed in 0.02s
ok  fresh-custom-set               stub: 34 failed, 6 passed in 0.25s             example: 40 passed in 0.03s
ok  fresh-matching-brackets        stub: 20 failed in 0.17s                       example: 20 passed in 0.02s
ok  fresh-rail-fence-cipher        stub: 6 failed in 0.14s                        example: 6 passed in 0.01s
ok  fresh-sublist                  stub: 1 failed, 21 passed in 0.14s             example: 22 passed in 0.04s
ok  fresh-state-of-tic-tac-toe     stub: 29 failed in 0.21s                       example: 29 passed in 0.02s
ok  fresh-game-of-life             stub: 8 failed in 0.15s                        example: 8 passed in 0.01s
ok  fresh-flower-field             stub: 16 failed in 0.17s                       example: 16 passed in 0.01s
ok  fresh-nucleotide-count         stub: 7 failed in 0.14s                        example: 7 passed in 0.01s
ok  fresh-luhn                     stub: 23 failed in 0.18s                       example: 23 passed in 0.02s
ok  fresh-pascals-triangle         stub: 10 failed in 0.16s                       example: 10 passed in 0.07s
ok  fresh-saddle-points            stub: 10 failed in 0.16s                       example: 10 passed in 0.01s
ok  fresh-linked-list              stub: 24 failed in 0.21s                       example: 24 passed in 0.02s
ok  fresh-hexadecimal              stub: 10 failed in 0.15s                       example: 10 passed in 0.01s
ok  fresh-nth-prime                stub: 6 failed in 0.14s                        example: 6 passed in 0.03s
ok  fresh-yacht                    stub: 29 failed in 0.21s                       example: 29 passed in 0.02s
ok  fresh-minesweeper              stub: 15 failed in 0.17s                       example: 15 passed in 0.01s
30/30 exercises grade right
```
