# Brief template (aim for ≤ 200 words besides the person's quoted request)

```
Request (verbatim): <the person's own words: interfaces, names, exact strings, numbers unchanged>
Look at: <paths you already know; the sub-agent finds and reads the rest itself>
Constraints: <don't touch X; keep API Y; don't commit (the lead commits); paths: compare and assert through workspace.canonical()>
Done when: <the acceptance command, e.g. `pytest tests/test_io.py -q` passes>
```

The `workspace.canonical()` constraint is for work in this repository; for other projects, use their path conventions.

Good
```
Request (verbatim): "make load_csv() accept a `delimiter` argument, default ','"
Look at: src/io/loader.py, tests/test_loader.py
Constraints: no new dependencies; keep the public signature otherwise unchanged; don't commit.
Done when: a new test for ";" passes with `pytest tests/test_loader.py -q`.
```
Pass the same command as `--check` so ccx runs it again.

Bad (wastes tokens both ways, or changes the task)
- re-wording the person's interface or numbers in your own words ("the first match" → "the earliest position")
- reading the code base yourself first to write a long brief (the sub-agent reads it on the cheaper model)
- pasting whole files or the chat history into the brief
- "fix everything that looks wrong" (no boundary → long, expensive run)
- asking the sub-agent to commit (Codex's sandbox blocks `.git` writes)
- asserting a raw tmp path against one the code resolved
- re-explaining project background that belongs in `.ccx/context.md` (reuse it; update it only when context
  maintenance is part of the authorized task)
