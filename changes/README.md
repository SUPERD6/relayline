# changes/

English · [中文](README.zh.md)

One file per pull request, instead of editing `CHANGELOG.md`: parallel PRs then never conflict on it.

- Name it `changes/<PR number>.md` (e.g. `changes/21.md`). Before the PR has a number, use the branch name
  (`changes/fix-site-out.md`) and rename it once the PR is open, or leave it — numbered notes are folded first,
  the rest by name.
- Write the lines as they would appear under `## Unreleased`: one or more `- ` bullets, continuation lines indented
  two spaces, wrapped at about 120 columns. English, like the rest of the CHANGELOG.
- Don't edit `CHANGELOG.md` or `docs/STATUS.md` in a feature PR. The lead (coordinating) session updates STATUS, and
  folds the notes into the CHANGELOG when releasing:

```bash
python scripts/collect_changes.py --check                                  # check both note formats (also in tests)
python scripts/collect_changes.py                                          # preview the updated documents
python scripts/collect_changes.py --version 0.5.0 --title "..." --apply    # write both documents, delete the notes
```

## Decision rows

For a decision with a tradeoff, add `changes/<PR number>.decision.md` alongside the CHANGELOG note. Before the PR
has a number, use the branch name (e.g. `changes/fix-site-out.decision.md`); rename it when the PR is open, or leave it.
Write one or more rows exactly as in [docs/DECISIONS.md](../docs/DECISIONS.md), without the header or separator:

```markdown
| 2026-11-03 | Use per-PR decision notes | 按 PR 记录决策 | Avoid parallel conflicts / 避免并行冲突 | `changes/` |
```

Each physical line starts and ends with `|` and has exactly five cells: date (`YYYY-MM-DD`), decision (English),
decision (Chinese), why, and where. No bare newlines inside cells; use `<br>` if needed, and escape literal pipes as
`\|`. The file must not be empty. `--check` validates both note types and reports the file and line for bad rows.

The default preview also prints the updated decision log when decision notes exist. `--apply` inserts their rows
just below its table separator and deletes the folded files; `--version` folds them in alongside the release notes.
Rows sort by descending date, then descending numeric PR number; unnumbered notes follow numbered notes on the
same date, alphabetically by branch name. Rows from the same file and date keep their original order. Decision notes
never enter the CHANGELOG. Direct edits to `docs/DECISIONS.md` are still allowed, but parallel PRs can conflict there.
