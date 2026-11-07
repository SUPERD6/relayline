- Add `CCX_NO_START_ARCHIVE=1` to skip session-start archive scheduling and worker launch; keep startup defaults
  unchanged and preserve `CCX_NO_AUTO_ARCHIVE=1` as an after-run-only opt-out. Document both switches and existing
  archive configuration alternatives, with regressions through external session-start hooks (#306).
