# 参与贡献

[English](CONTRIBUTING.md) · 中文

谢谢你来帮忙。ccx 刻意保持小巧：Python 3.11+，只用标准库，凡是关于外部命令行工具的说法都对照过那个工具本身。请继续保持。

## 开始之前

- 报 bug、提想法：开一个 issue（有模板）。安全问题请看 [SECURITY.zh.md](SECURITY.zh.md)，不要开公开 issue。
- 改动比较大时，先开 issue 商量好怎么做，再动手写。
- 现在做到哪了、下一步是什么：[docs/STATUS.zh.md](docs/STATUS.zh.md)。设计和理由：[docs/DESIGN.zh.md](docs/DESIGN.zh.md)、[docs/DECISIONS.md](docs/DECISIONS.md)。已知问题、默认关着的开关、怎么跑评测：[docs/maintenance.zh.md](docs/maintenance.zh.md)。

## 准备环境

```bash
git clone https://github.com/SUPERD6/relayline
cd relayline
python -m pip install -e . pytest
python -m pytest -q tests            # 每次提交前都必须全部通过
```

测试从不调用真正的智能体：`tests/fakes/` 里有替身版的 `codex`、`claude` 和 `gemini` 命令行，输出的事件格式和真的一样。CI 在 Linux、Windows、macOS × Python 3.11–3.13 上跑这些测试，还会打出 wheel、装好后运行装好的 `ccx`（`tests/smoke_installed.py`）。

## 规则

- **每个改动都带测试。** 修 bug 要附一个没有这个修复就会失败的测试。
- **路径比较统一经过 `workspace.canonical()`。** 本仓库的代码在比较、打印或将路径存入运行记录前先用它处理；测试期望值也用它构造，不用裸 `tmp_path`。macOS 的 `/var` 是指向 `/private/var` 的符号链接；Windows 有 8.3 短名和 `\\?\` 前缀。CI 在 Linux、Windows 和 macOS 三个平台都跑，不能只依赖本机的路径写法。
- **核心功能不丢。** 不删命令或选项；改到某个命令的 PR 用一行写清保留了什么、怎么验证的。没真跑过的路径在说明处标“实验性”。
- **仓库里不放个人内容**：不放名字、本机路径、邮箱、机器名或数据。个人的东西放在用户自己的 hub 里。每次 push 都会用 `tests/test_repo_hygiene.py` 检查所有跟踪的文件（文本，以及图片里的字符串）；截图还要自己看一眼，画在像素里的路径查不出来。
- **文档两种语言**：`x.md`（英文）和 `x.zh.md`（中文），互相链接。真正的决定写进 `changes/<PR>.decision.md`，发版时折入 `docs/DECISIONS.md`（见 [changes/README.zh.md](changes/README.zh.md)）。仍可直接改 `docs/DECISIONS.md`，但并行 PR 会在这里冲突。
- **每个 PR 一个变更说明**：加一个 `changes/<PR 编号>.md`，写要进 CHANGELOG 的内容，不直接改 `CHANGELOG.md`（见 [changes/README.zh.md](changes/README.zh.md)）；发版时统一合进去，并行的 PR 就不会冲突。`docs/STATUS.md` 由维护者更新。
- **核对外部事实**：依赖的参数、事件字段或价格，都要用 `--help` 或官方文档确认，并写明核对的版本（`ccx/runners.py` 里的 `TESTED_VERSIONS`，[docs/measured.zh.md](docs/measured.zh.md) 的“已核对的外部事实”）。
- **不碰账号凭据**，也不改工具配置里 ccx 标记块以外的地方。
- 小步提交、说明清楚；行为变化写进这个 PR 的变更说明。

## 为另一个智能体命令行加适配器

复制 `ccx/agents/_template.py`（能跑的骨架，带说明）和 `tests/fakes/fake_template.py`；Gemini CLI（`ccx/agents/gemini.py`）是真实的例子。

1. `ccx/agents/<agent>.py`：后台运行的参数（续接和权限参数）和输出的解析（状态、JSON 结果、按 `usage_dict` 四类整理的用量、会话 ID、失败类型），放进一个 `ADAPTER`，`support="community"`，`tested_version` 写你核对过的版本。把名字加进 `ccx/agents/__init__.py` 的 `NAMES`。
2. `ccx/config.py`：把它加进 `DELEGATE_AGENTS`。
3. `config/tiers.toml`：每一档的模型和强度，以及 `[permissions.<agent>]` 的 `read` 和 `write`。
4. `skills/task-routing/data/priors.toml`：档位（模型、强度、能力）和价格，并写明价格的出处。
5. `tests/fakes/fake_<agent>.py`：一个输出和真命令行相同事件的替身，再仿照 `tests/test_adapters.py` 里的 `TestGemini` 写测试。
6. 对真的命令行跑一次，在 PR 里写清楚（版本、跑了什么、得到了什么）。

## 提交 PR

写明改了什么、为什么改、怎么测的，以及没能测到的部分——PR 模板问的就是这些。提交贡献即表示你同意以 [MIT 许可](LICENSE) 发布你的工作，并遵守[行为准则](CODE_OF_CONDUCT.md)。
