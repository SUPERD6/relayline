# Original user wording (experimental)

English · [中文](user-words.zh.md) · [Features](features.md)

Evidence: **engineering check** only. Whether this improves delegated correctness is **Unknown**.
This feature is off by default. No existing command or option is removed, and existing exit codes,
receipt meanings and verdict rules stay the same.

```sh
ccx config set delegate.user_words true
ccx config set delegate.user_words_max_chars 8000
ccx run --user-words-file request.txt --mode write "Implement the requested interface"
```

`--user-words-file PATH` explicitly opts in for that run, regardless of `delegate.user_words`.
It takes a UTF-8 file and has priority over automatic capture. Relative paths are resolved from the
directory where `ccx run` is invoked, including background runs. An unavailable or unreadable source
adds no section and does not fail the delegation.

With `delegate.user_words = true` and a Claude Code lead, ccx reads the latest real user message from
the lead conversation, using the existing transcript locator. A known lead session ID wins; otherwise
the locator selects a recent main session in the task project, excluding known ccx child sessions.
No eligible conversation means no section. Other lead tools require the explicit file option.
The lead writes its brief as before; no skill change is required.

The new “User's original words / 用户原话” section tells the sub-agent to prefer the original interface
requirements when the brief conflicts and put uncertainty in `open_questions`. It is task data,
not a grant of additional permissions or a wider task scope. Hook/meta/system-reminder messages,
tool results and ccx-injected messages are skipped. `<pasted_content>` blocks are removed and known
credential patterns use the existing transcript redactor. Other wording, whitespace and markup are
preserved; this is a heuristic filter, not a guarantee that all private information is detected.

`delegate.user_words_max_chars` defaults to 8000 retained characters after filtering. Nonpositive values
use a one-character minimum. Longer text is cut at the cap with an explicit truncation notice.
The sanitized, capped section is saved as `user-words.md` beside the run's existing `prompt.md`.
Retries, escalations, fallback and `ccx resume` reuse that snapshot even if the source or configuration
changes. A new task continued in an old session captures its own wording. A missing resume snapshot
adds no section and never reads a new source.

`run.json` adds `user_words: {"source": "file" | "claude" | null, "chars": N}`. `chars` counts the
retained wording, excluding the section instructions and truncation notice. No original text or
source file path is added to the accounting ledger. The prompt and snapshot still contain task data
and follow the existing run-artifact retention rules.

For evaluation, `scripts/eval/r5.py run --arms ccx2,ccx2uw ...` opts into a comparison. `ccx2uw` uses
exactly ccx2's lead text, flags and isolation, enabling only `delegate.user_words` in the unit hub and
asserting the effective config before launch. The lead's task message supplies the original wording.
Rows record `user_words_mode`; this is the configured mode, not evidence that a transcript was found
or that correctness improved. Inspect each builder's `run.json` for actual capture metadata.
