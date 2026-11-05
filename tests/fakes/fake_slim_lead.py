"""Deterministic wiring fixture, not evidence that a model follows the guidance."""
import json
import os
from pathlib import Path
import subprocess
import sys

prompt = sys.stdin.read()
assert "no ccx command, brief file" in prompt
assert "--files <estimated number of implementation files>" in prompt
root = Path(__file__).resolve().parents[2]
hub = Path(os.environ["CCX_HUB"])
assert "slim_small = true" in (hub / "ccx/settings.toml").read_text(encoding="utf-8")
managed = Path(os.environ["CLAUDE_CONFIG_DIR"]) / "CLAUDE.md"
if managed.exists():
    assert "no ccx command, brief file" in managed.read_text(encoding="utf-8")
if os.environ["FAKE_SLIM_MODE"] == "small":
    Path("answer.py").write_text("def f(x):\n    return x * 2\n", encoding="utf-8")
    content = [{"type": "tool_use", "id": "write", "name": "Write", "input": {"file_path": "answer.py"}}]
else:
    for agent in ("CODEX", "CLAUDE"):
        assert Path(os.environ[f"CCX_{agent}_BIN"]).resolve().parent == Path(__file__).resolve().parent
    argv = [sys.executable, str(root / "ccx.py"), "run", "--from", "claude", "--to", "codex",
            "--model", "gpt-6-luna", "--effort", "low", "--files", "2", "--mode", "write",
            "--review", "off", "--context", "off", "--no-ab", "--no-fallback", "--new", "Implement f(x), double x"]
    r = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    assert json.loads(r.stdout).get("run_id"), r.stdout
    content = [{"type": "tool_use", "id": "run", "name": "Bash",
                "input": {"command": subprocess.list2cmdline(argv)}}]
print(json.dumps({"type": "system", "subtype": "init", "session_id": "fake-slim", "model": "sonnet",
                  "skills": []}))
print(json.dumps({"type": "assistant", "message": {"id": "fake-slim-1", "content": content,
                  "usage": {"input_tokens": 10, "cache_read_input_tokens": 20, "output_tokens": 5}}}))
print(json.dumps({"type": "result", "subtype": "success", "total_cost_usd": 0.01,
                  "result": "DONE: doubled x", "usage": {"input_tokens": 10, "output_tokens": 5}}))
