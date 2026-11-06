# Experimental brief checks

[中文](brief-check.zh.md)

Before `ccx run` starts an agent (including `--bg`), a cheap static check warns about
clear contradictions: read mode with an imperative to edit files or create a PR,
a missing local input explicitly requested with `Read`, `Inspect` or `Open`, and
obviously incompatible native-platform syntax in `--check` or `Run `-style inline
commands. Chinese input-reading and file-editing imperatives are also recognized.
No model, network request, command execution or file-content read is needed.

By default warnings go to stderr and an additive `brief_warnings` array in the
receipt and saved run record (`ccx show`), including the initial background receipt.
The detached child retains the diagnostic without printing the parent's warning again.
They do not change routing, permissions, verdicts or exit codes. No existing command
or option is removed. Blocking is **off by default**: opt in with `--strict-brief`.
With any warning, strict mode prints a refusal receipt (`delegated: false`), exits 2,
and starts neither an agent nor a background process. With no warning it runs normally.
There is no new configuration key.

Checks use the resolved mode, the original brief and the target `--cwd`, before
project, role and shared-context text is attached. This is a conservative heuristic,
not a validator: unrecognized wording and commands are Unknown. Proposed output
paths need not exist. Advice about editing, negated instructions, optional inputs,
URLs, globs, placeholders, foreign absolute paths, tool-private paths, fenced code
and block quotes are skipped (including real instructions placed inside examples).
Input paths stop at full-width punctuation. Bare names without a directory separator
require a common file extension (such as `.py`, `.md`, `.json` or `.txt`); dotted API
names and version numbers are not treated as files. Report-file requests such as
`Write the report to out.md` or `写一个报告文件` conflict with read mode; prose-only
report requests and negated writing instructions do not.
Explicit `bash`, `wsl`, `powershell` or `pwsh` wrappers are not second-guessed;
installed utilities and shell versions are not inferred. Windows checks use the
native command shell, so `&&` alone is not a platform mismatch.

Evidence: engineering checks using fake CLIs only. Real-agent effectiveness and
false-positive rates on real briefs are **Unknown**.
