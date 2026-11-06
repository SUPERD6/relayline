"""Archive/resume interleavings and cleanup, with fake CLIs and explicit signals."""
import contextlib
import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from unittest import mock

from test_ccx import Env, ROOT
from ccx import archive, archive_worker, ledger, sessionguard
from ccx.config import Paths


class TestArchiveSafety(Env):
    def setUp(self):
        super().setUp()
        self.environment = mock.patch.dict(os.environ, self.env)
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        super().tearDown()

    def candidate(self):
        p = Paths(self.hub)
        rec = {"run_id": "old", "state": "finished", "to": "codex", "session_id": "shared",
               "attempts": [{"agent": "codex", "session_id": "shared"}]}
        (p.runs / "old").mkdir(parents=True)
        ledger.write_record(p.runs / "old", rec)
        p.ledger.write_text(json.dumps({"run_id": "old", "ts": 1, "to": "codex",
                                       "usage4": {}, "sessions": ["shared"]}) + "\n", encoding="utf-8")
        return p

    def test_resume_waits_for_archive_journal_then_restores_and_publishes_busy(self):
        p = self.candidate()
        archived, release, restoring, published = (threading.Event() for _ in range(4))
        errors = []
        real_run, real_lock = archive._run, sessionguard._lock

        def paused(argv):
            result = real_run(argv)          # fake CLI has archived, journal not written yet
            if "archive" in argv:
                archived.set()
                assert release.wait(60)
            return result

        @contextlib.contextmanager
        def observed_lock(*args, **kwargs):
            if threading.current_thread().name == "resume-test":
                restoring.set()
            with real_lock(*args, **kwargs):
                yield

        def publish():
            d = p.runs / "new"
            d.mkdir()
            ledger.write_record(d, {"run_id": "new", "state": "running", "to": "codex",
                                    "session_id": "shared", "attempts": []})
            published.set()

        def checked(fn):
            try:
                fn()
            except BaseException as exc:
                errors.append(exc)

        with mock.patch.object(archive, "_run", side_effect=paused), \
             mock.patch.object(sessionguard, "_lock", side_effect=observed_lock):
            worker = threading.Thread(target=lambda: checked(lambda: archive_worker.run(p)))
            resume = threading.Thread(name="resume-test", target=lambda: checked(lambda: sessionguard.start(
                p, {"session_id": "shared"}, publish)))
            worker.start()
            try:
                assert archived.wait(60)
                resume.start()
                assert restoring.wait(60)
                assert not published.is_set()
            finally:
                release.set()
                worker.join(60)
                if resume.ident is not None:
                    resume.join(60)
            assert not worker.is_alive() and not resume.is_alive()
            assert not errors, errors
            assert published.is_set()
        assert [c["argv"][:2] for c in self.calls()] == [["archive", "shared"], ["unarchive", "shared"]]
        assert archive.archived_ids(p) == set()
        archive_worker.run(p)                # old ledger row still names the now-running session
        assert len(self.calls()) == 2
        assert archive.archived_ids(p) == set()

    def test_running_session_is_not_archived_through_an_older_finished_run(self):
        p = self.candidate()
        d = p.runs / "new"
        d.mkdir()
        ledger.write_record(d, {"state": "running", "session_id": "shared", "attempts": []})
        archive_worker.run(p)
        assert self.calls() == []
        assert not (p.state / "archived.jsonl").exists()

    def test_resume_cli_restores_after_inflight_worker_before_continuing(self):
        import socket
        from ccx.winproc import BACKGROUND
        result = self.ccx("run", "--from", "claude", "--to", "codex", "--tier", "T2", "x")
        assert result.returncode == 0, result.stderr
        rid = json.loads(result.stdout)["run_id"]
        p = Paths(self.hub)
        old = json.loads(p.ledger.read_text(encoding="utf-8").splitlines()[-1])
        old["ts"] = 1
        p.ledger.write_text(json.dumps(old) + "\n", encoding="utf-8")
        archived, release = threading.Event(), threading.Event()
        real_run = archive._run
        errors = []

        def paused(argv):
            result = real_run(argv)
            if "archive" in argv:
                archived.set()
                assert release.wait(60)
            return result

        def worker_fn():
            try:
                archive_worker.run(p)
            except BaseException as exc:
                errors.append(exc)

        with socket.socket() as server, mock.patch.object(archive, "_run", side_effect=paused):
            server.bind(("127.0.0.1", 0))
            server.listen()
            server.settimeout(60)
            support = self.work / "resume-support"
            support.mkdir()
            (support / "sitecustomize.py").write_text(
                "import socket, sys\n"
                f"sys.path.insert(0, {str(ROOT)!r})\n"
                "from ccx import sessionguard\n"
                "original = sessionguard.start\n"
                "def start(*args):\n"
                f"    with socket.create_connection({server.getsockname()!r}, timeout=60) as signal:\n"
                "        signal.sendall(b'ready')\n"
                "    return original(*args)\n"
                "sessionguard.start = start\n", encoding="utf-8")
            worker = threading.Thread(target=worker_fn)
            worker.start()
            child = None
            try:
                assert archived.wait(60)
                child = subprocess.Popen([sys.executable, str(ROOT / "ccx.py"), "resume", rid, "continue"],
                                         cwd=self.work, env={**self.env, "PYTHONPATH": str(support)},
                                         stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                         **BACKGROUND)
                connection, _ = server.accept()
                with connection, connection.makefile("rb") as signal:
                    assert signal.read(5) == b"ready"
                release.set()
                stdout, stderr = child.communicate(timeout=60)
                assert child.returncode == 0, (stdout, stderr)
            finally:
                release.set()
                worker.join(60)
                if child is not None and child.poll() is None:
                    child.kill()
                    child.wait()
            assert not worker.is_alive() and not errors, errors
        verbs = [c["argv"][:2] for c in self.calls()
                 if c["argv"][:1] in (["archive"], ["unarchive"]) or c["argv"][:2] == ["exec", "resume"]]
        assert [v[0] for v in verbs] == ["archive", "unarchive", "exec"]

    def test_archive_timeout_kills_reaps_child_and_releases_worker_lock(self):
        p = self.candidate()
        real_popen = subprocess.Popen
        children = []
        limits = []

        def launch(*args, **kwargs):
            child = real_popen(*args, **kwargs)
            if str(ROOT / "tests/fakes/fake_archive_wait.py") not in args[0]:
                return child
            children.append(child)
            original = child.communicate
            first = True

            def expire(input=None, timeout=None):
                nonlocal first
                if first:
                    first = False
                    limits.append(timeout)    # no real timeout is allowed to elapse
                    assert child.stdout.readline() == "archive-ready\n"
                    raise subprocess.TimeoutExpired(args[0], timeout)
                return original(input=input, timeout=timeout)
            child.communicate = expire
            child.kill = mock.Mock(wraps=child.kill)
            return child

        with mock.patch.dict(os.environ, {"CCX_CODEX_BIN": str(ROOT / "tests/fakes/fake_archive_wait.py")}), \
             mock.patch.object(archive.subprocess, "Popen", side_effect=launch):
            archive_worker.run(p)
        assert len(children) == 1
        assert limits == [30]
        children[0].kill.assert_called_once()
        assert children[0].poll() is not None
        assert archive.archived_ids(p) == set()
        # Successful retry under the same OS lock proves the timed-out worker
        # released it; the next command uses the normal fake CLI.
        with sessionguard.lock(p, timeout=0):
            assert archive._run([sys.executable, str(ROOT / "tests/fakes/fake_codex.py"),
                                 "archive", "next"])[0] == 0
        archive_worker.run(p)
        assert archive.archived_ids(p) == {"old"}

    def test_relative_hub_worker_uses_absolute_hub_from_changed_cwd(self):
        p = self.candidate()
        support = self.work / "support"
        support.mkdir()
        (support / "sitecustomize.py").write_text(
            "import atexit, threading\n"
            "def reap():\n"
            "    for t in threading.enumerate():\n"
            "        if t.name == 'ccx-archive-reaper': t.join(60)\n"
            "atexit.register(reap)\n", encoding="utf-8")
        relative = os.path.relpath(self.hub, self.work)
        result = subprocess.run([sys.executable, str(self.ccx_entrypoint), "mem", "delta", "--as", "codex"],
                                cwd=self.work, env={**self.env, "CCX_HUB": relative, "PYTHONPATH": str(support)},
                                capture_output=True, text=True, encoding="utf-8", timeout=60)
        assert result.returncode == 0, result.stderr
        assert archive.archived_ids(p) == {"old"}
        assert [c["argv"][:2] for c in self.calls()] == [["archive", "shared"]]
        assert not (p.state / relative / "ccx").exists()
