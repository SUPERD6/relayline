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

Codex（#289 起）改用 **permission profile** 运行，不再用旧的沙箱模式：ccx 把自己传的
`-c sandbox_mode="read-only"` / `"workspace-write"` 换成 `-c default_permissions="ccx-credential-guard"` 和内联的
`-c permissions.ccx-credential-guard={extends=":read-only"|":workspace", filesystem={<目标>="deny", ...}}`，
禁读目标与 Claude 相同。不写用户的 Codex 配置文件；`exec resume` 用同样的参数。
参数无法检查或会让 profile 失效时，启动前拒绝（配置错误，不产生尝试）：`--sandbox`/`-s`、
`--dangerously-bypass-approvals-and-sandbox`、`--approve-for-me`、`-p/--profile`、`sandbox_mode="danger-full-access"`、
已有 `default_permissions`/`permissions.*`/`sandbox_workspace_write` 覆盖、`--config=` 写法、无法解析的 Codex 配置文件，
以及 Windows 上的 **unelevated** 沙箱（`windows.sandbox` 取后面的 `-c` 或第一个设置它的配置文件）。
实测（见下）：unelevated 沙箱遇到禁读条目直接拒绝启动会话；**elevated** 沙箱给匹配的文件和目录加
`CodexSandboxUsers:(DENY)(R)` ACL 来执行禁读，**运行结束后这些 ACL 仍然保留**。它们只影响 Codex 的沙箱账户，
不影响你本人和 Codex 主进程，可用 `icacls <路径> /remove:d CodexSandboxUsers` 去掉。Codex 的 permission profile 仍是 **beta**。
不覆盖：MCP 服务器、Codex 进程内的工具（如看图）以及 Codex 主进程自己的读取。Codex 文档说任何已加载配置文件里的
`sandbox_mode` 会让它改用旧沙箱；实测 codex-cli 0.164.0 仍按 `-c` 的 profile 执行，所以 ccx 不拒绝，但记录
`config_sets_sandbox_mode: true` 并在警告里说明。检查的配置文件：`CODEX_HOME/config.toml`（`--ignore-user-config` 时跳过）
和从任务目录到仓库根的 `.codex/config.toml`；不检查托管（`requirements`）配置。Linux/macOS 的执行效果
（按 Codex 文档是 bubblewrap / Seatbelt）**未在本机实测**。

Codex 记录 `credential_guard: {status: "Unknown", mechanism: "codex-permission-profile", rules_added: true}`，
Windows 上另记 `windows_sandbox`（`elevated`、未设置时为 `default` 等）。其他适配器在**启动前**警告，并记录
`{status: "Unknown", mechanism: "unverified"}`，保留现有沙箱参数。
Claude 记录 `status: "Unknown"`、`mechanism: "claude-permissions-deny"`，不把注入规则当作已验证隔离。
`rules_added` 仅表示规则已注入启动设置。
每次尝试结束后统计看到的拒绝：Codex `access_denied_commands` = 非零退出且输出含拒绝访问信息
（`Access is denied`、`Permission denied`、`Operation not permitted` 等）的 shell 命令数；Claude `refused_tool_calls`
= CLI 自己的 `permission_denials` 计数。两者**不区分拒绝原因**（禁读、沙箱、允许列表都算），不归因于禁读本身；
不经 shell 的读取看不到。顶层数值是整次运行的合计。记录和警告不添加凭据内容或目录清单。
CLI 自身的认证和启动配置加载不属于工具规则保护范围。

开启时，`attempts[n].credential_guard` 保留各次启动证据，包括满载后换模型的尝试。
顶层 `credential_guard` 取本次运行所有尝试里最弱的状态（依次为 `Fail`、`Unknown`、`Pass`），
并新增 `attempts` 摘要，包含从零开始的 `n`、agent、model 和禁读证据。
状态相同时，`unverified` 比已注入规则更弱；原有 mechanism 和 `rules_added` 字段描述最弱的那次，
不代表整次运行；其他尝试的证据保留在摘要里。核对每次启动，以 `attempts[].credential_guard` 为准。
Claude 和 Codex 都报告 `Unknown`，注入的规则或 profile 不代表 `Pass`。
启动警告同时写入运行记录的 `credential_guard_warnings` 列表，包含从零开始的 `attempt`、agent 和 message。
紧凑的 `run`/`show` 收据也包含汇总与警告。中断后恢复成 attempt 时保留禁读证据。
主导选择 `line` 模式时，有禁读警告或禁读状态不是 `Pass` 就保留完整收据；直接使用 line 视图也保留两个禁读字段。
开关关闭时不新增这些字段，已有收据输出保持不变。

Claude 生成的 settings 上限为 22,000 字符，完整引用后的命令上限为 30,000 个 UTF-16 单元，
低于 Windows 的 32,767 单元上限；过长时启动前报错，不截断保护规则。
配置错误走现有配置错误退出码 3，记录为 finished/error，不再误记 killed/被中断，也不产生 CLI 尝试。

## CLI 依据（2026-11-05，Codex 部分 2026-11-16 更新）

- 2026-11-16（#289）：Windows 11 上的 `codex-cli 0.164.0`。`codex exec --help` 有 `-c key=value`、`-p/--profile`
  （配置文件层）、`--sandbox`、`--ignore-user-config`；`codex sandbox --help` 有 `-P/--permission-profile`。
  [Codex 官方权限文档](https://learn.chatgpt.com/docs/permissions)（beta）：`[permissions.<name>]` 含 `extends` 和
  `filesystem` 条目 `read`/`write`/`deny`，用 `default_permissions` 选择；deny 也禁读；支持通配；profile 不与
  `sandbox_mode` 组合；Windows `unelevated` 遇到无法执行的策略会拒绝。
- 只用假文件（`FAKE-TOKEN-FOR-TEST`）、不调模型实测：elevated 后端上 `codex sandbox -c permissions.g={...} -P g -- cmd /c type <文件>`
  拒绝了被禁的文件、目录、绝对路径 `auth*` / `*.sqlite*` 通配和 `:workspace_roots` 通配（"Access is denied."），
  其他文件仍可读，不存在的路径也接受；之后 `icacls` 显示持久的 `CodexSandboxUsers:(DENY)(R)`。同样操作在 unelevated
  后端上每条命令都失败（"Restricted read-only access requires the elevated Windows sandbox backend"）。
- 用与 ccx 完全相同的 `-c default_permissions=... -c permissions.ccx-credential-guard={...}` 参数实测 `codex exec`：
  unelevated home 下会话没有启动（"windows unelevated restricted-token sandbox cannot enforce deny-read restrictions
  directly; refusing to run unsandboxed"），不花 token；关掉禁读时同一任务读出了假 token。配置里另设
  `sandbox_mode = "danger-full-access"` 的临时 home 得到同样的拒绝，说明 `-c` 的 profile 仍生效。
  `ccx run --to codex` 的实测见 PR。
- [Claude 官方权限文档](https://code.claude.com/docs/en/permissions) 说明 deny 优先级、绝对路径 `//`、
  Windows 盘符归一化、Bash 命令模式任意位置的 `*`（含 `Bash(*...*)`）和任意程序绕过限制。
  官方文档核对日期 2026-11-05，现有适配器核对基线为 Claude Code 2.1.309；
  本次未调用真实 Claude 或模型。

测试只用临时假 home 和 `tests/fakes`，核对路径构造、已有设置保留、Codex profile 参数与拒绝条件、警告、
拒绝计数，以及从仓库外启动 `ccx run` 的接线。测试本身不证明真实 CLI 或操作系统隔离效果；上面的实测只对所写版本和平台成立。
