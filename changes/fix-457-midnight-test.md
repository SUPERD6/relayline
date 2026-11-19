- Fix a flaky test: `test_context_share::test_claude_events_and_summary` failed within an hour of midnight, because
  its events were built relative to the real clock and the summary then added a date prefix. The test now pins the
  clock, and a new test covers the just-after-midnight case. No product code changed.
