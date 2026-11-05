"""Fake receipt target, captures argv only; no delegation."""
import json
import os
from pathlib import Path
import sys
Path(os.environ["P5_CAPTURE_ARGV"]).write_text(json.dumps(sys.argv[1:]), encoding="utf-8")
print(json.dumps({"ok": True, "status": "done", "summary": "fake"}))
