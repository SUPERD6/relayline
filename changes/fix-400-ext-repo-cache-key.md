- eval round 2: the clone cache key of a repository is now `owner/name` (case-folded, file-name safe) instead of the
  bare name, so `a/utils` and `b/utils` get separate `--ext-cache` folders (`a__utils.git`, `b__utils.git`) (#400).
  `repo_list` writes `repo` as `owner/name`, and a task id uses the safe key (`r2-a__utils-<sha>`); plain names of
  frozen tasks (`polyglot`, `boltons`) keep their folder. Old and new formats differ (`boltons` vs `mahmoud/boltons`,
  ids with and without the owner), so do not mix an old repos list or cache with the new code: an owner/name
  repository never falls back to an old bare-name clone, and a cache made earlier has to be prepared again (the
  error of `fetch` says so). `cache_key` rejects malformed input (`/utils`, `a/`, `host/o/n`); `holdout_check`
  compares repositories by name (`ext_repo.repo_name`), so `boltons` and `mahmoud/boltons` count as one.
