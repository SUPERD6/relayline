"""Independent startup/after-run archive switches; only synthetic hubs and fake CLIs."""
import json
import os
import subprocess
import sys
from unittest import mock

from test_ccx import Env, ROOT
from ccx import archive_worker, startup_maintenance
from ccx.config import Paths


class TestStartArchiveOptOut(Env):
    def test_disabled_scheduler_creates_no_worker_or_state(self):
        p = Paths(self.hub)
        with mock.patch.dict(os.environ, {"CCX_NO_START_ARCHIVE": "1"}), \
             mock.patch.object(archive_worker.subprocess, "Popen") as start, \
             mock.patch.object(archive_worker.threading, "Thread") as thread:
            assert not archive_worker.schedule(p)
            start.assert_not_called()
            thread.assert_not_called()
            assert not p.state.exists()

    def test_disabled_startup_skips_scheduling_but_keeps_other_maintenance(self):
        with mock.patch.dict(os.environ, {"CCX_NO_START_ARCHIVE": "1", "CCX_NO_BENCH_REFRESH": "1"}), \
             mock.patch("ccx.delegate.soft_verdicts") as verdicts, \
             mock.patch("ccx.ability.after_verdict") as ability, \
             mock.patch("ccx.projects.refresh_later") as projects, \
             mock.patch.object(archive_worker, "schedule") as schedule:
            p = Paths(self.hub)
            startup_maintenance.maintain(p)
            schedule.assert_not_called()
            verdicts.assert_called_once_with(p)
            ability.assert_called_once_with(p)
            projects.assert_called_once()

    def test_unset_or_non_one_value_keeps_scheduling(self):
        for value in (None, "", "0", "true"):
            with self.subTest(value=value), mock.patch.dict(os.environ), \
                 mock.patch.object(archive_worker.subprocess, "Popen") as start, \
                 mock.patch.object(archive_worker.threading, "Thread"):
                os.environ.pop("CCX_NO_START_ARCHIVE", None)
                if value is not None:
                    os.environ["CCX_NO_START_ARCHIVE"] = value
                assert archive_worker.schedule(Paths(self.hub))
                start.assert_called_once()

    def hook(self, *, disabled, no_auto):
        p = Paths(self.hub)
        rid, sid = "old-run", "old-session"
        run = p.runs / rid
        run.mkdir(parents=True)
        (run / "run.json").write_text(json.dumps({
            "run_id": rid, "to": "codex", "state": "finished", "sessions": [sid],
            "attempts": [{"agent": "codex", "session_id": sid}],
        }), encoding="utf-8")
        p.ledger.write_text(json.dumps({
            "run_id": rid, "ts": 1, "to": "codex", "sessions": [sid], "usage4": {}, "ae_usd": 0,
        }) + "\n", encoding="utf-8")
        support = self.work / "support"
        support.mkdir()
        # Observe real Popen calls, and wait for the real detached worker only
        # in this test harness. No sleep-based inference about worker startup.
        marker = self.work / "archive-worker-started"
        (support / "sitecustomize.py").write_text(
            "import atexit, subprocess, sys, threading\n"
            "from pathlib import Path\n"
            f"sys.path.insert(0, {str(ROOT)!r})\n"
            "import ccx\n"
            "original = subprocess.Popen\n"
            "def start(argv, *args, **kwargs):\n"
            "    if len(argv) > 1 and Path(argv[1]).name == 'archive_worker.py':\n"
            f"        Path({str(marker)!r}).write_text('started', encoding='utf-8')\n"
            "    return original(argv, *args, **kwargs)\n"
            "subprocess.Popen = start\n"
            "def reap():\n"
            "    for t in threading.enumerate():\n"
            "        if t.name == 'ccx-archive-reaper': t.join(30)\n"
            "atexit.register(reap)\n", encoding="utf-8")
        env = {**self.env, "PYTHONPATH": str(support), "CCX_NO_AUTO_ARCHIVE": no_auto,
               "CCX_HOOK_TIMEOUT_S": "0"}
        env.pop("CCX_NO_START_ARCHIVE", None)
        if disabled:
            env["CCX_NO_START_ARCHIVE"] = "1"
        result = subprocess.run([sys.executable, str(ROOT / "ccx.py"), "mem", "delta", "--as", "codex"],
                                cwd=self.work, env=env, capture_output=True, text=True, encoding="utf-8", timeout=60)
        assert result.returncode == 0, result.stderr
        journal = p.state / "archived.jsonl"
        if disabled:
            assert not marker.exists()
            assert not journal.exists()
            assert self.calls() == []
        else:
            assert marker.read_text(encoding="utf-8") == "started"
            entries = [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines()]
            assert [entry["run_id"] for entry in entries] == [rid]
            assert [call["argv"][:2] for call in self.calls()] == [["archive", sid]]

    def test_external_hook_does_not_launch_worker_when_disabled(self):
        self.hook(disabled=True, no_auto="0")

    def test_external_hook_keeps_default_startup_archival(self):
        self.hook(disabled=False, no_auto="0")

    def test_external_hook_ignores_after_run_opt_out(self):
        self.hook(disabled=False, no_auto="1")

    def test_startup_opt_out_keeps_after_run_archival(self):
        result = self.ccx("run", "--from", "claude", "--to", "codex", "--model", "gpt-6-luna",
                          "--effort", "low", "x", env={"CCX_NO_START_ARCHIVE": "1", "CCX_NO_AUTO_ARCHIVE": "0"})
        assert result.returncode == 0, result.stderr
        rid = json.loads(result.stdout)["run_id"]
        entries = [json.loads(line) for line in (Paths(self.hub).state / "archived.jsonl")
                   .read_text(encoding="utf-8").splitlines()]
        assert [(entry["run_id"], entry["why"]) for entry in entries] == [(rid, "after_run")]
