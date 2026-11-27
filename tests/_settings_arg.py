"""The value after `--settings` in a claude argv as a dict: inline JSON when short, else the settings file ccx wrote (#585)."""
import json
from pathlib import Path


def settings_arg(argv):
    v = argv[argv.index("--settings") + 1]
    return json.loads(v if v.lstrip().startswith("{") else Path(v).read_text(encoding="utf-8"))
