- Add API-equivalent USD and configurable subscription quota units side by side in the ledger, usage summaries,
  report and UI data. Default API report presentation is unchanged; subscription reports put quota units first.
  Legacy rows infer unweighted units from tokens without rewriting history.
  Switch with `ccx config set billing.mode subscription`; stats and lead breakdown put the selected basis first
  and retain existing dollar fields.
  中：账本、用量汇总、报表与 UI 数据增加订阅配额单位，保留 API 等价美元；默认 API 报表呈现不变，订阅报表优先展示配额。
  旧记录按未加权 token 补算且不重写历史；支持 CLI 切换模式，stats 和 lead breakdown 优先展示所选口径并保留美元字段。
