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
context 上限 $4，memory 上限 $3。dry-run 分别显示本次预算与任务上限，估价超过本次预算时退出 2；
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

`results.jsonl` 保留隐藏测试失败、运行失败和中断。花费未知时保留全部单元预留并停止，不当作零；
总预算耗尽、单次超预留或中断也不再启动下一单元。已发请求可能超出 token 监控预算，因此不是账单保证。
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
