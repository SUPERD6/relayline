- eval round 2: the clone cache key of a repository is now `owner/name` (case-folded, file-name safe) instead of the
  bare name, so `a/utils` and `b/utils` get separate `--ext-cache` folders (`a__utils.git`, `b__utils.git`) (#400).
  `repo_list` writes `repo` as `owner/name`; plain names of frozen tasks (`polyglot`, `boltons`) keep their folder.
  An owner/name repository never falls back to an old bare-name clone: a cache made by an earlier `prepare` has to
  be prepared again.
