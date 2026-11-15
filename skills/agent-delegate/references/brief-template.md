# Brief template (aim for ≤ 200 words besides the person's quoted request)

```
Request (verbatim): <the person's own words: interfaces, names, exact strings, numbers unchanged>
Look at: <paths you already know; the sub-agent finds and reads the rest itself>
Constraints: <don't touch X; keep API Y; don't commit (the lead commits); paths: follow the target project's path conventions>
Done when: <the acceptance command, e.g. `pytest tests/test_io.py -q` passes, including a test of the new requirement that fails today>
```

For a task that adds or fixes behaviour, the acceptance command should fail before the change: write at least one
test (or a checkable command) for the new requirement yourself, see it fail, commit it, and give concrete inputs
and expected outputs in the brief. The existing suite already passes, so it cannot tell whether the new requirement
was met. (A refactor that keeps behaviour is the exception: its check passes before and after.)

Only for work in the relayline (ccx) repository itself, add
`paths: compare and assert through workspace.canonical()` to Constraints. Other projects use their own path conventions.

Good
```
Request (verbatim): "make load_csv() accept a `delimiter` argument, default ','"
Example (the lead's, from its new test): load_csv("a;b\n1;2\n", delimiter=";") returns [{"a": "1", "b": "2"}]; without delimiter, "," is used.
Look at: src/io/loader.py, tests/test_loader.py
Constraints: no new dependencies; keep the public signature otherwise unchanged; don't touch test_semicolon; don't commit.
Done when: `pytest tests/test_loader.py -q` passes, including test_semicolon (written by the lead; it fails today).
```
Pass the same command as `--check` so ccx runs it again.

Bad (wastes tokens both ways, or changes the task)
- re-wording the person's interface or numbers in your own words ("the first match" → "the earliest position")
- reading the code base yourself first to write a long brief (the sub-agent reads it on the cheaper model)
- pasting whole files or the chat history into the brief
- "fix everything that looks wrong" (no boundary → long, expensive run)
- asking the sub-agent to commit (Codex's sandbox blocks `.git` writes)
- asserting a raw tmp path against one the code resolved (in the relayline (ccx) repository itself, construct
  expectations through `workspace.canonical()`; elsewhere, use that project's path conventions)
- re-explaining project background that belongs in `.ccx/context.md` (reuse it; update it only when context
  maintenance is part of the authorized task)
