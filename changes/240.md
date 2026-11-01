- Quota awareness (P0-17): `ccx quota --refresh`, reading freshness, default 60-minute automatic refresh
  (`quota.auto_refresh_min`, 0/false to disable), and quota-first candidate ordering (`quota.avoid_above = 0.8`,
  `quota.routing = "on"`, `"off" to disable). Unknown/expired readings stay explicit; failures have a cooldown.
  配额感知：刷新与读数新鲜度，默认 60 分钟自动刷新；任一窗口超过 80% 或重置时预测超过 100% 则降序。
  Automatic refresh only probes a vendor that already has a reading which is stale or already reset; a vendor
  with no reading is never probed on its own (`ccx quota --refresh` does it by hand).
  自动刷新只对已有读数且过期（或窗口已重置）的一家探针；从未有读数的一家不自动探，要用 `ccx quota --refresh`。
- Quota stops keep evidence and at most one eligible cross-vendor retry, with the reason/reset in the receipt;
  non-quota errors do not trigger it. Run records keep a `quota_at_start` snapshot; the probe itself writes no run record and no ledger row.
  限额停止记录证据，只向另一家可用候选改派一次；收据显示原因和重置时间，运行记录保留开始配额快照；探针本身不写运行记录、不进账本。
- UI data adds freshness and projected-at-reset fields without changing the page; doctor adds a read-only quota line.
  Probe costs/usage and failures are recorded. Existing commands/options and `--no-fallback` remain supported.
  UI 只增数据字段，页面未改；doctor 增配额摘要。记录探针费用、用量与失败，保留既有命令、选项和回退开关。
  Tested with fake CLIs only; live limit recovery, startup cost and the <$0.005 probe target are not verified.
  仅假 CLI 验证；真实限额恢复、启动费用及单次低于 $0.005 的探针目标尚未验证。
