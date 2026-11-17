- Evaluation (#417): the round-2 task tools now see copies of a kept package that pip, setuptools and other
  installed packages vendor in `--ext-python` (`_vendor`, `vendor`, `_vendored`, `vendored` folders in
  site-packages, and inside `.whl` files there such as virtualenv's embedded pip/setuptools wheels). Each top-level
  package or module in such a folder is one copy, named by its folder and by the distributions `vendor.txt` and
  `*.dist-info` (`top_level.txt`) give for it; its version comes from `vendor.txt`, `METADATA` or `__version__`.
  A copy belongs to a task when one of its names is the task's project or a top-level package of the parent's tree.
  `select`'s installed-overlap check compares each commit's new lines with the installed package's files together
  with these copies, also when the package itself is not installed; an excluded commit records the copies
  (`vendored`) and the rule is in `rule.installed_overlap`. `env-check` (new optional `--ext-cache`) lists each
  task's vendored copies with their release date (`after_commit`) and `vendored_scan`; the copies do not change
  `ok`, a failed site-packages scan does. Read only: nothing in the environment is changed.
