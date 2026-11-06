# 契约诊断（实验性）

[English](review-contract-diag.md) · 中文

默认 `review.contract_diag = false`。用 `python ccx.py config set review.contract_diag true`
显式打开后，启用审查的写入任务会先附加诊断。保留全部现有命令、选项、JSON 字段含义、
退出码、审查默认值和判定规则。当前证据等级是 engineering check，不能据此说审查变准或任务做对。

## 进程和证据

控制器只传保存的用户原话（如果存在）、指派题面和改前 Python 接口。全新 `python -I -S`
进程在空临时目录通过 stdin 收到这三段文字。固定代码没有读文件操作、模型调用或工具；
不传 Python 配置、凭据环境变量、实现、diff、隐藏测试、旧审查和共享上下文。
这是可信代码的数据隔离，不是能够安全运行任意模型 CLI 或不可信 Python 的操作系统沙箱。
改前接口由现有提取器读取保存的 Git base，不读取当前实现。

本版离线生成器只提取段落，把原文保留为候选预期，所有项均为 `unknown: true`。
文字提取不能建立语义预期。另有下述显式开启的 Claude 语义适配器；脚本也可读取独立撰写并冻结的契约。
不能通过把实现路径交给这个进程来生成契约。

行为字段为 `id`、`source`、`quote`、`expected`、`unknown`。控制器分别校验每个来源的引用，
不跨来源拼接。无效引用、重复 ID、接口假设、缺失输入保持 Unknown。改前接口不自动升级成需求。
输入超过 64,000 字符时报告 Unknown，不静默截断。历史缺失的原话无法恢复；不同措辞之间的语义冲突
也不能由提取器裁定。

`review-contract.json` 用规范 JSON 的 SHA256 `contract_hash` 冻结来源、行为、缺口和生成器，
只创建、不覆盖；复用时检查 hash 和来源完全一致。只有实际运行诊断，精简收据才新增
`contract_diagnostic`、`evidence_level`、`evidence_scope`、`covered_ids` 和 `coverage_note`：

| JSON 值 | 含义 |
|---|---|
| `independent_verified` | 未修改的外部检查通过，或独立测试审查实际执行且判定明确；范围是列出的测试文件 |
| `self_checked` | 控制器检查通过，但执行的测试全由实现者自己写或改 |
| `unverified` | 没有上述执行证据 |

普通只读审查通过不能升级“只自检”。这些等级描述已运行检查，不代表全部行为或整单正确。
行为与实际执行测试尚未建立映射，所以 `covered_ids` 保持空。测试基础有改动、部分缺失、筛选（如 `-k`）或不明时，
不能建立独立验证结论。原有判定规则不变。

## 历史离线诊断

从任意目录运行，显式指定本地材料和全新输出目录：

```text
python /path/to/relayline/scripts/eval/review_contract_diag.py --evidence /path/to/p2-r2-evidence --dry-run
python /path/to/relayline/scripts/eval/review_contract_diag.py --evidence /path/to/p2-r2-evidence --generate --out /path/to/new-output
```

15 个已知错误 ID 来自 [R2 诊断](research/2026-11-05-p2-r2-diagnostics.zh.md)，属于历史开发材料，
不能当全新评测样本。脚本读取各自存档 job 和重建树 HEAD 中提交的原始 stub，不读当前实现。
缺材料也保留行和分母。不 clone、不下载、不调模型、不运行隐藏测试。
`--dry-run`（也是默认行为）不写文件；`--generate` 在控制器读隐藏判定表之前冻结所有契约。
缺题面、接口或判定证据时保持 Unknown。

模型调用的默认预留为 15 × $0.50 = $7.50，绝对上限 $8。
`--budget`、`--unit-reservation` 必须是有限正数，总预留超预算就拒绝。
这是预留算术，不是模型报价；真实模型预期费用 Unknown，离线模式的调用和花费均为零。

## 显式语义生成与缺陷映射

