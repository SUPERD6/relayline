"""Synthetic regressions for hook deadlines, background archival and report I/O."""
import contextlib
import hashlib
import io
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest import mock

from test_ccx import Env, ROOT
from ccx import archive_worker, hookbudget, hooktimeout, ledger, memory, report, transcript
from ccx.ability import _lock
from ccx.config import Paths
from ccx.ui import Reader


class FakeClock:
    value = 0

    def __call__(self):
        return self.value


class TestSpeed(Env):
    def test_mem_delta_returns_before_blocked_background_archive_completes(self):
        import socket
        support = self.work / "blocked-archive-support"
        support.mkdir()
        complete = Paths(self.hub).state / "slow-archive-complete"
        with socket.socket() as server:
            server.bind(("127.0.0.1", 0))
            server.listen()
            server.settimeout(60)
            address = server.getsockname()
            # Both the CLI and its worker see the same fake. A synchronous
            # hook would block on recv; only the test can release archival,
            # and it does so after observing that the hook already returned.
            (support / "sitecustomize.py").write_text(
                "import socket, sys\n"
                f"sys.path.insert(0, {str(ROOT)!r})\n"
                "from ccx import archive\n"
                "def slow(p):\n"
                f"    with socket.create_connection({address!r}, timeout=60) as signal:\n"
                "        signal.sendall(b'started')\n"
                "        if signal.recv(1) == b'1':\n"
                "            (p.state / 'slow-archive-complete').write_text('done', encoding='utf-8')\n"
                "            signal.sendall(b'done')\n"
                "    return 0\n"
                "archive.auto = slow\n", encoding="utf-8")
            try:
                result = subprocess.run([sys.executable, str(ROOT / "ccx.py"), "mem", "delta", "--as", "codex"],
                                        cwd=self.work, env={**self.env, "PYTHONPATH": str(support)},
                                        capture_output=True, text=True, encoding="utf-8", timeout=60)
                assert result.returncode == 0, result.stderr
                connection, _ = server.accept()
                with connection, connection.makefile("rb") as signals:
                    connection.settimeout(60)
                    try:
                        assert signals.read(7) == b"started"
                        assert not complete.exists()
                    finally:
                        connection.sendall(b"1")
                    assert signals.read(4) == b"done"
                    assert complete.read_text(encoding="utf-8") == "done"
            except subprocess.TimeoutExpired:
                # Release the fake if a regression made the hook synchronous.
                connection, _ = server.accept()
                with connection:
                    connection.sendall(b"0")
                raise

    def test_session_start_schedule_keeps_original_no_auto_archive_semantics(self):
        # CCX_NO_AUTO_ARCHIVE controls after_run, not the original session-start
        # archive.auto path. Scheduling must preserve that distinction.
        with mock.patch.dict(os.environ, {"CCX_NO_AUTO_ARCHIVE": "1"}), \
             mock.patch.object(archive_worker.subprocess, "Popen") as start, \
             mock.patch.object(archive_worker.threading, "Thread"):
            assert archive_worker.schedule(Paths(self.hub))
            start.assert_called_once()

    def fixture(self):
        p = Paths(self.hub)
        p.state.mkdir(exist_ok=True)
        rows = [
            {"run_id": "old", "ts": 1, "to": "codex", "sessions": ["old-sub"],
             "usage4": {}, "ae_usd": 0, "status": "done"},
            {"type": "verify", "run_id": "old", "ts": 1, "ok": True, "soft": True},
            {"type": "verify", "run_id": "old", "ts": 2, "ok": False},
            {"run_id": "new", "ts": 1_800_000_000, "to": "codex", "sessions": ["sub"],
             "usage4": {"input_tokens": 100, "output_tokens": 10}, "ae_usd": 0.1, "status": "done"},
            {"type": "verify", "run_id": "new", "ts": 1_800_000_000, "ok": True},
        ]
        p.ledger.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
        return p

    def test_report_reads_once_and_keeps_json_and_text(self):
        p = self.fixture()
        # An uncached execution is the reference for the exact same inputs.
        # Freeze presentation time, not test duration or machine timezone.
        with mock.patch("time.time", return_value=1_800_000_001), \
             mock.patch("time.strftime", side_effect=lambda fmt, *a: "2026-11-04" if fmt == "%Y-%m-%d"
                        else "2026-11-04 12:00"), \
             mock.patch("ccx.usage.lead_events", return_value=([], [])) as leads:
            for include_lead in (False, True):
                with mock.patch("ccx.readscope.read", side_effect=lambda path, loader: loader()):
                    report.write(p, include_lead=include_lead)
                expected_json = (p.state / "report" / "summary.json").read_text(encoding="utf-8")
                expected_text = (p.state / "report" / "index.html").read_text(encoding="utf-8")
                # Captured from the unmodified HEAD report.py on the same
                # fixed fixture. These catch changes shared by both paths.
                golden = {
                    False: ("7a24874236b0b4fcc435d45ccf8baf653f999b774793f691618c23299416d2a4",
                            "c2dde94c6b38889f75aed8edd4a3c08090f4c42d52484d41bbcf05c617fea64d"),
                    True: ("4b4453e85f70d9b8719a3cc0e1430cd710d1e0855653a965d919fe63f1993acd",
                           "7a62cfc78a7ea564f63f2b54351a3268e5e14d62478b86e6091fb06db5b4f7f4"),
                }
                assert tuple(hashlib.sha256(s.encode()).hexdigest() for s in
                             (expected_json, expected_text)) == golden[include_lead]
                with mock.patch.object(ledger, "_read_rows", wraps=ledger._read_rows) as read:
                    report.write(p, include_lead=include_lead)
                    assert read.call_count == 1
                assert (p.state / "report" / "summary.json").read_text(encoding="utf-8") == expected_json
                assert (p.state / "report" / "index.html").read_text(encoding="utf-8") == expected_text
                if not include_lead:
                    leads.assert_not_called()
            # All-time trust and excluded sessions retain rows outside the window.
            assert report.collect(p)["soft_trust"]["overturned"] == 1
            assert "old-sub" in leads.call_args.args[1]
        # The snapshot is not kept for the next command.
        p.ledger.write_text("", encoding="utf-8")
        assert report.collect(p, include_lead=False)["runs"] == []

    def test_scope_released_on_failure_and_different_hubs(self):
        from ccx.readscope import once
        p = self.fixture()
        other = Paths(self.work)
        @once
        def fail():
            assert ledger.rows(p)
            assert ledger.rows(other) == []
            raise ValueError("stop")
        with self.assertRaises(ValueError):
            fail()
        p.ledger.write_text("", encoding="utf-8")
        assert ledger.rows(p) == []

    def test_budget_preserves_complete_output_and_skips_next_step(self):
        clock = FakeClock()
        later = mock.Mock()
        def hook():
            hookbudget.hints(["[ccx first]"], "codex")
            clock.value = 2
            hookbudget.check()
            later()
        with contextlib.redirect_stdout(io.StringIO()) as out:
            assert hooktimeout.run("mem delta", hook, Paths(self.hub), 2, clock=clock) == 0
        assert out.getvalue() == "From ccx (shared memory and delegated work):\n[ccx first]\n"
        later.assert_not_called()

    def test_hard_timeout_emits_checkpoint_even_while_worker_is_stuck(self):
        class Worker:
            ident = None
            def __init__(self, target, **kwargs):
                self.target = target
            def start(self):
                self.target()
            def join(self, timeout):
                pass
            def is_alive(self):
                return True
        clock = FakeClock()
        def hook():
            hookbudget.checkpoint('{"complete":true}')
            return 0
        with contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()), \
             mock.patch.object(hooktimeout.threading, "Thread", Worker), \
             mock.patch.object(hooktimeout.os, "_exit", side_effect=SystemExit(0)):
            with self.assertRaises(SystemExit):
                hooktimeout.run("turn", hook, Paths(self.hub), 2, clock=clock)
        # _exit normally terminates the process; restore the redirected streams
        # for this in-process simulation, as the production path never returns.
        assert out.getvalue() == '{"complete":true}\n'
        assert json.loads(out.getvalue()) == {"complete": True}

    def test_mem_delta_cli_budget_uses_fake_clock_and_preserves_hint(self):
        p = Paths(self.hub)
        memory.add(p, "keep the completed hint", "user", "preference")
        support = self.work / "budget-support"
        support.mkdir()
        # Only the child hook gets this fake clock. Advancing in stale() must
        # skip ranked(), while retaining memory.delta's complete output.
        (support / "sitecustomize.py").write_text(
            "import sys\n"
            f"sys.path.insert(0, {str(ROOT)!r})\n"
            "from ccx import hookbudget, memory, memsuggest\n"
            "state = [0]\n"
            "original = hookbudget.Budget.__init__\n"
            "def init(self, seconds, clock=None):\n"
            "    original(self, seconds, lambda: state[0])\n"
            "hookbudget.Budget.__init__ = init\n"
            "def stale(p):\n"
            "    state[0] = 21\n"
            "    return []\n"
            "memory.stale = stale\n"
            "def forbidden(*args):\n"
            "    raise AssertionError('late step executed')\n"
            "memsuggest.ranked = forbidden\n", encoding="utf-8")
        result = self.ccx("mem", "delta", "--as", "codex", "--peek", env={
            "PYTHONPATH": str(support), "CCX_HOOK_TIMEOUT_S": "20"})
        assert result.returncode == 0, result.stderr
        assert "keep the completed hint" in result.stdout
        assert result.stderr == ""

    def test_header_cache_invalidates_same_size_replace_and_newest_discovery(self):
        d = self.home_codex / "sessions"
        d.mkdir()
        f = d / "rollout-a.jsonl"
        def content(cwd):
            return json.dumps({"payload": {"id": "a", "cwd": str(cwd)}}) + "\n" + "x" * 10000
        f.write_text(content(self.work), encoding="utf-8")
        find = lambda: transcript.find_session("codex", self.work, set(), codex_home=self.home_codex)
        assert find() == f
        with mock.patch.object(Path, "open", side_effect=AssertionError("unchanged header reread")):
            assert find() == f
        old = f.stat()
        replaced = f.with_suffix(".tmp")
        replaced.write_text(content(self.work.with_name("away")), encoding="utf-8")
        assert replaced.stat().st_size == old.st_size
        os.utime(replaced, ns=(old.st_atime_ns, old.st_mtime_ns))
        os.replace(replaced, f)
        assert find() is None
        newer = d / "rollout-b.jsonl"
        newer.write_text(content(self.work), encoding="utf-8")
        assert find() == newer
        assert transcript.find_session("codex", self.work, {"a"}, codex_home=self.home_codex) is None

    def test_ui_json_already_short_circuits_and_keeps_last_good(self):
        p = self.fixture()
        f = self.work / "large.json"
        f.write_text('{"data":"' + "x" * 100000 + '"}', encoding="utf-8")
        reader = Reader(p)
        expected = reader.json_file(f)
        with mock.patch.object(Path, "read_text", side_effect=AssertionError("unchanged JSON reread")):
            assert reader.json_file(f) == expected
        f.write_text("{", encoding="utf-8")
        assert reader.json_file(f) == expected
        f.write_text('{"data":2}', encoding="utf-8")
        assert reader.json_file(f) == {"data": 2}

    def test_archive_schedule_is_windowless_reaped_and_failure_is_quiet(self):
        from ccx.winproc import BACKGROUND
        child = mock.Mock()
        with mock.patch.dict(os.environ, {"CCX_NO_AUTO_ARCHIVE": "0"}), \
             mock.patch.object(archive_worker.subprocess, "Popen", return_value=child) as start, \
             mock.patch.object(archive_worker.threading, "Thread") as thread:
            assert archive_worker.schedule(Paths(self.hub))
            assert start.call_args.kwargs.items() >= BACKGROUND.items()
            for key in ("stdin", "stdout", "stderr"):
                assert start.call_args.kwargs[key] == subprocess.DEVNULL
            assert start.call_args.kwargs["close_fds"] is True
            assert thread.call_args.kwargs["target"] == child.wait
            assert thread.call_args.kwargs["daemon"] is True
            thread.return_value.start.assert_called_once()
        with mock.patch.dict(os.environ, {"CCX_NO_AUTO_ARCHIVE": "0"}), \
             mock.patch.object(archive_worker.subprocess, "Popen", side_effect=OSError("unavailable")):
            assert not archive_worker.schedule(Paths(self.hub))

    def test_busy_archive_worker_skips_without_taking_over_lock(self):
        p = Paths(self.hub)
        with _lock(p, name="archive.lock"), mock.patch("ccx.archive.auto") as auto:
            assert archive_worker.run(p) == 0
            auto.assert_not_called()
        with mock.patch("ccx.archive.auto", return_value=3):
            assert archive_worker.run(p) == 3

    def test_mem_delta_cli_from_outside_repo_schedules_archival(self):
        p = Paths(self.hub)
        p.state.mkdir(exist_ok=True)
        rid, sid = "synthetic-old", "synthetic-session"
        rec = {"run_id": rid, "to": "codex", "state": "finished", "sessions": [sid],
               "attempts": [{"agent": "codex", "session_id": sid}]}
        run = p.runs / rid
        run.mkdir(parents=True)
        (run / "run.json").write_text(json.dumps(rec), encoding="utf-8")
        p.ledger.write_text(json.dumps({"run_id": rid, "ts": 1, "to": "codex", "sessions": [sid],
                                       "usage4": {}, "ae_usd": 0}) + "\n", encoding="utf-8")
        # A separate process must respect a live holder, without sleep/polling
        # or inferring whether two fast processes happened to overlap.
        with _lock(p, name="archive.lock"):
            busy = subprocess.run([sys.executable, str(ROOT / "ccx" / "archive_worker.py"), str(self.hub)],
                                  cwd=self.work, env=self.env, capture_output=True, timeout=20)
            assert busy.returncode == 0
            assert not (p.state / "archived.jsonl").exists()
        # Join only in the test harness at process exit so effects can be checked
        # without polling or sleeping. Production hooks never wait for the worker.
        support = self.work / "support"
        support.mkdir()
        (support / "sitecustomize.py").write_text(
            "import atexit, threading\n"
            "def reap():\n"
            "    for t in threading.enumerate():\n"
            "        if t.name == 'ccx-archive-reaper':\n"
            "            t.join(20)\n"
            "atexit.register(reap)\n", encoding="utf-8")
        r = self.ccx("mem", "delta", "--as", "codex", env={
            "PYTHONPATH": str(support), "CCX_HOOK_TIMEOUT_S": "20", "CCX_NO_AUTO_ARCHIVE": "0"})
        assert r.returncode == 0, r.stderr
        entries = [json.loads(line) for line in (p.state / "archived.jsonl").read_text(encoding="utf-8").splitlines()]
        assert [e["run_id"] for e in entries] == [rid]
        assert [c["argv"][:2] for c in self.calls() if c["argv"][:1] == ["archive"]] == [["archive", sid]]
        # A fresh detached worker finds the archived run and does nothing.
        r = subprocess.run([sys.executable, str(ROOT / "ccx" / "archive_worker.py"), str(self.hub)],
                           cwd=self.work, env=self.env, capture_output=True, timeout=20)
        assert r.returncode == 0
        assert len((p.state / "archived.jsonl").read_text(encoding="utf-8").splitlines()) == 1
