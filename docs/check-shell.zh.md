# 验收命令的 shell

[English](check-shell.md) · 中文

Windows 的普通 `--check` 命令继续使用 `cmd.exe`，保留现有单引号与通配符兼容处理。
`&&` 本身在 cmd.exe 中有效，不会单独触发切换。不移除命令或选项，不改配置默认值和退出码约定。

命令含 shell 层的 `export`、前置 `NAME=value`，或 `$VAR`、`${VAR}`、`$(...)` 展开时，
使用 PATH 中的 Bash，或从 Git 安装目录找到 Git Bash。传给 Bash 的命令不经过 cmd.exe
引号和通配符改写，且不加载 profile/rc。单引号字面量、程序字符串里的 `export` 不触发切换。
PowerShell 的 `$env:NAME` 表达式、字面路径里的美元符不触发切换。
这只是语法识别，不是完整 shell 解析器；复杂脚本应写入文件并明确指定解释器。
`System32`、`SysWOW64`、`Sysnative` 和 `WindowsApps` 下的 WSL 启动器不当作 Git Bash。
查找 Git Bash 时也检查父目录，兼容 `mingw64/bin` 和标准 Scoop 目录。

需要 Bash 但找不到（包括查找后可执行文件消失）时，沿用 `check_broken`，给出原因和完整安装/改写办法，
其他操作系统错误保持原行为。
不会判为代码 `check_failed` 或触发升档。命令成功启动后出现测试失败，保持现有判定。
Linux/macOS 沿用原有 shell 路径。
选择 Bash 的命令含反斜杠路径时，检查结果新增 `shell_warning`，提醒使用正斜杠或谨慎引用
Windows 路径，因为 Bash 会解释转义符。

证据等级：使用隔离测试与假 agent CLI 的 **engineering check**；真实 agent 评测：**not run**。
