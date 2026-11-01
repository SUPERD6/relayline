# P0-16 — role assignments / 角色表

EN:
- Project-supplied role checks are displayed with their source, not automatically executed in the host shell;
  effective defaults and templates use only global checks or an explicit CLI `--check`. CLI receipts/notices
  and UI previews label the ignored project check. Fake-CLI process tests cover the CLI and confirmed UI path.
- Opt-in `[roles]` assignments (`agent:model:effort`) with per-project `.ccx/roles.toml` overrides and explicit
  CLI precedence. Shipped roles are empty; existing commands/options and non-role outputs are retained.
- `ccx roles` / `show` / `set` / `unset`, `run/route --role`, fixed-model automatic effort, `other` cross-vendor
  selection with recorded same-vendor/different-model fallback, optional role run defaults and brief templates.
- UI role buttons and read-only `/api/roles`; reuse #233's preview/nonce/confirm, length limits, token/origin
  checks and `via=ui` audit. Configuration/template changes invalidate prepared role commands.
- Persist nullable role metadata, role receipts and conditional report column/totals. Optional role ability
  grouping via `ccx roles --ability` / `/api/ability?by_role=1` reuses #230 without modifying its default cells.
- Document Terra's official model name and prices and Astra's official context window (checked 2026-11-01;
  Codex CLI 0.164.0 help); reference role workflows retain their reported/untested evidence labels. Terra's
  installed accounting price remains unknown if its priors do not include it. No live model evaluation.

中文：
- 项目角色 check 只展示并注明来源，不自动在主机 shell 执行；实际默认值和模板只采用全局 check 或显式 CLI
  `--check`。CLI 收据/提示和 UI 预览说明被忽略的项目来源；用假 CLI 独立进程覆盖命令行与 UI 确认后的路径。
- 新增可选 `[roles]`（agent:model:effort）、项目 `.ccx/roles.toml` 覆盖、显式旗标优先；默认空表，保留既有命令、
  选项和不带角色的输出。
- 增加 `ccx roles` / `show` / `set` / `unset`、`run/route --role`、固定模型自动强度、`other` 跨厂商与同家不同模型
  回退说明、角色默认 mode/worktree/review/check、可选简报模板。
- UI 按角色按钮和只读 `/api/roles`，复用 #233 的预览/nonce/二次确认、长度限制、同源鉴权和 `via=ui`；配置或模板
  改变后要求重新预览。
- 记录可空 role、角色收据、条件追加 report 列与总计；`ccx roles --ability` / `/api/ability?by_role=1` 可按角色
  分组能力证据，沿用 #230，不改原默认能力格。
- 核实 Terra 官方名字、价格和 Astra 上下文（2026-11-01；CLI help 0.164.0），参考角色表逐行注明来源和未测。
  已安装先验未收录 Terra 时，账本价格仍为 unknown；本次没有真实模型评测。

Compatibility / 兼容：No command or option removed. The existing CLI-surface/routing/UI/report tests cover the
unchanged paths; new role tests use fake CLIs and launch the CLI from outside the repository. / 不删命令或选项，
既有 CLI 面、路由、UI 和 report 测试覆盖原路径；角色测试用假 CLI，并从仓库外独立启动 CLI 核对接线。
