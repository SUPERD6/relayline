- Docs: the agent-delegate skill (`SKILL.md`, `README.zh.md`) now says `--worktree` / `ccx q run` start from the local
  HEAD by default, and from `@{upstream}` with `base = "upstream"` / `--base upstream` (push the test first or use
  `--base head`); the `base` result field is described the same way. The sensitivity note says the clean tree is
  the one the dispatch runs in (the new worktree for `--worktree`). Fixes #351.
