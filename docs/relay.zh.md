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
包内有显式目标、进度、下一步、源会话、Git HEAD、有上限的暂存与未暂存 diffstat、未提交文件清单和接手命令，不存全文 diff。
缺失上下文写 `Unknown`；目标未知时禁止接续。未跟踪文件只列清单、不复制；不读取私有 transcript。
capture 写入本地 `.ccx/relay/.gitignore`，避免交接包进入 Git。文件清单最多 200 条、每条 512 字符；diffstat 与上下文摘要分别最多 4,096 字符。脏文件指纹在快照时限内读取最多 200 个路径、8 MiB，只存 SHA256，跳过私有路径和仓库外链接。钩子保持每条 Git 命令两秒、快照总计六秒；手动 capture/continue 默认每条 30 秒、每次快照 120 秒，`--git-timeout-seconds 60` 可改为 60/240 秒。接续者再次保存交接包时也沿用该设置；不改变模型墙钟预算，也不新增配置键。超时先保存含 Unknown 快照、原因和重试方法的最小包再通知；Git 快照 Unknown 时禁止接续，需先看 `git status`，用更长超时手动重新 capture，再用该超时 continue。子智能体钩子（`CCX_DEPTH > 0` 或 `CCX_ROLE=subagent`）静默返回。

先停止旧会话、其子任务及额度自动恢复等待，再用 capture 输出的包 id：

```text
ccx relay continue PACKET_ID --to codex --budget-seconds 300 --old-stopped
ccx relay continue PACKET_ID --to codex --budget-seconds 300 --old-stopped --launch
```

上述停止旧会话的步骤适用于已确认额度耗尽的交接（`state=quota_stopped`）。裸 StopFailure
`rate_limit` 保存为 `state=rate_limit_unconfirmed`，通知“可能只是限速，可以等一下或手动接续”，
不建议停止旧会话。可用 `relay continue ... --to codex --budget-seconds 300` 查看准备结果，
无需强制确认或停止声明。真正启动必须显式带 `--force-unconfirmed --old-stopped --launch`；
force 不绕过工作区锁、已知写进程检查、Git 核对或预算。旧 StopFailure 和 rate_limit_event 包
缺少 `usage_confirmed=true` 时也要求 force。

第一条只准备 prompt 和 argv，不调用模型。`--launch` 才显式启动受监督的 `codex exec --json --sandbox workspace-write` 或 `claude -p --output-format stream-json --verbose --permission-mode acceptEdits --permission-prompts none`。Claude 的原生文件编辑权限不等于 Codex 的操作系统沙箱，其他工具仍可能被拒绝；不启用权限绕过。退出码零但没有观察到工作区改动时返回 `no_changes`，不报成功；验证仍为 `not-run`。
子进程退出码零但改动检测为 Unknown 时，单独返回 `changes_unknown`，提示人工查看 `git status`，
ccx 命令退出码为 2。记录中的 `exit_code` 仍指子进程，所以可以保持零。
2026-11-05 重新核对 **Claude Code 2.1.316 --help**：即使使用 `acceptEdits`，
`--permission-prompts none` 也会自动拒绝需要询问的工具。交接包没有可信的精确检查命令字段，
因此不增加 `--allowedTools` 授权。Claude 提示词说明原生编辑权限及 Bash/PowerShell/测试可能被拒绝，
要求无法检查时报告具体被拒绝的命令，并将测试标为 `not-run`。
预算必填，必须是有限正数，单位为**墙钟秒数**，不是美元上限。此新主导路径的美元记账和封顶 **Unknown / 尚未实现**；不单独约束原生子任务花费。
准备和启动前都检查暂存与未暂存 diffstat、HEAD 和当前状态。HEAD 变化时需人工核对后重新 capture。未提交修改有变化时交给新主导检查，绝不 reset。
prompt 要求新主导先检查半成品和运行相关检查，再编辑；这不能证明模型遵守，`verification` 仍为 `not-run`。
监督器保存 argv、prompt、PID、退出码和 stdout/stderr 日志；到时终止子进程树并保留半成品。
新主导输出显式限额拒绝时，即使退出码为零，也会保存新的交接和通知；不会自动启动另一家。
持久包声明禁止同一包重复启动，工作区级锁阻止不同包同时启动。锁记录 PID 和时间，失效锁必须先人工核对孤儿进程；启动进程失败会释放两把锁。启动前检查同 Git 工作区（含子目录）的已知 ccx 运行 PID。没有 ccx 记录的原生进程及自动恢复状态仍为 Unknown；`--old-stopped` 是必需的用户声明，不能证明所有写入者已停止。外部强杀监督器可能留下 CLI；没有 watchdog，也不自动恢复。

