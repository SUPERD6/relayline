- Add experimental `routing.default = auto | self_first` (default `auto`): prefer self unless lead quota is
  tight, context is large, delegation is explicitly assigned, or independent parallel work is declared.
  Preserve existing policies, commands, options and verdicts; expose condition evidence in routing receipts.
  Fixed-model role assignments qualify explicitly; internal sizing overrides do not report a user `--force`.
  Use a separate `--independent-parts` signal for task parallelism; keep `--parallel` for child sub-agents.
  Expose missing quota windows and reuse context only from explicit input or lead-session readings.
  Recognize user force only through a positive CLI marker; queue pieces report explicit requests from queue.
  Audit all five internal routing force sites and cover each without misreporting a user override.
