- Add conservative experimental pre-dispatch brief warnings to stderr, receipts and run records, including background runs.
  Keep dispatch advisory by default; opt-in `ccx run --strict-brief` refuses clear mode, input-path or platform conflicts
  before launching an agent. Preserve existing commands, options, verdicts and default exit codes.
  Handle Chinese punctuation and report-file requests conservatively, distinguish common file extensions from dotted
  API names or versions, and avoid duplicate background warnings while preserving saved diagnostics and stdin briefs.
