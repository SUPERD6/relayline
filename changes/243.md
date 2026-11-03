- Record decisions in per-PR `changes/<PR>.decision.md` files and fold them into `docs/DECISIONS.md` when releasing,
  avoiding conflicts between parallel PRs. Validate both note types with `--check`, preview both documents by
  default, and keep decision rows out of the CHANGELOG. All existing collector options remain available;
  temporary-repository CLI tests cover validation, ordering, preview, and release folding.
