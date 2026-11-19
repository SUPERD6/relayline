- strength_retest: the logged-in homes every unit shares keep earlier units' session records (Codex `sessions/`,
  `archived_sessions/`, `history.jsonl`, `memories/`, `*.sqlite`; Claude `projects/<slug>/`, `file-history/`,
  `todos/` ...), whose prompts and tool results hold an on or mem arm's answer. The audit masked the whole home as the
  unit's own; now any part that is not the unit's own (its Claude project folders, its own Codex rollouts) is a
  path-audit hit for every unit, and Claude units get Read deny rules on them (transcripts, record folders, the run's
  earlier units' project folders as a few globs). A Claude unit whose settings would exceed 30,000 characters is
  refused before its CLI starts. (#470)
