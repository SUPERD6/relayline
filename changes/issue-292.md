- Fix preflight JSON and warning output on Windows by configuring stdout/stderr as UTF-8 when supported.
  Harden eval sandbox temp subprocess tests with UTF-8 Python output, replacement decoding, and stdout/stderr
  diagnostics. Add legacy-encoding regression checks, including an unset PYTHONIOENCODING environment.