## 信号与原生功能重叠

`ccx/quota_signals.py` 优先识别已知用量窗口被拒绝、显式 `usage_limit_reached` 或错误包中的明确额度文案。
StopFailure 和被拒绝的 rate_limit_event 缺少这些证据时保留 `rate_limit_unconfirmed`；
仅有重置时间或每分钟请求限制不能证明额度耗尽。认证、网络、账单错误、正常额度读数和任意工具/用户/模型正文
不算额度耗尽。原派活的历史限额分类逻辑不变。
`tests/data/real_signals` 中 Claude 样本来自脱敏实录；**Codex 限额样本是合成的**，不是实录。

2026-11-05 核对：`claude --version` / `claude --help` 为 **2.1.316**；`codex --version` / `codex exec --help` 为 **0.164.0**。未调用真实模型。

* [Claude hooks 官方文档](https://code.claude.com/docs/en/hooks#stopfailure)：StopFailure 的输出和退出码不能让会话继续。实现的提示音使用文档允许的 `terminalSequence` 例外；`-p`/SDK 会忽略它，落盘通知仍可查看。
* [Claude settings 官方文档](https://code.claude.com/docs/en/settings-reference#autocontinueatusagelimit)：原生 `autoContinueAtUsageLimit` 等待同一账号恢复后自动继续，默认 true，要求 2.1.234 起。它与等待/恢复重叠，不提供跨厂商接力。ccx 不修改此设置；换家前需停止原生等待，避免双写。本轮抓取的官方页面未找到准确的 `quota_auto_resume_*` Notification matcher 名称，记 **Unknown**。
* [Codex 非交互模式官方文档](https://learn.chatgpt.com/docs/non-interactive-mode)：`codex exec --json` 可给独立监督器提供事件。抓取的 [Codex hooks 文档](https://learn.chatgpt.com/docs/hooks) 未确认对应的限额 StopFailure 钩子，记 **Unknown**；不安装 Codex 限额钩子。

## 桌面一分钟检查（2026-11-05，待本人验证）

1. 在一次性 Git 项目按上文开启并同步钩子。桌面 Code 标签页不支持 `/hooks`，用下面两种办法之一检查注册：(a) 在终端运行交互式 `claude`，输入 `/hooks`；(b) 直接看 `~/.claude/settings.json` 里的 `hooks.StopFailure`（桌面 app 和 CLI 共用这个文件）。两种办法都要确认有 matcher `rate_limit` → `ccx relay capture --hook`。之后新开一个桌面会话让它读到该文件。
2. 若正常使用的会话已经自然限额，发一个无害请求，查看 `.ccx/relay/*.notification.json` 是否新增，检查包里的桌面会话、HEAD 和脏文件。尚未限额时只检查钩子可见性，实际事件投递仍为 **Unknown**，不要为了验证耗尽额度。
3. 停止旧会话及其自动恢复。运行不带 `--launch` 的 `relay continue ...` 查看另一家的交接内容。

2026-11-10 已用模拟的 StopFailure 事件（经 stdin 喂给钩子命令）验证能写出 `.ccx/relay/*.notification.json`（状态 `rate_limit_unconfirmed`）；真实限额时桌面是否触发钩子、提示是否可见仍为 **Unknown**。一分钟可核对注册；实际限额事件需要已限额会话，不能承诺一分钟内验证。

关闭方法：`ccx config set relay.enabled false`，再 `ccx sync --only hooks --apply`。关闭时遗留 capture 钩子静默无操作。uninstall 只移除 ccx 的接力 handler，保留其他 handler。
