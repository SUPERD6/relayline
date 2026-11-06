# 凭据目录保护（实验性）

[English](credential-guard.md) · 中文 · [威胁模型](threat-model.zh.md)

使用 `ccx config set security.credential_guard true` 开启，**默认关闭**。
现有命令、选项、沙箱默认值、JSON 含义与判定规则保持不变。
用 `ccx config set security.credential_dirs "path-one;path-two"` 追加目录；
相对路径以任务原始工作目录为基准。证据等级是 engineering check，未实测恶意智能体隔离效果。

保护覆盖普通 `ccx run` 派活（含其续跑、回退和审查）；独立的 `ccx relay` 直接 Popen 路径
**没有接入此保护**，不能假定 relay 已注入这些规则。

默认只禁凭据：默认及配置的 Claude home 下 `.credentials.json`、`auth*`，默认及配置的 Codex home 下
`auth*`（含 `auth.json`）、根目录 `*.sqlite*` 数据库与附属文件，整个项目 `.ccx/eval-codex-home`，
以及明确追加的目录。正常 skills、`projects/*/memory`、tool-results 等不再被整 home 禁读。
原始和子进程 home 都纳入；相对环境 home 分别按原始任务 cwd、worker cwd 解析，不按 ccx 进程 cwd。
通过 `resolve(strict=False)` 同时纳入原始写法和规范路径。它会查询文件系统元数据，并非纯字符串操作；
用于解析链接、junction 和受平台支持的 Windows 短名，不读取文件内容、不列目录。
解析失败时保留原路径，不保证所有别名都覆盖。测试只用临时路径和确定性的别名解析替身。

Claude 临时 `--settings` 追加 `permissions.deny`：敏感目标的 Read 规则，以及包含可识别路径写法的 Bash 规则。
保留已有设置和 deny，不修改用户配置文件。开启后要求 settings 为内联 JSON；无法检查的设置或绕过权限的模式在启动前拒绝。
这不是操作系统隔离：任意 Python/Node 程序、从父目录递归搜索、`cd ~ && cat .claude/.credentials.json`、
路径别名或 MCP 仍可能绕过。Windows Bash 规则包含盘符/反斜杠、Git Bash `/c/...`、`//c/...` 写法，
以及整路径小写和大写变体。Bash 通配匹配**区分大小写**，任意混合大小写仍可能绕过。
Read 使用官方说明的 `//c/...` 盘符归一化；不能据此声称所有工具匹配均不区分大小写。启动前会警告。
需要所有进程都不可读取时，应使用外部操作系统隔离。

Codex 等其他适配器在**启动前**警告，并在运行记录新增
`credential_guard: {status: "Unknown", mechanism: "unverified"}`，保留现有沙箱参数。
Claude 记录 `status: "Unknown"`、`mechanism: "claude-permissions-deny"`，不把注入规则当作已验证隔离。
`rules_added` 仅表示规则已注入启动设置，**不统计拒绝次数**，也不把已有 CLI 拒绝计数归因到这些规则。
**Codex 未受到本 guard 的禁读保护**。记录和警告不添加凭据内容或目录清单。
CLI 自身的认证和启动配置加载不属于工具规则保护范围。
Claude 生成的 settings 上限为 22,000 字符，完整引用后的命令上限为 30,000 个 UTF-16 单元，
低于 Windows 的 32,767 单元上限；过长时启动前报错，不截断保护规则。
配置错误走现有配置错误退出码 3，记录为 finished/error，不再误记 killed/被中断，也不产生 CLI 尝试。

## CLI 依据（2026-11-05）

- 本机核对 `codex-cli 0.164.0 --help`：支持 `-c key=value` 和 read-only/workspace-write；
  这些模式本身不能证明按目录禁读。
- [Codex 官方权限文档](https://learn.chatgpt.com/docs/permissions) 提供 filesystem `deny` 和 profile 继承；
  这些 beta 配置在已核对版本/平台上的支持与执行效果**尚未确认**，不传猜测配置，也不悄悄替换沙箱默认值。
- [Claude 官方权限文档](https://code.claude.com/docs/en/permissions) 说明 deny 优先级、绝对路径 `//`、
  Windows 盘符归一化、Bash 命令模式任意位置的 `*`（含 `Bash(*...*)`）和任意程序绕过限制。
  官方文档核对日期 2026-11-05，现有适配器核对基线为 Claude Code 2.1.309；
  本次未调用真实 Claude 或模型。

测试只用临时假 home 和 `tests/fakes`，核对路径构造、已有设置保留、警告，以及从仓库外启动 `ccx run` 的接线。
未证明真实 CLI 或操作系统隔离效果。
