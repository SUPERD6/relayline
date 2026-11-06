# 单次尝试时限与阶段收据

[English](timeouts.md) · 中文

`ccx run` 和 `ccx resume` 已有 `defaults.timeout_sec` 配置，作用于每次 CLI 尝试（含重试）。
默认仍为 **1800 秒（30 分钟）**，不是所有尝试、检查和审查的累计时限。
通过现有配置命令调整；后续运行启动时读取配置：

```sh
ccx config set defaults.timeout_sec 2400
ccx config get defaults.timeout_sec
```

超时时，超时的那次 attempt 新增 `timeout_context`。只有运行最终 kind 为 `timeout`，运行记录和
`run`、`resume`、`show` 展示的收据才在顶层附上它。升级重试成功后，早先的超时证据留在原 attempt 内，顶层不带超时字段。
现有 status、kind、退出码、`result` 和 `files_changed` 含义都不变；原 `files_changed` 仍来自子智能体的结构化回报。

| `timeout_context` 内的新增字段 | 含义 |
|---|---|
| `files_changed` | 相对 Git 根目录的实际路径，通过针对原快照的 `git diff --name-only` 和 `git ls-files --others --exclude-standard` 获取，不读 diff 正文或未跟踪文件内容。含跟踪文件的修改、删除和新增未跟踪文件；排除运行前已有改动与 `.ccx/`。原目录和 worktree 都适用。没有 Git 快照或 Git 取证失败时为 `null`，表示 Unknown。 |
| `last_assistant_message` | 已捕获的 CLI JSON 事件流中，最后一条非空 assistant 文本。超过 4000 字符时保留末尾 4000 字符，以保留通常写在末尾的阶段结果。排除工具输出、推理和错误消息。未捕获到时为 `null`，表示 Unknown。 |
| `last_assistant_message_truncated` | 消息是否超过字符上限。 |

原有 `diffstat` 继续提供改动摘要。已有文件留在原处，供检查或用 `ccx resume <run_id>` 接续；
新增证据不把超时改判为成功。Git 证据沿用现有快照的限制（例如不含被忽略文件），不在 Git 之外递归扫描目录。

## 可选提醒（实验性）

```sh
ccx config set defaults.timeout_reminder true
# 恢复默认：
ccx config set defaults.timeout_reminder false
```

默认 **false**，派活文字保持原样。打开后，每次尝试的提示词写明时限（分钟与秒），要求接近时限时先写阶段结果，
包括改了什么、已经跑的检查和下一步。续接和重试也适用。这是**开始时的指令**，不是临近时限才发出的通知：
ccx 不向正在运行的 CLI 注入新消息。运行中注入支持情况为 **Unknown**；子智能体是否会遵从提醒也为 **Unknown**。
CLI 如果在输出 assistant 文本前被切断，就没有可恢复的消息。

证据等级：仅 **engineering check**，使用一秒时限和假 CLI；未真跑智能体，未测出收益。
保留所有命令、选项和原超时判定规则。
