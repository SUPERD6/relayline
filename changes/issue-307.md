- Fix Windows demo-test cleanup races by joining UI reader/watcher threads and child processes before removing
  the temporary demo. Reuse the test-only CLI child-wait helper; production background defaults are unchanged.
  Failed demo removal still returns a boolean and now reports up to five failed paths on stderr, also included
  in the test fixture's assertion message (#307).
  The original parallel full-suite failure was not reproduced, so its occupying process remains unconfirmed.
  This covers UI reader/watcher threads and direct child processes, including the demo-backed map tests; it does
  not join grandchildren spawned by a UI-started ccx process. If cleanup fails again, inspect the failed paths
  printed by `demo.remove`.
