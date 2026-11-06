"""Claude launch/auth stand-in with a deterministic model-capacity refusal."""
import json
from pathlib import Path
import runpy
import sys

if "-p" not in sys.argv:
    runpy.run_path(str(Path(__file__).with_name("fake_claude.py")), run_name="__main__")
else:
    sys.stdin.read()
    print(json.dumps({"type": "result", "subtype": "error_during_execution", "is_error": True,
                      "session_id": "claude-capacity-session",
                      "errors": ["Selected model is at capacity. Please try again later."]}))
    sys.exit(1)
