"""Long-session lead whose login has expired (#509): fails at once, costs nothing, ends the stream with an error result."""
import json
import sys

argv = sys.argv[1:]
sid = argv[argv.index("--resume" if "--resume" in argv else "--session-id") + 1]
sys.stdin.read()
msg = "Failed to authenticate. API Error: 401 OAuth session expired and could not be refreshed"
print(json.dumps({"type": "result", "subtype": "success", "is_error": True, "session_id": sid,
                  "total_cost_usd": 0, "usage": {}, "modelUsage": {}, "result": msg}))
print(msg, file=sys.stderr)
sys.exit(1)
