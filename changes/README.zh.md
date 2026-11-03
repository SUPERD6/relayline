# changes/

[English](README.md) · 中文

每个 PR 加一个文件，不直接改 `CHANGELOG.md`：这样并行的 PR 不会在 CHANGELOG 上互相冲突。

- 文件名用 `changes/<PR 编号>.md`（如 `changes/21.md`）。PR 还没有编号时先用分支名（`changes/fix-site-out.md`），
  开了 PR 再改名，不改也行：合并时先按编号排，其余按文件名排。
- 内容就是它在 `## Unreleased` 下面的样子：一条或几条 `- ` 开头的条目，续行缩进两个空格，每行约 120 列。和
  CHANGELOG 其他部分一样用英文。
- 功能 PR 不改 `CHANGELOG.md` 和 `docs/STATUS.md`。STATUS 只由主会话（统筹）更新；发版时由主会话把这些文件合进 CHANGELOG：

```bash
python scripts/collect_changes.py --check                                  # 检查两类记事的格式（测试里也会跑）
python scripts/collect_changes.py                                          # 预览更新后的文档
python scripts/collect_changes.py --version 0.5.0 --title "..." --apply    # 写入两份文档，删掉已折入的文件
```

## 决策行

有取舍的决定，除 CHANGELOG 记事外，再加一个 `changes/<PR 编号>.decision.md`。PR 还没有编号时先用分支名
（如 `changes/fix-site-out.decision.md`），开了 PR 再改名，不改也行。内容是一行或几行
[docs/DECISIONS.md](../docs/DECISIONS.md) 的表格行，不带表头和分隔行：

```markdown
| 2026-11-03 | Use per-PR decision notes | 按 PR 记录决策 | Avoid parallel conflicts / 避免并行冲突 | `changes/` |
```

每个物理行以 `|` 开头和结尾，恰好五个单元格：日期（`YYYY-MM-DD`）、英文决定、中文决定、原因、位置。
单元格内不能直接换行，需要时用 `<br>`；字面的竖线写成 `\|`。文件不能为空。`--check` 同时检查两类记事，
决策行有错时报告文件名和行号。

存在决策记事时，默认预览也会打印折入后的决策记录。`--apply` 把新行插到表格分隔行后，并删除已折入的文件；
`--version` 发版时也一并折入。行按日期倒序、同日按 PR 编号倒序；同日未编号文件排在编号文件后，按分支名排序。
同一文件中日期相同的行保留原顺序。决策记事不会进入 CHANGELOG。仍可直接改 `docs/DECISIONS.md`，但并行 PR 会在这里冲突。
