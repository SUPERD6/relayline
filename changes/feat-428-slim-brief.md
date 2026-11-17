- Config: `[brief] slim = false` (#428, experimental, effect Unknown, off by default). On, the first message a sub-agent
  gets keeps the task, scope and read / write boundary, acceptance command and receipt format; the optional advice
  goes to `guidance.md` in the run's folder with one line pointing at it (ccx's own reviewer is unchanged). Off, the text
  is byte for byte as before (`tests/test_brief_slim.py`). Different from `lead.slim_context` (#300, the lead's own
  context) and `[prompt] slim`. No command or option was removed.
