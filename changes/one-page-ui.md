- `ccx ui`'s home page is now one project on one map (P2-10): the agents and what went between them (runs sent,
  board threads, `ccx discuss` talks; a stopped thread or a message that asks you is a to-do) in the middle; shared
  memory on the left, linked to the runs whose brief carried a note (read from the run's `prompt.md`, never guessed)
  and how they ended; one receipt per run on the right (who to whom, tier and rung, cost, the check's cover and a
  red "basis changed" when the run edited its own tests, the review, the verdict); this week's spend on top, summed
  from the records by rung, other ways only from the published hc1 table; a "who is good at what" table at the
  bottom that says "not enough data yet" until enough work is judged. `#/map/<project>` picks another project. The
  former home page (every to-do and its buttons) moved to `#/all` and stays in the nav; every other page keeps its
  address. `ccx demo` now seeds four shared notes carried by four runs, check covers (one with a changed basis) and a
  discussion, so the map is full; a headless browser test renders it.
