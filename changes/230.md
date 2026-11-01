- Add an advisory ability table by vendor, model and task, with incremental verdict updates, ledger rebuild,
  user prefer/avoid settings and separately sourced hc1/r5/pg1/r4 workflow measurements. Self-checked passes
  remain unverified; fewer than five local runs show insufficient data. Add `ccx ability`, route's read-only
  `ability` field and authenticated `/api/ability`; all existing commands/options and routing decisions stay
  unchanged (CLI surface/help checks and route output comparison). No frontend or routing-policy integration.
  新增按厂商、模型、任务分类的建议性能力表，支持 verdict 增量更新、账本回填、用户偏好和独立列出的公开实测。
  自测通过仍未独立验证，本地不足五条显示数据不足；新增高级命令、route 只读摘要和 UI 数据接口，保留既有命令、
  选项及路由选择（命令表面/帮助检查与 route 输出对照），本次不接入前端或路由策略。
