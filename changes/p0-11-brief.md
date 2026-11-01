- A run given `--mode write` and no `--check` no longer gets the Finish text's answer-only sentence (P0-11 item 2,
  `prompts.SELFCHECK_WRITE`, 315 characters less); an inferred or default write mode, read runs and `--check` runs
  are unchanged. Experimental: not measured on a real sub-agent. Off: `ccx config set prompt.slim false`.
