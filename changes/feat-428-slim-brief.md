- Config: `[brief] slim = false` (#428, experimental, effect Unknown, off by default). On, a fresh or continued sub-agent
  run's first message moves two builder paragraphs (how to test through the triggering command, what to do for an
  answer-only task) into `guidance.md` in the run's folder, with a line telling it to read that file first, and the Finish
  text is shorter; the rules, `KEEP_TESTS`, the project-context / memory / shared-note lines, permission, acceptance
  command and receipt format stay in the message. ccx's own reviewer and follow-up resumes are unchanged; if the file
  cannot be written the run gets the full text. The run record gets `brief_slim` / `brief_guidance` (only when the switch
  is on). Off, the text is byte for byte as before (`tests/test_brief_slim.py`). Different from `lead.slim_context`
  (#300, the lead's own context) and `[prompt] slim`. No command or option was removed.
