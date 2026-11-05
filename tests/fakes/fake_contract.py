"""Tool-free semantic CLI fixture: refuses contaminated process inputs."""
import json
import os
from pathlib import Path
import sys

if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8")
argv = sys.argv[1:]
assert list(Path.cwd().iterdir()) == []
assert argv[argv.index("--tools") + 1] == ""
assert argv[argv.index("--setting-sources") + 1] == ""
assert all(flag in argv for flag in ("--bare", "--strict-mcp-config", "--disable-slash-commands"))
assert "PYTHONPATH" not in os.environ and "CONTRACT_SECRET" not in os.environ
sources = json.load(sys.stdin)
assert set(sources) == {"task", "user_words", "interface"}
assert "IMPLEMENTATION_SECRET" not in json.dumps(sources)
assert "HIDDEN_SECRET" not in json.dumps(sources)
behavior = {"id": "integer", "source": "task", "quote": "Return 2.",
            "expected": "Returns integer 2", "unknown": False}
event = {"type": "result", "is_error": "--fake-error" in argv,
         "structured_output": {"behaviors": [behavior], "unknown_reasons": []}}
if "--fake-missing-cost" not in argv:
    event["total_cost_usd"] = 0.01
print(json.dumps(event))
