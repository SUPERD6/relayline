# 真实额度事件登记（模板和步骤）

[English](quota-event-log.md) · 相关：[额度接力](relay.zh.md)

证据等级：**engineering template**（只是工程模板）。目前没有记录过任何真实额度事件，所以真实限额会不会触发接力的
`StopFailure` 钩子仍是 **Unknown**（只有 2026-11-10 的模拟事件，见 [relay.zh.md](relay.zh.md)）。
本页只是给真实事件发生时一个统一存证据的地方，不加代码，不改默认。

## 可能的结果（都算正常结果）

| 结果 | 你看到什么 | 含义 |
|---|---|---|
| A. 钩子触发 | 事件前后 `.ccx/relay/` 多出新的 `*.notification.json` 和接力包 | 钩子在真实限额下可用，可以接着做接力 |
| B. 被原生 auto-continue 接管 | 没有新包；会话显示在等重置，之后自己继续，或一直可见地在等 | **不是 bug。** Claude Code 的 `autoContinueAtUsageLimit`（2.1.234 起默认开）接管了额度用完的情况，回合没有以错误结束 |
| C. 钩子没触发，也没在原生等待 | 没有新包，会话只是停住并显示限额提示 | 可能是 bug：按第 7 步开 bug issue |

怎么区分 B 和 C：(1) 看 `~/.claude/settings.json`（Windows 是 `%USERPROFILE%\.claude\settings.json`）里的
`autoContinueAtUsageLimit`，没有这个键就是默认值，也就是开；(2) 桌面端看 auto-continue 勾选框；(3) 看录屏：出现倒计时或
“将自动继续”之类的字样就是 B。把你能查到的几项都写下来；一项都查不到就写 Unknown，结果记“未判定”。

## 事件发生时的步骤

按顺序做，每步只做一件事。不要为了测这个故意耗尽额度。

1. 保持录屏，先别关会话窗口。记下第一次看到限额提示的时钟时间。
2. 在项目目录打开终端，运行 `claude --version`，再运行 `codex --version`，把两行抄进记录。
3. 运行 `git status`，把输出抄进记录。
4. 运行 `dir .ccx\relay`（macOS/Linux 用 `ls .ccx/relay`），把文件名和时间抄进记录；目录不存在或没有新文件就写“无新文件”。
5. 如果有 `*.notification.json`，打开最新的一个，只抄 `state` 和提示文字那几行，不抄整个文件。
6. 按上面说的查原生 auto-continue 设置，写下查到的结果。
7. 判定结果 A、B 或 C。A：用 `ccx relay continue PACKET_ID --to codex --budget-seconds 300 --old-stopped` 继续
   （见 [relay.zh.md](relay.zh.md)），再跑任务需要的检查，写下回执；C：开一个 GitHub bug issue，链接这份记录，并写明当时
   auto-continue 开没开。
8. 把填好的记录存为 `.ccx/relay/events/<日期>-quota-event.md`（本地文件，`.ccx/` 不进 Git）。录屏放在旁边，或记下存放位置。

## 不能放进仓库（也不能放进 issue/PR）的东西

- 私人对话内容、提示词、会话记录，以及不公开的任务内容。
- 凭据：API key、token、`auth.json`、cookie，`~/.claude`、`~/.codex` 下除了读到的那一个设置值以外的任何内容。
- 个人路径、用户名、邮箱。用 `<user>`、`<project>` 代替。
- 录屏本身。留在本地，只写文件名。
- 完整的接力包文件：里面有文件名和 diffstat，只抄模板里点名的字段。

如果某份记录要链接到公开 issue，先去掉以上内容，只贴填好的模板。

## 模板

把这一块复制到新文件里。凡是没能从实际文件或屏幕读到的字段写 `Unknown`，不要猜。

```markdown
# 额度事件 <YYYY-MM-DD>

- 事件时间（本机时钟，带时区）：
- Claude Code 版本（`claude --version`）：
- Codex 版本（`codex --version`）：
- ccx 版本（`ccx --version`）：
- 触发前在做什么（一句话，不含私人内容）：
- 哪个客户端遇到限额（桌面端 / 终端 / 其他）：
- 钩子有没有触发（是 / 否 / Unknown）：
- `.ccx/relay/` 文件（文件名和时间，或“无新文件”）：
- 通知的 `state` 和提示（只抄这几行）：
- `git status`（粘贴）：
- 原生 auto-continue：settings.json 里的值（开 / 关 / 没有这个键=默认开 / Unknown）：
- 原生 auto-continue：桌面端勾选框（开 / 关 / Unknown）：
- 会话是否在等限额重置（是 / 否 / Unknown）：
- 结果（A 钩子触发 / B 原生接管 / C 钩子没触发 / 未判定）：
- 接力结果（用的命令、最终状态如 `no_changes`、退出码；没接力就写没有）：
- 接力后跑的检查和回执（命令和通过/失败，或“未跑”）：
- 录屏文件名（只写名字）：
- C 时的 bug issue 链接：
- 其他 Unknown：
```
