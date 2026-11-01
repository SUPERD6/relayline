- Add `worktree.location = "sibling" | "inside"` and `ccx config set worktree.location inside` for new worktrees
  within `<repo>/.ccx/worktrees/<run_id>`. The default sibling layout and agent arguments remain unchanged;
  inside warns when Git does not ignore `.ccx/`, without editing `.gitignore`. `ccx doctor` explains the selection.
  Both layouts are recognized in results, queue tracking/acceptance, lane commits, automatic merging, check-trust
  grouping and UI project grouping, even after the setting changes. Inside is experimental (fake-CLI and Git
  checks only; real agent CLIs and Codex project trust inheritance have not been checked).
- 新增 `worktree.location = "sibling" | "inside"`，可用 `ccx config set worktree.location inside` 把新工作树放入
  `<repo>/.ccx/worktrees/<run_id>`。默认 sibling 布局和智能体调用参数不变；Git 未忽略 `.ccx/` 时先警告，不自动改
  `.gitignore`。`ccx doctor` 显示并解释位置设置。结果、队列跟踪与接收、lane 提交、自动合并、验收可信度分组和 UI
  项目归类同时识别两种布局，改设置后仍识别已有运行。inside 暂为实验性（仅假 CLI 和 Git 验证，未验证真实智能体 CLI
  或 Codex 项目信任继承）。
