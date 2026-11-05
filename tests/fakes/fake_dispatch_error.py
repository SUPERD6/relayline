"""Deterministic cheap-rung CLI failure; stronger attempts use the existing fake adapter."""
import json
from pathlib import Path
import runpy
import sys

argv = sys.argv[1:]
if "-m" in argv and argv[argv.index("-m") + 1] == "gpt-6-luna":
    print(json.dumps({"type": "error", "message": "synthetic CLI execution failed"}))
    sys.exit(1)
runpy.run_path(str(Path(__file__).with_name("fake_codex.py")), run_name="__main__")
