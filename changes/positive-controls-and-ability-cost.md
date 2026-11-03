- Pair real Claude quota-refusal replays with successful controls through the same fake CLI and run entry point,
  covering UTF-8 and legacy console encoding; preserve classification and exactly-one-fallback assertions.
- Keep successful-run cost medians and add all-observation known spend, right counts, missing-cost counts and
  spend per success, separated by cost basis; backfill existing cached cells and expose the fields through ability JSON.
  Include recorded costs of stopped, partial and running work in existing cells without changing ability evidence counts.
- Explain both cost metrics in ability output and bilingual feature docs: the final model bears the recorded cost
  of the entire attempt chain, which describes the workflow rather than intrinsic model ability. Routing is unchanged.
