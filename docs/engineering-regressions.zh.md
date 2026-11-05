# 工程回归覆盖

[English](engineering-regressions.md)

证据等级：**engineering check**，只用假 CLI。没有调用真实智能体，
没有测量性能，也没有验证其他操作系统。

四项回归测试覆盖下述路径。测试审查已收到保存的原话，原话传递测试
已移除预期失败标记，作为普通回归测试通过。

`tests/test_engineering_regressions.py` 新增：

- 同一委派同时传入两个原始输入文件：原任务进入测试审查和修复后的再次审查；
  两次实施调用都保留原话及 `source=file`。显式 resume 可替换原任务，原话仍使用旧快照。
- 从仓库外目录启动独立进程，串起
  `run -> show -> verify -> resume -> stop -> undo -> ui --export`。
  停止已完成运行保持原有退出码 2；undo 恢复整条会话链开始前的内容。
  正在运行时的停止已有
  `tests/test_preflight_e2e.py::TestPreflightSteps::test_stop_then_resume` 覆盖。
- `mem delta` 钩子启动真实后台归档进程，通过 socket 信号阻塞实际归档。
  钩子先退出，此时没有归档日志或 CLI 调用；释放信号后检查真实归档日志和假 CLI 调用完成。
  用因果顺序验证延迟，不用机器速度门槛或 sleep。

已覆盖部分不重复：`tests/test_ccx.py` 的 memory CLI 测试、
`tests/test_board.py::TestBoard::test_to_all_and_reply`、
`tests/test_projects.py::test_where_command`，以及 `tests/test_user_words.py`
中的重试、resume 和跨厂商回退。所有命令和选项均保留。

## 已修复：测试审查收到原话

回归测试命令：

```console
python -m pytest -q tests/test_engineering_regressions.py -k user_words_file_reaches
```

此前，实施者收到 `--user-words-file` 时，测试审查者可能只收到改写简报。
现在测试审查通过 `ccx/review_task.py` 同时提供保存的 `user-words.md`、
原话来源信息和分配的任务。回归测试检查独立审查者收到原话，
且运行记录保留 `source=file`。这些结果只证明假 CLI 的接线行为。
