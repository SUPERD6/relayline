# 无凭据的新手走查 — 2026-11-05

[English](2026-11-05-walkthrough.md) · 中文

证据等级：**engineering check**。对象是 relayline 0.6.0 当前工作树，环境为 Windows、Python 3.11。没有使用真实智能体 CLI、模型、账号或凭据。这是一次脚本走查，不是用户研究或性能对比。

## 复现方法

在任意目录运行 `python <checkout>/scripts/walkthrough.py`。脚本新建并保留一个临时目录，打印位置，把 `result.json`、`logs/*.stdout.txt`、`logs/*.stderr.txt`、假 CLI 调用记录和 HTML 页面放进去。脚本只用标准库（包括 `venv`）；可编辑安装的构建步骤需要 setuptools >=77 和 wheel。

离线安装：`python <checkout>/scripts/walkthrough.py --wheelhouse <构建依赖wheel目录>`。明确允许访问公共 PyPI 时：`python <checkout>/scripts/walkthrough.py --allow-download`。默认不联网。构建依赖是否齐备与 relayline 没有运行时依赖是两回事。

所有 ccx 子进程都从仓库外的新临时工作目录运行。HOME、USERPROFILE、CCX_HUB、CCX_CONFIG、工具目录、应用数据和临时目录都指向新目录。环境采用白名单，不继承凭据、CLI 覆盖、主导身份和 Python/pip 配置。PATH 只有私有假 CLI 启动器和临时 venv；自动寻找桌面应用已关闭。只复制明确列出的打包输入，不遍历仓库本地状态。原始检出、真实工具目录和 hub 不用作运行状态。

## 观察结果

| 步骤 | 结果 | 摩擦与证据限制 |
|---|---|---|
| 新建 venv | Pass | 成功创建隔离 Python 环境。 |
| `pip install -e` | Fail | 沙箱禁止下载构建依赖，报 WinError 10013。离线重试也缺 setuptools >=77，没有可用构建 wheel 缓存。安装后运行情况为 **Unknown**。 |
| 管道输入运行 `ccx setup` | 源码回退下 Pass | 显示计划和 `Nothing was changed.`，没有创建用户配置。期待直接装好的人可能没注意这是预览。 |
| `ccx setup --yes` | 源码回退下 Pass | 创建隔离 hub、接线，跑过两家假 CLI 自测。真实安装中 `--yes` 也会同意付费自测；本脚本只能找到假工具。客户端信任 hook 仍需本人操作。 |
| `ccx doctor` | 源码回退下 Pass | 假版本与登录探测正常。Codex 假版本 0.163 与适配器验证版本 0.164 不同，产生版本警告；订阅额度仍为 Unknown。登录成功是模拟结果。 |
| `ccx demo --no-open --export ...` | 源码回退下 Pass | 生成有示例数据的静态页面，不开浏览器或服务。私有 PATH 特意不提供 Git，未验证依赖 Git 的 demo 快照。 |
| `ccx ui --no-open --export ...` | 源码回退下 Pass | 根据隔离 hub 生成静态页面。没有验证实时服务、按钮和浏览器外观。 |
| README 第一次派活及 `ccx show` | 源码回退下 Pass | 原样只读任务经 PATH 假 CLI 派出，可查看完成收据。假 CLI 没有真正总结 README，不能证明回答质量。 |

前两次开发尝试还暴露了走查脚本漏复制假 CLI 辅助模块的问题，已补齐现有辅助模块。这是脚本缺陷，不是 relayline 产品缺陷。失败产物仍保留，没有计成安装成功。

## 小修复与回归检查

setup 显示第一次任务前，现在明确要求从包含 README.md 的项目目录运行；还提示先用 `ccx show <run_id>` 看结果，并同时给出 `--ok 1 (correct)` 与 `--ok 0 (wrong)`。原提示没有说明目录前提，只展示正向验收命令。

`tests/test_walkthrough.py` 检查环境隔离，从仓库外通过独立进程运行真实脚本，检查页面生成和假派活，并通过 setup CLI 检查新提示。即使源码检查通过，脚本也保留安装失败；setup/doctor 输出 FAIL 时，不会仅凭退出码为零算通过。另跑相关 setup 回归，保留原有行为。最终命令：`python -m pytest -q tests/test_walkthrough.py tests/test_firstrun.py -k 'walkthrough or SetupFirstRun' -x`，**7 项通过、34 项未选中**，进程退出码为 0。没有跑全量。没有移除命令或选项，没有改变默认值、现有 JSON 含义和退出码约定。

## 大项与未验证范围

有构建 wheel 时的安装后运行、真实 pipx 与 Claude marketplace 插件安装、真实登录、hook 执行与信任、真实模型结果、实时 UI 交互、Linux/macOS 均为 **Unknown / not run**。README 后续日期解析示例需要已有项目和测试文件，属于示例，不能在空目录直接照抄。本单没有扩大范围处理这些项。

安装失败时脚本仍返回非零，即使后续源码检查通过。应看逐步记录，不把总结果当产品质量分数。本报告不能证明更快、更省或更准。
