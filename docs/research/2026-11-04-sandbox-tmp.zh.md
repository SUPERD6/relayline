# Windows 沙箱临时目录：阶段 1-A

[English](2026-11-04-sandbox-tmp.md)

## 2026-11-04 的实测（measured）

真实命令在本单 Codex 的 shell 中执行：`Windows-10-10.0.26200-SP0`、Python 3.11.9（AMD64）、
PowerShell 5.1。会话声明 `workspace-write`，禁止审批升级。派发说明称 Windows 后端为 `unelevated`；
没有独立检查后端、账户或 ACL，也没有检查工具 home 或凭据目录。默认系统 Temp 在本会话可写；
续接后即使声明的可写根只列工作目录，复测仍通过。这个结果只说明本次环境，不能推广到所有沙箱。

临时测试文件有两个测试：第一个通过 pytest 的 `tmp_path` 写入并读回文件；第二个在
`os.environ['TMP']` 下直接创建 UUID 目录，写入、读回文件，并在 `finally` 清理。
每种情况分别启动新进程，执行 `python -m pytest -q -s -p no:cacheprovider <test_tiny.py>`，
关闭第三方插件自动加载。工作目录外、目录内两种情况同时设置 TMP/TEMP/TMPDIR；默认情况保留继承值。
默认 TMP、TEMP 是系统 Temp；首轮 TMPDIR 也是系统 Temp，续接复测时 TMPDIR 未设置。
下表路径已脱敏；临时测试文件及其创建的目录均已清理。

| TMP 情况 | pytest 退出码 | 实际结果 |
|---|---:|---|
| 继承的系统 Temp | 0 | 2 passed；fixture 和显式目录读写都通过 |
| 工作目录外、已有的父目录 | 1 | 1 passed, 1 failed；fixture 回退到系统 Temp，显式 mkdir 被拒 |
| 本工作目录内的独立目录 | 0 | 2 passed；两种临时文件都在指定目录内 |

目录外情况的真实错误（只替换个人路径和 UUID）：

```text
>       d.mkdir()
E       PermissionError: [WinError 5] Access is denied: '<workspace-parent>\\phase1a-<uuid>'
FAILED .phase1a-measure/test_tiny.py::test_explicit_tmp - PermissionError: [W...
1 failed, 1 passed in 0.17s
```

此前用 `tempfile.TemporaryDirectory(dir=TMP)` 的版本在目录外情况超过 30 秒后被超时终止；
当时 `tmp_path` 已回退到系统 Temp 并通过。最初开启插件自动加载的一轮没有产出结果，已中断。
这两次都不算通过。实测证明了目录外访问被拒，也说明回退可能掩盖这个问题；hc2 历史错误的
具体操作与路径缺失，不能据此认定每个历史 WinError 5 的归属。

## 候选实现：工程检查（engineering check）

`preflight.py`、`r5.py run` 和 `batch.py run` 新增 `--codex-workspace-tmp`，实验性，**默认关闭**。
只在评测环境中把 `CCX_CODEX_BIN` 指向小型启动器。明确使用 `workspace-write` 时，启动器在
该次子任务实际 cwd 下建立独立的 `.ccx-eval-tmp-*`，把相同的绝对路径作为 TMP/TEMP/TMPDIR 传给
原 CLI。首次执行与 resume 使用同一机制；独立 worktree 使用自己的目录。只读与非执行类调用
保持继承的环境。不新增沙箱权限，不改用户配置，其他 CLI 仍用原来的 `x-*/tmp`。

评测仓库本地 Git `info/exclude` 忽略这些目录，linked worktree 也适用；不改被跟踪的忽略文件。
正常退出由启动器清理；中断残留由 postflight 清理，linked worktree 仍走既有整体清理。
报告和评测行 fingerprint 新增 `tmp_policy`（`unit-x` / `codex-workspace-private`；旧报告缺失时为 null）。
沙箱模式复用已有 `fingerprint.codex_windows_sandbox` 和 daily 相关字段。

Codex canary 改为执行一个小 Python 文件，同时要求原有算术结果和临时目录创建、写入、读回、
删除的成功标记。临时变量不一致、回退到别的根、缺少标记或命令非零退出都会让预检失败，
在单元开跑前拦截。保留已有 `--force-unclean` 显式强制运行和 `--no-canary` 跳过行为。

默认用户 Temp 的真实探测通过，因此没有改 `ccx/agents/codex.py`、`ccx/delegate.py` 或 `ccx doctor`。
这是评测候选实现；尚未实测完整 hc2 修复，也没有改产品默认值。

## 原始事件留存

r5 每个单元在清理 hub 前，保留已有的主导 JSONL 和 ccx 子智能体的
`events.<attempt>.log`、`stderr.<attempt>.log`，涵盖成功、隐藏测试失败和异常路径。
正常运行写到 `<results-stem>-artifacts/<invocation>/<tag>-<unit>/streams/`；新增 `row.streams`
记录相对文件名、字节数、SHA-256、invocation 和 `redacted=true`。没有 artifacts 目录的库调用
仍以旧 streams 根作为后备位置。保留事件顺序、结构及完整内容，不套 diff 产物的截断上限；
脱敏后不是逐字节原件。

只复制明确列出的日志文件，不复制凭据、配置、会话文件或符号链接。屏蔽已知凭据环境值、
凭据字段及赋值、常见 token 格式和已知本机路径；保留 WinError 5 等错误文字及其事件、run、attempt
关联。这不能补回历史缺失流，也不会复制工具原生孙智能体另存的会话文件。

## 验证范围

假 CLI 覆盖三个变量相同、位于当前子任务 cwd 内、每次调用目录独立、首次执行与 resume、
有无 linked worktree、Git 状态干净、只读行为不变，以及 canary 成功、缺失、拒绝三种情况。
事件流测试覆盖三类结果路径、多个 attempt、脱敏、顺序和哈希。另从仓库外启动 preflight 子进程，
验证选项确实接到报告。

最终五个相关文件 `test_eval_preflight.py`、`test_eval_sandbox_tmp.py`、`test_eval_streams.py`、
`test_eval_r5.py`、`test_eval_batch.py` 合计 **165 passed, 1 skipped, 2 deselected**，关闭插件自动加载。
排除的是下述两项进程观测测试。最后一轮定向检查另有 25 项通过。AST 对比确认原有 71 个 preflight
测试函数/类完全未改。按本单要求没有运行全仓测试，由统筹负责。
收尾审阅把事件留存失败限定为新增诊断字段，保留原有 audit 和评分含义；随后 67 项 stream/r5
测试全过，包含产物写入失败后继续清理的情况。脱敏实测数据在本地
`.ccx/reports/optimize-20261104/phase1a-measured.json`，不提交到仓库。

两项既有进程测试在本沙箱内无法用枚举或 `alive()` 看见自己启动的脱离进程。
原版 HEAD 实现也复现了相同现象：snapshot 没列出子进程，Job Object 列出的子进程却得到
`alive=false`。保留其原断言，须由统筹在沙箱外重跑。未运行 Linux/macOS、付费的真实 Codex
完整评测；这里没有正确率、成本改善、CI 通过或可发版的结论。
