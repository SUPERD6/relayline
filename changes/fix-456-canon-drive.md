- p4 evaluation clean room (#456): on Windows `canon()` no longer reads a single-letter directory after a drive as
  Git Bash's drive form (`D:/a/x` became `d:a:/x` while `/d/a/x` became `d:/a/x`), so `path_hits` now matches a
  forbidden path under `D:/a/...` in either spelling; a URL such as `http://a/b` is left alone too. Behaviour off
  Windows is unchanged.
