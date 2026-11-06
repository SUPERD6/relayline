"""New-lead fake: preserve partial work; deterministic abrupt process death, no model calls."""
import json
import os
from pathlib import Path
import sys
import signal

prompt = sys.stdin.buffer.read().decode("utf-8")
Path("relay-fake-call.json").write_text(json.dumps({"argv": sys.argv[1:], "prompt": prompt}), encoding="utf-8")
Path("partial.txt").write_text("partial work survives\n", encoding="utf-8")
if os.environ.get("FAKE_RELAY_DIE") == "1":
    os._exit(17)  # abrupt death after mutation, before normal completion
if os.environ.get("FAKE_RELAY_KILL") == "1":
    os.kill(os.getpid(), signal.SIGTERM)
if os.environ.get("FAKE_RELAY_QUOTA") == "1":
    # Synthetic Codex event; intentionally exits zero, as a refusal may do.
    print(json.dumps({"type": "turn.failed", "error": {"code": "usage_limit_reached"}}))
    sys.exit(0)
if os.environ.get("FAKE_RELAY_UNCONFIRMED") == "1":
    print(json.dumps({"hook_event_name": "StopFailure", "error": "rate_limit"}))
    sys.exit(0)
print(json.dumps({"type": "turn.completed"}))
