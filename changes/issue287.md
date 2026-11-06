- Add experimental `lead.slim_context` (off by default): render two-line ccx entry guidance and load startup
  context on demand with `ccx mem delta --as <tool> --full`; keep commands and skills available.
  Managed-mode startup hooks avoid duplicate entry text; external-mode hooks expand both executable paths.
  Retain quiet startup maintenance, background board synchronization, human-turn tracking and short completion
  notices. Hidden context stays unread. Client-managed skill descriptions remain in the skill list.
  The legacy `ccx lead --hint` hook is intentionally quiet while the switch is on.
