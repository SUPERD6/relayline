# P5 重新选题约定

[English](2026-11-05-p5-reselection.md)

> 2026-11-05 检出修正复验预先约定：仍用同一 117 候选、同排序、同排除和资格规则。
> Windows 固定 `core.autocrlf=true`，通过空目录导出后覆盖确保真实字节转换，尊重 `.gitattributes`；
> Linux/macOS 不新增该设置。策略版本 `native-git-checkout-v2`，每行记录 Git 的实际 EOL 计数。
> 下方 v1 的零题结果是历史：回归测试证明旧实现只设置配置，没有把 stat-clean 的 LF 文件转成 CRLF。
> 本次只重做离线校验，不读取模型结果，不降低规则。

## CRLF 修正复验结果

已确认同一 117 候选及完整排序未变（36 more-itertools、49 boltons、32 pluggy）。
Python 3.11.9 / pytest 9.1.1；Windows 单元和选题统一 `autocrlf=true`，
实际 EOL 计数写入每题及单元行的 `checkout_evidence`。Linux/macOS 不新增该配置。

| 合格候选 | 实现改动 | 父全量 | 父隐藏 | 参考隐藏 | 参考全量 |
|---|---|---|---|---|---|
| boltons `1216b467c10b852d08aa6895c80b6b9ec8f990d8`，September PR sweep | 44 行、4 文件 | 512 passed / exit 0 | 11 failed、189 passed / exit 1 | 200 passed / exit 0 | 519 passed / exit 0 |

四个实现文件：`cacheutils.py`、`jsonutils.py`、`strutils.py`、`urlutils.py`。
符合“至少 60 行或至少 3 个文件”，没有降规则。**合格 1/8，缺 7 题；
无法组成任何四题一局，可运行集合 0/8，整体 Unknown。**

排除计数：父版本全量失败 105，父隐藏未失败 9，参考隐藏失败 2；参考全量失败 0。
另有上表合格 1 题因不足四题无法进入完整会话，不与资格失败混计。
105 个基线失败按原始输出优先分类：旧计时断言 19、旧 collections 导入 13、
缺少 nose 7、不兼容 pytest hook 35、其他基线失败 31（该项不推断统一原因）。
详见[逐题选题记录](../../scripts/eval/p5_long_selection.json)与
[CRLF 汇总](data/p5-crlf-reselection-summary.json)。新原始输出保存在
`.ccx/eval/p5-crlf-reselection-raw/`，旧输出保留。没有模型运行、项目全量测试或提交。

复现用 `p5_reselect.py` 原参数，仅更换独立输出路径；`--previous` 指向保留原排除清单的 manifest。
即使重复运行也不能根据结果调整排序、解释器、依赖或题目门槛。

离线校验开始前固定：只用已有 more-itertools、boltons、pluggy 缓存，仓库优先级依此排列；
扫描全部本地单亲提交，提交时间倒序、完整 SHA 升序。实现 Python 改动至少 60 行或 3 个文件，
不计文档、测试和类型桩。排除 P4 dev/final 和之前已校验的八题，不使用模型结果调参。
按顺序取最先通过的完整四题组，满八题停止。

唯一新增资格要求是环境兼容：按单元的 native Git 检出与明确指定的外部解释器，
未改动父版本全量 `PYTHON -m pytest -q -o addopts=` 必须 exit 0；
父版本隐藏测试失败，参考解隐藏测试和全量测试全部通过。所有失败保留，不修改旧测试或降低规则。
题面来自提交需求，不含隐藏测试或参考补丁。此次选题不调用模型。

缓存复现参数见 `scripts/eval/p5_reselect.py --help`。真实模型评测仍由统筹提交固定版本预登记后决定。

## 离线结果（2026-11-05）

解释器 Python 3.11.9，pytest 9.1.1，Windows native Git 检出。
排除旧题后扫描完所有 117 个合尺寸候选，合格 **0/8，缺 8 题，Unknown**，无法组成两局。
新题清单为空，不拿旧题或不合格题补足。没有调用模型。

| 仓库 | 校验候选 | 父版本全量 exit 0 | 最终合格 |
|---|---:|---:|---:|
| more-itertools | 36 | 5 | 0 |
| boltons | 49 | 2 | 0 |
| pluggy | 32 | 4 | 0 |

106 题父版本全量失败；其余 11 题中，9 题隐藏测试在父版本也全过，
2 题参考解隐藏测试收集错误，因此没有候选进入参考解全量阶段。
失败包括旧计时断言、缺少 nose、旧 pytest hook 参数和旧 collections 导入。
不重试择优，不安装依赖，不改旧测试。逐题完整 SHA、代码行数和错误保存在
[选题记录](../../scripts/eval/p5_long_selection.json)，汇总见
[数据](data/p5-reselection-summary.json)，原始输出留在本地 `.ccx/eval/p5-reselection-raw/`。

三组实际 dry-run：`--split p5 --gates p5 --arms self,ccxlong,ccxlongcheap --dry-run`，
可运行单元为 0，脚本估价三组均 $0；这不是一个完整实验的价格。
用历史 P4final 各 8 单实际总成本投影到未来每组 8 题：
self $1.015828（每题 $0.1269785），ccxlong $2.083943（每题 $0.260492875），
两组小计 $3.099771；ccxlongcheap 及三组总计 **Unknown**。这是历史投影，
题目变化、冷启动和恢复上下文可能改变花费，不能据此声称便宜档更省。
此前 $15.213 的八道旧题规模代理估价已不适用于当前空集合。
