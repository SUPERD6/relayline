"""Offline engineering check; synthetic data only, no agent CLIs or real homes.

Run unchanged before/after a patch, optionally with --out PATH. Timings are
observations, never test assertions. All fixtures are removed on exit.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ccx import archive, report, transcript
from ccx.config import Paths
from ccx.ui import Reader


def measure(fn, repeats):
    values = []
    for _ in range(repeats):
        start = time.perf_counter()
        fn()
        values.append(round((time.perf_counter() - start) * 1000, 3))
    return {"ms": values, "median_ms": statistics.median(values)}


def archival(root, mode, repeats):
    # Baseline revisions have no worker module. Resolve it only when this
    # revision supports the background path; the fixture itself stays identical.
    if mode == "auto":
        try:
            from ccx import archive_worker
        except ImportError:
            mode = "sync"
        else:
            mode = "background"
    elif mode == "background":
        from ccx import archive_worker
    values, completed = [], []
    for n in range(repeats):
        p = Paths(root / f"archive-{n}")
        p.state.mkdir(parents=True)
        rows = []
        for i in range(14):
            rid, sid = f"run-{i}", f"session-{i}"
            d = p.runs / rid
            d.mkdir(parents=True)
            (d / "run.json").write_text(json.dumps({"run_id": rid, "to": "codex",
                "attempts": [{"agent": "codex", "session_id": sid}]}), encoding="utf-8")
            rows.append({"run_id": rid, "ts": 1, "sessions": [sid], "usage4": {}})
        p.ledger.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
        start = time.perf_counter()
        if mode == "sync":
            archive.auto(p)                  # the original hook's exact call
        else:
            assert archive_worker.schedule(p)
        values.append(round((time.perf_counter() - start) * 1000, 3))
        # Completion is deliberately outside the hook-path timing.
        for t in threading.enumerate():
            if t.name == "ccx-archive-reaper":
                t.join(60)
                assert not t.is_alive()
        entries = (p.state / "archived.jsonl").read_text(encoding="utf-8").splitlines()
        assert len(entries) == 14
        completed.append(len(entries))
    return {"mode": mode, "ms": values, "median_ms": statistics.median(values), "completed": completed}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rows", type=int, default=50_000)
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--archive-mode", choices=("auto", "sync", "background"), default="auto",
                    help="auto uses this revision's path; sync reproduces the original hook call; "
                         "background measures scheduling only")
    a = ap.parse_args()
    with tempfile.TemporaryDirectory(prefix="ccx-hook-report-") as tmp:
        root = Path(tmp)
        p = Paths(root / "hub")
        p.state.mkdir(parents=True)
        # Old verdicts exercise all-time trust and exclusion, without a costly
        # bootstrap drowning out I/O. A report still traverses every ledger row.
        row = {"type": "verify", "run_id": "synthetic", "ok": True, "ts": 1}
        p.ledger.write_text((json.dumps(row) + "\n") * a.rows, encoding="utf-8")
        home = root / "codex"
        sessions = home / "sessions"
        sessions.mkdir(parents=True)
        for i in range(200):
            f = sessions / f"rollout-{i:04}.jsonl"
            meta = {"payload": {"id": str(i), "cwd": str(root / "other")}}
            f.write_text(json.dumps(meta) + "\n" + '{"type":"irrelevant"}\n' * 2500, encoding="utf-8")
        big = root / "large.json"
        big.write_text(json.dumps({"data": "x" * 5_000_000}), encoding="utf-8")
        reader = Reader(p)
        env = {"CCX_CONFIG": str(root / "absent.toml"), "CODEX_HOME": str(home),
               "CLAUDE_CONFIG_DIR": str(root / "claude"), "DSH_HOME": str(root / "dsh"),
               "CCX_HUB": str(p.hub), "CCX_NO_AUTO_ARCHIVE": "0",
               "CCX_CODEX_BIN": str(Path(__file__).resolve().parents[1] / "tests" / "fakes" / "fake_codex.py"),
               "CCX_NO_LOCATE": "1", "FAKE_LOG": "", "FAKE_QUOTA_CODEX": ""}
        with patch.dict(os.environ, env):
            result = {"evidence": "engineering check", "rows": a.rows, "session_files": 200,
                      "session_lines_each": 2501, "json_bytes": big.stat().st_size,
                      "report_no_lead": measure(lambda: report.write(p, include_lead=False), a.repeats),
                      "find_session": measure(lambda: transcript.find_session(
                          "codex", root, set(), codex_home=home), a.repeats),
                      "json_file": measure(lambda: reader.json_file(big), a.repeats),
                      "archive_hook": archival(root, a.archive_mode, a.repeats)}
    text = json.dumps(result, indent=2)
    if a.out:
        a.out.write_text(text + "\n", encoding="utf-8", newline="")
    print(text)


if __name__ == "__main__":
    main()
