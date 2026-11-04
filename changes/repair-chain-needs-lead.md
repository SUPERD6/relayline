- Mark repair chains whose independent re-review did not run or returned an unclear verdict with an explicit
  `needs_lead` cue: distinguish completed fixes from attempted fixes by their reported status, preserve existing
  cue prefixes and cap the combined cue at 300 characters. Only unclear verdicts add a recap note; reviews that
  did not run retain the existing note. Exit codes, `ok`, reviewer selection, merge gates and `must_needs_repro`
  behavior are unchanged; ordinary receipts are unchanged.
