# Acceptance command shells

English · [中文](check-shell.zh.md)

On Windows, ordinary `--check` commands keep using `cmd.exe`, including its existing
single-quote and glob compatibility handling. `&&` alone is valid in cmd.exe and does
not change the shell. No command, option, configuration default or exit-code convention changes.

Commands with shell-level `export`, leading `NAME=value`, or `$VAR`, `${VAR}` or
`$(...)` expansion use Bash from PATH, or Git Bash found beside Git. Bash receives
the command without cmd.exe quote/glob rewrites and runs without profile/rc files.
Single-quoted literals and quoted program text containing `export` do not select Bash.
PowerShell `$env:NAME` expressions and dollars embedded in literal paths do not select
Bash. This is syntax detection, not a complete shell parser; write complex scripts in
a file and invoke their interpreter explicitly. WSL launchers under `System32`,
`SysWOW64`, `Sysnative` and `WindowsApps` are not treated as Git Bash. Git discovery
also checks ancestor directories for `mingw64/bin` and standard Scoop layouts.

If Bash is needed but unavailable (including a binary disappearing after discovery),
the existing `check_broken` result includes the reason and the full install/rewrite
remedy. Other OS errors retain their existing behavior. It does not classify the work as
`check_failed` or trigger escalation. A command that starts and exits with a test
failure retains the existing verdict. Linux/macOS keep their existing shell path.
Checks selected for Bash that contain backslash paths add a `shell_warning` field:
use forward slashes or quote Windows paths carefully because Bash interprets escapes.

Evidence: **engineering check** with isolated tests and fake agent CLIs; real-agent
evaluation: **not run**.
