# 常见问题和同类项目

[English](faq.md) · 中文 · 回到 [README](../README.zh.md)

**和同名项目不是一个东西：** relayline 原名 `claude-codex-bridge`，但不是 [CCB](https://github.com/SeemSeam/claude_codex_bridge)（`SeemSeam/claude_codex_bridge`，同时看、同时指挥多个代理的可见终端工作区），也不是 OpenAI 官方的 [codex-plugin-cc](https://github.com/openai/codex-plugin-cc)（只把活从 Claude Code 交给 Codex）。见[同类项目对比](#同类项目对比)。

## 常见问题

**多一个智能体，不是更费 token 吗？** 是的：实测的小任务里 token 是 3.3 倍；因为子智能体便宜，美元基本持平（比值 1.02），慢约 23 秒。派活省的是主导自己的请求（主导看到 ccx 验收通过就直接答复时，每个任务少 1 次）；只有主导每次请求都要重读很长的对话时这才值钱，而这一点目前是外推。主导如果再自己跑一遍测试，就是多花子任务的钱。很小的任务 ccx 会直接让你自己做（`delegated: false`）。钱主要花在主导每轮重读自己的对话上，所以 `ccx lead`、`ccx sum`、`ccx fresh` 管的是这一块。`ccx report` 用你自己的运行算差多少；`ccx trial` 做一周的正式对比。

**我用的是订阅，不是 API。** 花费按 API 价格折算，方便互相比较；看板也会显示每个工具的额度用在了哪里。一边额度用完了，任务会换到另一边（实验性：只有替身测试，还没遇到过真实的额度用完）。

**让子智能体改文件安全吗？** 只能改任务所在的文件夹；每次可写运行都会拍快照，可以 `ccx undo`；`--mode read` 或 `--worktree` 不会动你的工作区。详见 [SECURITY.zh.md](../SECURITY.zh.md)。

**只读还是可以改文件？** 不加 `--mode` 时，ccx 按任务描述判断：说的是分析、解释、对比（analyze、review、explain……）就只读；要修复、添加、重构、改成（fix、add、refactor……）就可以改；判断不了时沿用原来的默认（可以改），并在结果里说明。`--mode` 永远优先。只读的子智能体发现必须改文件才能完成时，会停下并标成 `needs_write`，交回给你决定。

**它操作的是聊天网页吗？** 不是。两边调用的都是工作模式（`codex exec`、`claude -p`），也就是你在终端里用的那个智能体，不是网页聊天。

**支持哪些工具？** **主导：Claude Code、Codex、DeepSeek（真机实测）。**DeepSeek 当主导有两种：DeepSeek Harness（`dsh` 0.2.1-rc.3，无头模式，派活给 Codex），或跑 DeepSeek 模型的 Claude Code（派活给 Claude）；ccx 从环境变量认出它，账本里主导厂商记为 deepseek。跑 DeepSeek 模型的 Codex 靠它的 config 或 `CCX_LEAD=deepseek-codex` 认出，没当主导实测过。Gemini CLI 和配置好的各家 provider 不能当主导。**子智能体：**Claude Code 和 Codex 两个方向；DeepSeek 经 Claude Code（真实任务校准过）、经 Codex（一个小的只读任务）、以 `dsh` 身份（只读、可写、续接都真跑过；Windows 上 ccx 也能自己找到 DeepSeek Harness 桌面版自带的 `dsh`）。Gemini CLI 已适配（社区），**实验性、未实测**；Kimi、GLM、Qwen、OpenRouter 已配置，未实测。每家一个适配器（`ccx/agents/`），`ccx agents` 列出各自的能力；加一家的方法见 [CONTRIBUTING.zh.md](../CONTRIBUTING.zh.md)（从 `ccx/agents/_template.py` 和 `tests/fakes/fake_template.py` 开始）。

**官方还是社区？** *官方*（Claude Code、Codex CLI）：每次发版都在适配器 `tested_version` 写的版本上真跑只读、可写和续接任务（发版检查）。*社区*（Gemini CLI、`dsh`、新加的适配器）：按命令行的 `--help` 和文档写成，用模拟程序测过；`dsh` 还真跑过（只读、可写、续接）。装的版本主次版本号和 `tested_version` 不一样时，`ccx doctor` 会给 WARN：官方的请先跑发版检查再用，社区的表示在这个版本上没验证过。

**两个模型能直接讨论吗？** 能，有几种方式：`ccx ask` 问一次第二意见，`ccx resume` 在同一个子会话里追问，`ccx send` 发消息进正在运行的 Codex 会话（在它两轮之间送到），同一项目里开着的会话用留言板（`ccx say`）互相留言。选错代价高的决定可以用 `ccx discuss`：不同厂商的模型最多讨论 3 轮（一家出方案、一家挑错、一家裁判），轮与轮之间只传要点；主导开之前会先问你。

**运行记录 JSON 里的中文显示成 `���`？** 中文 Windows 上，Python 往管道打印时用代码页（cp936/GBK），读管道的工具按 UTF-8 解码就会显示成 `���`；ccx 写的文件本身是 UTF-8，没有坏。用 `ccx show <run>` 读，或者给跑你自己 Python 单行命令的 shell 设 `PYTHONUTF8=1`。ccx 读子智能体 CLI 的输出（stdout、stderr、Codex 的最后一条消息）时先按 UTF-8，不行再按本机代码页，解不开的字节保留成 `\xNN`，不替换掉（#335）。

## 同类项目对比

2026-10-24 查看（星数和日期来自 GitHub API，会变）。细节、来源和哪些还没确认：
[docs/research/landscape.zh.md](research/landscape.zh.md)。

| 项目 | 做什么 | 星数 · 最近推送 · 许可证 | 和 ccx 的区别 |
|---|---|---|---|
| Claude Code 自带的子智能体（Task 工具） | Claude Code 把子任务交给自己的子智能体，用的是它自己的额度；不用装任何东西 | 自带 | 最接近的替代，第 3–5 轮实测过（开发集，留出集待测）：做对的次数差不多；每次成功的花费第 3 轮内置 $0.069 对 ccx $0.071，第 5 轮内置 $0.114–0.202 对 ccx $0.116–0.135（精简做法的 builtin2 $0.114 比 ccx 的 r5h $0.135 便宜）；用时第 3 轮 41 秒对 63 秒，第 5 轮 276–316 秒对 236–267 秒（[实测](measured.zh.md)）。ccx 多给的：另一家的模型和额度、ccx 自己重跑你的 `--check`、另一家审查、账本、`ccx undo`。 |
| [openai/codex-plugin-cc](https://github.com/openai/codex-plugin-cc) | OpenAI 官方的 Claude Code 插件（2026-03-30）：让 Codex 审查、接活、把会话转给 Codex、管后台任务 | 3.45 万 · 2026-07 · Apache-2.0 | 只做 Claude → Codex，不选模型、不记花费。ccx 两个方向都做，另有按成本选模型、账本和主导成本。按设计可以一起用（命令和 hook 各是各的），但还没实测过一起用；装了它时 `ccx doctor` 会提示。 |
| [PAL MCP](https://github.com/BeehiveInnovations/pal-mcp-server)（`clink`） | MCP 服务器，把多家模型接进一个 CLI；`clink` 能启动另一个 CLI 当子智能体 | 1.18 万 · 2025-12 · Apache-2.0 | PAL 用 API key 接更多模型和工具；ccx 用两个 CLI 的订阅额度，按成功率和成本选，并用实际结果校准。 |
| [CCB](https://github.com/SeemSeam/claude_codex_bridge)（`SeemSeam/claude_codex_bridge`） | 可见的多智能体终端工作区，支持 16 类 CLI，代理间有消息队列，可随时接管 | 3,595 · 2026-10 · AGPL-3.0 | CCB 重在一起看、一起指挥多个代理；ccx 是无界面的派活工具，重在成本。名字相近，但是不同的项目。 |
| [sendbird/cc-plugin-codex](https://github.com/sendbird/cc-plugin-codex) | 跑在 Codex 里调 Claude Code 的插件（官方插件的反方向） | 226 · 2026-10 · Apache-2.0 | 只做 Codex → Claude。 |
| [umum-ai](https://github.com/umum-ai/claude-codex-bridge) / [Jayden-X-L](https://github.com/Jayden-X-L/claude-codex-bridge) 的 `claude-codex-bridge` | 在 Claude 里调 Codex 并可中途追加指令 / 双向互相审查 | 10 / 16 · 2026 · MIT | 各做一部分（插话、审查），不选模型、不记账。 |
| [claude-codex-memory-sync](https://github.com/DaizeDong/claude-codex-memory-sync)、[mycelium](https://github.com/conradomateu/mycelium)、[memorize](https://github.com/shakystar/memorize) | 在工具之间同步技能、指令、MCP 和记忆 | 1–31 · 2026 · MIT | 只管配置和记忆；ccx 的共享记忆是为派活服务的。 |

ccx 没有的：可见的分屏界面；子智能体干活途中追加指令（`ccx send` 只能在一个开着的 Codex 会话两轮之间送到）；多家模型投票（`ccx discuss` 最后由一家裁判）；把整段对话搬进 Codex。ccx 还欠的：用真实的长对话主导测出来的节省
（见本页开头）。
