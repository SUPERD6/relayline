- Fix Windows demo-test cleanup races by joining UI reader/watcher threads and child processes before removing
  the temporary demo. Reuse the test-only CLI child-wait helper; production background defaults are unchanged.
  Failed demo removal still returns a boolean and now reports up to five failed paths on stderr, also included
  in the test fixture's assertion message (#307).
