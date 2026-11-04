"""Fake CLIs accept already-decoded stdin used by runpy wrappers as well as pipes."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("agent", ["codex", "claude"])
def test_fake_cli_accepts_decoded_stringio(tmp_path, agent):
    fakes = Path(__file__).resolve().parent / "fakes"
    words = "Original words / 用户原话\nReturn (kind, value).\n"
    wrapper = tmp_path / "wrapped.py"
    wrapper.write_text(
        "import io, runpy, sys\n"
        f"sys.path.insert(0, {str(fakes)!r})\n"
        f"sys.stdin = io.StringIO({words!r})\n"
        f"runpy.run_path({str(fakes / ('fake_' + agent + '.py'))!r}, run_name='__main__')\n",
        encoding="utf-8", newline="")
    log = tmp_path / "calls.jsonl"
    env = {**os.environ, "FAKE_LOG": str(log), "FAKE_STATUS": "done",
           "FAKE_STATUS_CODEX": "done", "FAKE_STATUS_CLAUDE": "done"}
    result = subprocess.run([sys.executable, str(wrapper), "-p"], cwd=tmp_path, env=env,
                            capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stdout + result.stderr
    calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert calls[0]["prompt"] == words
