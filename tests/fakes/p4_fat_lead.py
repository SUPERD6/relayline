"""No-network fat-context lead (#546): a fill turn, then task turns whose tool calls follow the arm.

The arm is read from the episode's repo folder name (`repo-<round>-<episode>-<arm>`); P4_FAKE_BEHAVE makes the lead
behave as another arm, P4_FAKE_FILL_FAIL makes the fill turn fail. It persists only its fake conversation log.
"""
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
assert "HIDDEN_GRADE_SENTINEL" not in prompt, "grade leaked to lead"
arm = os.environ.get("P4_FAKE_BEHAVE") or repo.name.rsplit("-", 1)[-1]
is_fill = prompt.startswith("BACKGROUND-FILL")
if is_fill and os.environ.get("P4_FAKE_FILL_FAIL"):
    print("fill failed", file=sys.stderr)
    sys.exit(3)
if is_fill:
    context = len(prompt.split("\n\n", 1)[1]) // 4   # the filler only, at the default 4.0 characters per token
    usage = {"input_tokens": 10, "cache_read_input_tokens": 0, "cache_creation_input_tokens": context - 10,
             "output_tokens": 2}
    step_cost = .5
else:
    last = previous[-1]["context"] if previous else 0
    context = last + 50
    usage = {"input_tokens": 10, "cache_read_input_tokens": last, "cache_creation_input_tokens": 40,
             "output_tokens": 8}
    step_cost = .1
total = {k: sum(e["usage"][k] for e in previous) + usage[k] for k in usage}
cumulative = round(sum(e["cost"] for e in previous) + step_cost, 6)
with log.open("a", encoding="utf-8", newline="") as f:
    f.write(json.dumps({"session": sid, "flag": sid_flag, "fill": is_fill, "arm": arm, "argv": argv, "usage": usage,
                        "context": context, "cost": step_cost, "prompt_head": prompt[:400],
                        "prompt_len": len(prompt)}) + "\n")
mid = f"{sid}-{len(previous) + 1}"
content = []
if not is_fill and arm == "fatnative":
    content.append({"type": "tool_use", "id": mid + "-agent", "name": "Agent",
                    "input": {"subagent_type": "worker", "prompt": "do it"}})
if not is_fill and arm == "fatccx":
    content.append({"type": "tool_use", "id": mid + "-ccx", "name": "Bash",
                    "input": {"command": 'python "/x/p4_receipt.py" run --to codex "do it"'}})
print(json.dumps({"type": "assistant", "message": {"id": mid, "usage": usage, "content": content}}))
if content and arm == "fatnative":
    # The built-in sub-agent's own message: not the lead's context.
    print(json.dumps({"type": "assistant", "parent_tool_use_id": mid + "-agent",
                      "message": {"id": mid + "-w", "usage": {"input_tokens": 5, "output_tokens": 5}}}))
model_usage = {"fake": {"inputTokens": total["input_tokens"], "outputTokens": total["output_tokens"],
                        "cacheReadInputTokens": total["cache_read_input_tokens"],
                        "cacheCreationInputTokens": total["cache_creation_input_tokens"], "costUSD": cumulative}}
print(json.dumps({"type": "result", "session_id": sid, "subtype": "success", "total_cost_usd": cumulative,
                  "modelUsage": model_usage, "usage": usage, "result": "READY" if is_fill else "DONE: fake"}))
