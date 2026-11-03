- Isolate detached-launch controls (`CCX_RUN_ID`, `CCX_LEAD_VIEW`, `CCX_DISCUSS_ID`) from acceptance commands,
  sub-agent CLIs (including reviewers), and review Git subprocesses while preserving other environment settings
  and the intentional sub-agent identity. Background logs still contain the full result and lead output is unchanged.
