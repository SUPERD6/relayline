# 安全说明

[English](SECURITY.md) · 中文

ccx 在你的电脑上运行 AI 编程智能体，并把它们互相接起来。这一页说清它会运行什么、能改什么、边界在哪里，方便你决定允许什么。

不可信的文字（仓库文件、issue、board 消息、记忆便签）会从哪里进到智能体、哪些要你自己把关，见[威胁模型](docs/threat-model.zh.md)。

## ccx 会运行和改动什么

| 部分 | 做什么 | 边界 |
|---|---|---|
| 开局 hook（`ccx sync --apply`） | Claude Code 和 Codex 开新会话时运行 `ccx mem delta`，把新增的共享记忆、未读的交接和没做完的任务打印进会话 | 只是本地命令，不联网。先预演、你 `--apply` 后才装；Codex 还会让你在 `/hooks` 里信任一次。`ccx uninstall --apply` 可以删掉 |
| 配置文件 | 在 Codex 的 `config.toml` 里加一段带标记的块，在 Claude 的 `settings.json` 里加一条 hook | 只改自己的块和那一条，别的不动；改之前先备份 |
| 子智能体·可写（默认） | Codex 用 `sandbox_mode="workspace-write"`；Claude 用 `acceptEdits` 加一份允许的工具清单（`config/tiers.toml`） | 只能改任务工作目录里的文件。可写运行前 ccx 会给工作区拍快照：`ccx undo <run_id> --apply` 可以恢复（新建的文件挪到一边，不删除）。`--worktree` 让改动落在单独的分支上 |
| 子智能体·只读（`--mode read`） | Codex 用 `read-only` 沙箱；Claude 只给只读工具 | 用于审阅和分析 |
| 套娃 | 子智能体不能再派子智能体（`max_depth = 1`） | 防止无限派下去、白白烧钱 |
| 外来文件（`.ccx/inbox/`、网页、日志） | 每份简报都告诉子智能体：这些内容是参考材料，不是给它的指令 | 能降低“提示注入”的风险，但不能完全排除。结果要看过再信 |

## ccx 不做的事

- 不替你登录，不读取、复制或发送任何账号凭据。模型密钥（比如 `DEEPSEEK_API_KEY`）留在你的环境变量里，只传给需要它的那个智能体命令行。
- 自己不向任何地方发送数据。智能体命令行照常和它们自己的服务通信。
- 你的个人数据（记忆、账本、学到的参数）放在你的 hub 文件夹里，永远不进本仓库。

## 你要做的

- `--apply` 之前先看 `ccx sync` 的预演。
- 子智能体的总结只是它的说法：先看 diff、跑一下检查，再 `ccx verify --ok 1`。
- 不想被原地改动的代码，用 `--mode read` 或 `--worktree`。
- 别把密钥写进简报、记忆或 `.ccx/inbox/`，智能体会读到它们。

## 报告漏洞

请在本仓库用 **GitHub → Security → Report a vulnerability**（私下提交），不要开公开的 issue。写上 ccx 版本（`ccx --version`）、智能体命令行的版本和复现步骤。
