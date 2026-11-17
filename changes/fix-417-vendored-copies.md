- Evaluation (#417): the round-2 task tools now see copies of a kept package that pip, setuptools and other
  installed packages vendor in `--ext-python` (`_vendor`, `vendor`, `_vendored`, `vendored` folders under
  site-packages, the user site when enabled and ensurepip's bundled wheels, and inside `.whl` files there such as
  virtualenv's embedded pip/setuptools wheels; a wheel's own top-level packages count too). Each top-level package or
  module in such a folder is one copy, named by its folder and by the distributions `*.dist-info` `top_level.txt`
  maps to it; its version comes from `vendor.txt`, `METADATA` or `__version__`. A copy belongs to a task when one of
  its names is the task's project or a top-level package of the parent's tree (root or `src/`). `select`'s
  installed-overlap check compares each commit's new lines with the installed package's files together with these
  copies, also when the package itself is not installed; a copy with an unreadable file makes the commit unknown; an
  excluded commit records the copies (`vendored`) and the rule is in `rule.installed_overlap`. Scan errors that belong
  to no copy (a folder that cannot be listed, a wheel that cannot be read, including `zlib.error`) are cached with
  the scan, never stop or empty the selection, and are listed once in `vendored_scan_errors`. `env-check` (new
  optional `--ext-cache`) lists each task's vendored copies with their release date (`after_commit`,
  `release_unknown`) and `vendored_scan`; the copies do not change `ok`, a failed or incomplete scan does. Read only:
  nothing in the environment is changed.
