- Fix model-capacity errors retrying the same model at another effort: use the remaining ladder or existing
  cross-vendor fallback, with at most two switches and explicit capacity evidence/reasons in receipts.
  This bug fix is enabled by default; `defaults.capacity_fallback=false` restores legacy behavior.
  Preserve commands, options, exit codes, quota handling and budget checks; fake-CLI engineering checks only.
- Use only the final CLI error for capacity evidence, preserve higher-priority failure verdicts and resume context,
  mark tier upgrades in recovery receipts, and exclude capacity stops from session reuse, merged repair and wrong-task UI counts.
- Restore capacity-stopped queue pieces to decide, show capacity-specific UI recovery hints, and build continued-run memory prompts only when switching models.
