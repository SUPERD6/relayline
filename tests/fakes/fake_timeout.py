"""Write partial work and assistant events, then wait to be killed (never a real CLI)."""
import json
import os
import sys
import threading
from pathlib import Path

if "--version" in sys.argv:
    print("fake-timeout 1")
    sys.exit(0)
sys.stdin.reconfigure(encoding="utf-8")
prompt = sys.stdin.read()
agent = "claude" if "-p" in sys.argv else "codex"
if os.environ.get("FAKE_LOG"):
    with open(os.environ["FAKE_LOG"], "a", encoding="utf-8") as f:
        f.write(json.dumps({"agent": agent, "prompt": prompt, "argv": sys.argv[1:]}) + "\n")
once = os.environ.get("FAKE_TIMEOUT_ONCE")
if once and Path(once).exists():
    result = {"status": "done", "summary": "Recovered after timeout", "files_changed": ["a.py"],
              "commands_run": [], "verification": "not-run", "open_questions": [], "next_step": ""}
    if agent == "codex":
        print(json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps(result)}}))
    else:
        print(json.dumps({"type": "result", "structured_output": result, "session_id": "timeout-session"}))
    sys.exit(0)
if once:
    Path(once).write_text("first attempt started", encoding="utf-8")
Path("a.py").write_text("x = 2\n", encoding="utf-8")
Path("new file.txt").write_text("partial work\n", encoding="utf-8")
if Path("delete.txt").exists():
    Path("delete.txt").unlink()


def emit(event):
    print(json.dumps(event), flush=True)


message = "Partial result: changed a.py; checks not run; next: verify the change."
if agent == "codex":
    emit({"type": "thread.started", "thread_id": "timeout-session"})
    emit({"type": "item.completed", "item": {"type": "agent_message", "text": "Earlier message"}})
    emit({"type": "item.completed", "item": {"type": "agent_message", "text": message}})
    emit({"type": "item.completed", "item": {"type": "command_execution", "aggregated_output": "tool output"}})
else:
    emit({"type": "system", "session_id": "timeout-session"})
    emit({"type": "assistant", "message": {"content": [{"type": "text", "text": "Earlier message"}]}})
    emit({"type": "assistant", "message": {"content": [{"type": "text", "text": message},
                                                       {"type": "thinking", "thinking": "private reasoning"}]}})
    emit({"type": "user", "message": {"content": [{"type": "tool_result", "content": "tool output"}]}})
if os.environ.get("FAKE_TIMEOUT_PARTIAL_JSON"):
    print('{"type":"item.completed","item":', end="", flush=True)
threading.Event().wait()
