"""No-network long-session lead: persists only its fake conversation counter."""
import json
import os
from pathlib import Path
import sys

argv = sys.argv[1:]
sid_flag = "--resume" if "--resume" in argv else "--session-id"
sid = argv[argv.index(sid_flag) + 1]
prompt = sys.stdin.read()
log = Path(os.environ["P4_FAKE_LOG"])
entries = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []
previous = [e for e in entries if e["session"] == sid]
assert bool(previous) == (sid_flag == "--resume"), "resume must continue the same fake conversation"
repo = Path.cwd()
assert not (repo / "left-by-fake.txt").exists(), "task workspace was not reset"
assert "HIDDEN_GRADE_SENTINEL" not in prompt, "grade leaked to lead"
turn = len(previous) + 1
with log.open("a", encoding="utf-8", newline="") as f:
    f.write(json.dumps({"session": sid, "flag": sid_flag, "turn": turn, "prompt": prompt,
                        "parent": (repo / "source.py").read_text(encoding="utf-8")}) + "\n")
(repo / "left-by-fake.txt").write_text("changed", encoding="utf-8")
usage = {
    "input_tokens": 10, "cache_read_input_tokens": turn * 100, "cache_creation_input_tokens": 5,
    "output_tokens": 8}
cumulative_cost = round(.1 * turn, 6)
model_usage = {"fake": {"inputTokens": turn * 10, "outputTokens": turn * 8,
                         "cacheReadInputTokens": 100 * turn * (turn + 1) // 2,
                         "cacheCreationInputTokens": turn * 5, "costUSD": cumulative_cost}}
print(json.dumps({"type": "assistant", "message": {"id": f"{sid}-{turn}", "usage": usage}}))
# Native resumed results accumulate cost/modelUsage, while usage covers this call.
print(json.dumps({"type": "result", "session_id": sid, "subtype": "success",
                  "total_cost_usd": cumulative_cost, "modelUsage": model_usage, "usage": usage,
                  "result": "DONE: fake"}))
