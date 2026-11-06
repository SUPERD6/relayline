- Fix Windows acceptance checks using Bash syntax: select Git Bash when available and report missing or
  disappeared Bash executables as `check_broken`, preserving native cmd.exe commands, other OS errors, and
  existing test-failure verdicts. Preserve the full remedy in lead receipts, exclude WSL launchers, support
  nested Git/Scoop layouts, and warn about backslash paths in Bash checks.
