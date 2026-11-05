"""Zero-exit relay fixture that consumes the prompt without touching the workspace."""
import json
import sys

sys.stdin.buffer.read()
print(json.dumps({"type": "turn.completed"}))
