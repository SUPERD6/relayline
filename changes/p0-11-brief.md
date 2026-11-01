- A write run that is clearly a change and has no `--check` gets a shorter Finish text (P0-11 item 2,
  `prompts.SELFCHECK_WRITE`): no answer-only sentence, and no "run the full set once at the end", which contradicted
  "not the whole suite" right after it; −377 characters on such a run. Off: `ccx config set prompt.slim false`.
  `tests/data/b3_golden.json` holds the new text for the three write cases; argv and env are unchanged.
