- p4 evaluation: `--hide PATH` (repeatable) adds another folder, e.g. the everyday development checkout when the run
  uses an independent clone, to every unit's forbidden list (Claude Read/Edit deny rules and the tool-call audit);
  missing paths and paths holding the work folder, this checkout or `--ext-python` are refused. A round-2 dry run, or
  any dry run with `--hide`, prints an `isolation` field with the `--hide` paths and every denied path. Without
  `--hide` units are isolated as before (#451).