```text
python /path/to/relayline/scripts/eval/review_contract_diag.py --evidence /path/to/p2-r2-evidence --generator claude --dry-run --budget 8
python /path/to/relayline/scripts/eval/review_contract_diag.py --evidence /path/to/p2-r2-evidence --generator claude --run --budget 8 --out /path/to/new-semantic-output
python /path/to/relayline/scripts/eval/review_contract_diag.py --evidence /path/to/p2-r2-evidence --generate --map-defects --hidden-root /path/to/pg3b-results-artifacts --out /path/to/new-mapping
```

只有同时给出 `--run --generator claude --budget USD` 才调用模型。正常任务诊断仍默认离线；
没有新增配置键或修改判定。语义适配器在空 cwd 中使用 `--bare`、空 `--tools`，关闭 MCP、
技能、配置来源和会话保存。参数已于 2026-11-05 核对 **Claude Code 2.1.316 --help**。
stdin 只传三段来源文字，不传实现、隐藏失败或人工判定表。`--bare` 要求环境中显式 API 认证；
适配器不寻找、复制客户端凭据或 home。这限制模型工具，不是可信 CLI 二进制的操作系统沙箱。
其他 CLI 版本尚未验证。
Windows 的 `.cmd`/`.bat` 入口会解析为同目录原生可执行文件，或标准 npm
`node_modules/@anthropic-ai/claude-code/cli.js` 加 Node。未知布局不启动，返回 Unknown。
这样避开 `cmd.exe` 对 JSON 和空参数的有损转发，原生/Node argv 保留空 `--tools` 与
`--setting-sources` 参数。假 CLI 检查覆盖解析与保守停止；没有运行已安装的 npm shim。

每次调用的 `--max-budget-usd` 等于单元预留。串行执行，花费缺失时保留全部预留并停止后续调用；
已知超支也停止。失败调用仍入账，未知花费为 null，另报 `known_spent_usd` 和 `charged_usd`。
提供方可能在单个已发请求上超额，因此预留不是账单保证。本路径仅做假 CLI 工程检查，未验证模型质量。

`--map-defects` 在冻结契约后，只读取显式隐藏证据根目录下的 `hidden-pytest.txt`。
它把 pytest 用例 ID 和断言行关联，生成 `oracle-template.json` 与 `human-review.md`。
每条都有 SHA256，初始均为 `confirmed: false`、空 requirements 和 Unknown。
人工补齐来源引用与预期片段后才能作为 `--oracle` 使用；提取器不自动确认，也不让生成模型自判覆盖。
证据缺失或无法解析时仍为 Unknown。

要做确定性覆盖核对，在 `--generate` 之外加 `--contracts DIR --oracle table.json --hidden-root DIR`。
输入契约必须已冻结且 hash 有效，来源与存档完全一致。控制器独占的人工核对表按单元 key 列规则，
以下仅为合成例子：

```json
{"p2-1": [{"hidden_test": "test_integer", "hidden_artifact": "failure.txt",
  "sha256": "<隐藏测试产物的 SHA256>", "confirmed": true,
  "requirements": [{"source": "task", "quote": "Return 2.",
                    "expected_contains": ["integer", "2"]}]}]}
```

人工须先确认隐藏测试暴露的缺陷和应有行为；脚本只核对产物 hash 和文字映射。
每条规则都要找到引用来源、引用文字和所有预期片段相符、且不是 Unknown 的有效行为。
不让同一模型自判。缺证据、未确认、未解预期或没有规则时都是 Unknown。
这是清单文字覆盖，不等于审查实际抓住缺陷。报告保留全部 15 行、覆盖数、Unknown 数和 Unknown
效果门槛；不能据此打开默认值或改历史分数。

## 验证边界

合成回归和假 CLI 检查进程输入、引用校验、不可覆盖的 hash、证据分级、确定性人工表匹配、
预算校验及仓库外启动。本任务材料没有经确认的人工判定表，因此不报告新的抓错率。
真实模型质量、其他平台运行和 CI 需要另行验证。
