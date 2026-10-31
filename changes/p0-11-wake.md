- `ccx run --bg` / `ccx resume --bg` (no `--wait`) now tell the lead when the run is done, in one line, instead of the
  lead polling (P0-11 item 1, `ccx/wake.py`): into Claude Code's own inbox (cross-session messaging; tried for real on
  Claude Code 2.1.309, native Windows desktop app), else on the lead's next turn through the `ccx turn` hook (Codex:
  fakes only, experimental). Nothing is sent while a lead waits on the run (`--bg --wait N`, `ccx show --wait`);
  polling stays. Off: `ccx config set wake.enabled false` (`[wake]` in tiers.toml).
