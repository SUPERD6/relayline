"""P13 headless lead: dispatch the supplied argv; all other Claude requests use fake_claude.

Used only with explicit fake agent overrides. Never starts a provider binary.
"""
import io
import json
import os
import runpy
import shlex
import subprocess
import sys
from pathlib import Path

prompt = sys.stdin.read()
line = next((x for x in prompt.splitlines() if x.startswith("P13_RUN_ARGV=")), None)
if line is None:
    sys.stdin = io.StringIO(prompt)
    runpy.run_path(str(Path(__file__).with_name("fake_claude.py")), run_name="__main__")
else:
    argv = json.loads(line.split("=", 1)[1])
    # Tests must explicitly bind every provider path to fakes before a command can be dispatched.
    for key in ("CCX_CODEX_BIN", "CCX_CLAUDE_BIN"):
        assert Path(os.environ[key]).resolve().parent == Path(__file__).resolve().parent
    result = subprocess.run(argv, input="", capture_output=True, text=True, encoding="utf-8", timeout=120)
    print(json.dumps({"type": "system", "subtype": "init", "session_id": "p13-fake-lead", "model": "sonnet"}))
    print(json.dumps({"type": "assistant", "message": {"id": "p13-1", "usage": {
        "input_tokens": 10, "cache_read_input_tokens": 20, "output_tokens": 5}, "content": [
            {"type": "tool_use", "name": "Bash", "input": {"command": shlex.join(argv)}}]}}))
    print(json.dumps({"type": "result", "subtype": "success", "is_error": False,
                      "result": result.stdout + result.stderr, "total_cost_usd": 0.01,
                      "usage": {"input_tokens": 10, "cache_read_input_tokens": 20, "output_tokens": 5}}))
    sys.exit(0 if result.returncode in (0, 2) else result.returncode)
