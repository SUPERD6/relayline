- Join startup maintenance subprocesses in the shared hook-test environment before removing temporary hubs,
  and wait for the archive lock after releasing the deliberately asynchronous archive regression worker.
  Guard the waiting entry-point wiring with a regression test; reap every child after timeouts and report CLI
  and cleanup failures together. Production hooks and non-hook background command behavior are unchanged.
