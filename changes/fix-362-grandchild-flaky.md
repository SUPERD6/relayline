- Evaluation clean-up on Windows: closing a unit's Job Object now waits (up to 10 s) on a handle to each of its
  processes until it has really exited, and `after_unit` reports as unkilled exactly those still running; before,
  it slept a fixed 0.5 s and re-listed processes, which under load could miss a still-exiting process or mistake a
  reused pid. The grandchild test checks by handle, not pid. (#362)
