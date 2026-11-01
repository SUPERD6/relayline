- README (EN + ZH) now tells ccx in eight layers (conversation, shared memory, splitting and pipeline, delegation and
  choosing, checks and receipts, control and recovery, measurement and honesty, interface and first steps), each with
  what ccx does, one number from `docs/measured.md` and one limit; the hold-out (hc1) and polyglot (pg1) results sit
  side by side above it. New sections "You can stop at any point" (stop, resume, undo, worktree, autonomy L0–L2,
  confirmed buttons) and "Safety boundary". The quick start, install and commands are unchanged; the full comparison
  (dev set, cost, speed, receipt audit, limits) moved below the quick start; the seven-things line became a pointer to
  docs/features.md. The website's "Seven things" section became the same eight layers (EN + ZH), with the pg1 result
  beside the hold-out table. `tests/test_readme_layers.py` checks every number in the layer table against measured.md. The READMEs show the home map and a receipt; the
  token page's screenshot stays on the website and in docs/features.md. `tests/test_site.py` now checks every image the
  website shows is in the built site (the Chinese page's new screenshot pointed at the wrong folder).
