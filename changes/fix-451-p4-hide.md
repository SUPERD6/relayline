- p4 evaluation: `--hide PATH` (repeatable) adds another folder, e.g. the everyday development checkout when the run
  uses an independent clone, to every unit's forbidden list (Claude Read/Edit deny rules and the tool-call audit), in
  both spellings when a link makes them differ. With `--hide` the audit also flags any mention of the `round2_a` /
  `round2_bc` task folders and a hidden folder's parent folders named on their own. Missing paths, this checkout and
  paths holding the work folder, this checkout or `--ext-python` are refused. A round-2 dry run, or any dry run with
  `--hide`, prints an `isolation` field with the `--hide` paths, every denied folder and the extra audit regexes.
  Without `--hide` units are isolated and audited as before (#451).
