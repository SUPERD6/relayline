"""Synthetic model-capacity errors; successful models use the normal Codex fake."""
import json
import os
from pathlib import Path
import runpy
import sys

from fake_log import locked_append

argv = sys.argv[1:]
model = argv[argv.index("-m") + 1] if "-m" in argv else ""
failed_models = os.environ.get("FAKE_CAPACITY_MODELS", "")
if (model and (model in failed_models.split(",") or failed_models == "all")
        and (not os.environ.get("FAKE_CAPACITY_RESUME_ONLY") or "resume" in argv)):
    prompt = sys.stdin.read()
    with locked_append(os.environ["FAKE_LOG"]) as fh:
        fh.write(json.dumps({"agent": "codex", "argv": argv, "prompt": prompt, "capacity": True}) + "\n")
    print(json.dumps({"type": "thread.started", "thread_id": "capacity-session"}))
    if os.environ.get("FAKE_CAPACITY_TRANSIENT"):
        print(json.dumps({"type": "error", "message": "Selected model is at capacity"}))
    message = os.environ.get("FAKE_CAPACITY_MESSAGE", "Selected model is at capacity. Please try again later.")
    error = {"message": message}
    if os.environ.get("FAKE_CAPACITY_CODE"):
        error["code"] = os.environ["FAKE_CAPACITY_CODE"]
    print(json.dumps({"type": "turn.failed", "error": error}))
    if os.environ.get("FAKE_CAPACITY_STDERR"):
        print(os.environ["FAKE_CAPACITY_STDERR"], file=sys.stderr)
    sys.exit(1)
runpy.run_path(str(Path(__file__).with_name("fake_codex.py")), run_name="__main__")
