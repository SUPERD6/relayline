"""Run the real command parser with fake agents, counting quota file scans for the calling test."""
import json
import os
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from ccx import cli, quota  # noqa: E402

with mock.patch.object(quota, "claude_readings", wraps=quota.claude_readings) as claude, \
        mock.patch.object(quota, "codex_readings", wraps=quota.codex_readings) as codex:
    result = cli.main()
    Path(os.environ["FAKE_QUOTA_SCANS"]).write_text(
        json.dumps({"claude": claude.call_count, "codex": codex.call_count}), encoding="utf-8")
raise SystemExit(result)
