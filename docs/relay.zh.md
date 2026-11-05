# 实验性额度接力

[English](relay.md)

证据等级：**engineering check**，只有假 CLI 检查和 Claude 已捕获事件回放。
默认 `[relay] enabled = false`。现有派活判定、JSON 字段、命令和退出码保持不变。
本功能保存交接包，再由显式命令在另一家启动新主导；不透明接管已打开的终端或桌面会话。

## 保存与接续

在 Git 工作区运行，`SESSION_ID` 换成源会话 id：

```text
ccx config set relay.enabled true
ccx sync --only hooks --apply
ccx relay capture --session-id SESSION_ID --goal "完成解析器" --progress "解析器已写一部分" --next-step "核对 diff 并跑解析器测试"
```

`capture` 按会话保存上下文供后续钩子读取。请在有意义的进展后更新；不从私有对话记录提取目标和进度。
Claude 的 `StopFailure` 钩子使用 matcher `rate_limit`，执行 `ccx relay capture --hook`。
交接包和 `.notification.json` 通知原子写入工作区 `.ccx/relay/`。
包内有显式目标、进度、下一步、源会话、Git HEAD、暂存与未暂存 diff、未提交文件清单和接手命令。
缺失上下文写 `Unknown`；目标未知时禁止接续。未跟踪文件只列清单、不复制；不读取私有 transcript。
请在 Git 中忽略 `.ccx/`；本地交接包可能含源码 diff，不要直接发布。

先停止旧会话、其子任务及额度自动恢复等待，再用 capture 输出的包 id：

```text
ccx relay continue PACKET_ID --to codex --budget-seconds 300 --old-stopped
ccx relay continue PACKET_ID --to codex --budget-seconds 300 --old-stopped --launch
```

第一条只准备 prompt 和 argv，不调用模型。`--launch` 才显式启动受监督的 `codex exec --json --sandbox workspace-write` 或 `claude -p --output-format stream-json --verbose`，沿用原工作区和原生工具，不绕过权限。
预算必填，必须是有限正数，单位为**墙钟秒数**，不是美元上限。此新主导路径的美元记账和封顶 **Unknown / 尚未实现**；不单独约束原生子任务花费。
准备和启动前都执行 `git diff`、`git diff --cached`，核对 HEAD 并记录当前状态。HEAD 变化时需人工核对后重新 capture。未提交修改有变化时交给新主导检查，绝不 reset。
prompt 要求新主导先检查半成品和运行相关检查，再编辑；这不能证明模型遵守，`verification` 仍为 `not-run`。
监督器保存 argv、prompt、PID、退出码和 stdout/stderr 日志；到时终止子进程树并保留半成品。
新主导输出显式限额拒绝时，即使退出码为零，也会保存新的交接和通知；不会自动启动另一家。
持久排他启动声明禁止同一包重复启动。崩溃后检查 PID 和记录、停止孤儿写入者，再重新 capture。外部强杀监督器可能留下 CLI；最小版没有 watchdog，也不自动恢复。

## 信号与原生功能重叠

`ccx/quota_signals.py` 优先识别协议证据：Claude 使用窗口被拒绝、显式 `usage_limit_reached`、Claude `StopFailure` 的 `rate_limit`。
单独 HTTP 429、认证或网络错误、正常额度读数、任意工具/用户/模型正文均不算。原派活的历史限额分类逻辑不变。
`tests/data/real_signals` 中 Claude 样本来自脱敏实录；**Codex 限额样本是合成的**，不是实录。

2026-11-05 核对：`claude --version` / `claude --help` 为 **2.1.316**；`codex --version` / `codex exec --help` 为 **0.164.0**。未调用真实模型。

* [Claude hooks 官方文档](https://code.claude.com/docs/en/hooks#stopfailure)：StopFailure 的输出和退出码不能让会话继续。实现的提示音使用文档允许的 `terminalSequence` 例外；`-p`/SDK 会忽略它，落盘通知仍可查看。
* [Claude settings 官方文档](https://code.claude.com/docs/en/settings-reference#autocontinueatusagelimit)：原生 `autoContinueAtUsageLimit` 等待同一账号恢复后自动继续，默认 true，要求 2.1.234 起。它与等待/恢复重叠，不提供跨厂商接力。ccx 不修改此设置；换家前需停止原生等待，避免双写。本轮抓取的官方页面未找到准确的 `quota_auto_resume_*` Notification matcher 名称，记 **Unknown**。
* [Codex 非交互模式官方文档](https://learn.chatgpt.com/docs/non-interactive-mode)：`codex exec --json` 可给独立监督器提供事件。抓取的 [Codex hooks 文档](https://learn.chatgpt.com/docs/hooks) 未确认对应的限额 StopFailure 钩子，记 **Unknown**；不安装 Codex 限额钩子。

## 桌面一分钟检查（2026-11-05，待本人验证）

1. 在一次性 Git 项目按上文开启并同步钩子。在**新开的桌面 Code 会话**输入 `/hooks`，确认 `StopFailure` → `rate_limit` → `ccx relay capture --hook`。
2. 若正常使用的会话已经自然限额，发一个无害请求，查看 `.ccx/relay/*.notification.json` 是否新增，检查包里的桌面会话、HEAD 和脏文件。尚未限额时只检查钩子可见性，实际事件投递仍为 **Unknown**，不要为了验证耗尽额度。
3. 停止旧会话及其自动恢复。运行不带 `--launch` 的 `relay continue ...` 查看另一家的交接内容。

桌面钩子执行和提示可见性均**未实测**。一分钟可核对注册；实际限额事件需要已限额会话，不能承诺一分钟内验证。

关闭方法：`ccx config set relay.enabled false`，再 `ccx sync --only hooks --apply`。关闭时遗留 capture 钩子静默无操作。uninstall 只移除 ccx 的接力 handler，保留其他 handler。
