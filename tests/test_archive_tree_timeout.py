"""A real wrapper/child tree; timeout and OS tree termination use explicit signals."""
import json
import os
import socket
import subprocess
import sys
from unittest import mock

from test_ccx import Env, ROOT
from ccx import archive, runners, sessionguard
from ccx.config import Paths


class TestArchiveTreeTimeout(Env):
    def test_cmd_wrapper_timeout_requests_tree_cleanup_before_direct_child_reaping(self):
        fake = ROOT / "tests/fakes/fake_archive_tree.py"
        if os.name == "nt":
            shim = self.work / "fake-codex.cmd"
            shim.write_text(f'@echo off\n"{sys.executable}" "{fake}" %*\n', encoding="utf-8")
            argv = [str(shim), "archive", "synthetic"]
        else:
            argv = [sys.executable, str(fake), "archive", "synthetic"]
        real_popen = subprocess.Popen
        descendants, children, flags, events, limits = [], [], [], [], []
        with socket.socket() as server:
            server.bind(("127.0.0.1", 0))
            server.listen()
            server.settimeout(60)
            released = False

            def release():
                nonlocal released
                if not released:
                    released = True
                    peer, _ = server.accept()
                    with peer, peer.makefile("rb") as ready:
                        assert ready.read(5) == b"ready"
                        peer.sendall(b"1")

            def stop_tree(pid):
                # Simulate the OS helper by releasing the actual descendant.
                # The leaf exits, its Python wrapper reaps it, then cmd exits.
                events.append("tree")
                assert pid == children[0].pid
                release()
                children[0].wait(timeout=60)
                return True

            def launch(command, *args, **kwargs):
                proc = real_popen(command, *args, **kwargs)
                children.append(proc)
                flags.append(kwargs)
                communicate, kill = proc.communicate, proc.kill
                first = True

                def expire(input=None, timeout=None):
                    nonlocal first
                    if first:
                        first = False
                        limits.append(timeout)
                        ready = json.loads(proc.stdout.readline())
                        descendants.extend([ready["parent"], ready["leaf"]])
                        raise subprocess.TimeoutExpired(argv, timeout)
                    assert "tree" in events, "must clean descendants before collecting inherited pipes"
                    return communicate(input=input, timeout=timeout)

                def direct_kill():
                    events.append("direct")
                    return kill()

                proc.communicate, proc.kill = expire, direct_kill
                return proc

            p = Paths(self.hub)
            try:
                with mock.patch.dict(os.environ, {"FAKE_ARCHIVE_RELEASE": json.dumps(server.getsockname())}), \
                     mock.patch.object(archive.subprocess, "Popen", side_effect=launch), \
                     mock.patch.object(archive, "kill_tree", side_effect=stop_tree):
                    with sessionguard.lock(p):
                        rc, message = archive._run(argv)
                assert rc == -1 and "timed out" in message
                assert limits == [30]
                assert events == ["tree", "direct"]
                assert len(children) == 1 and children[0].poll() is not None
                assert flags[0].items() >= runners.group_flags().items()
                if os.name == "nt":
                    assert all(not runners.pid_alive(pid) for pid in descendants)
                with sessionguard.lock(p, timeout=0):
                    pass
            finally:
                if descendants:
                    release()
                for child in children:
                    if child.poll() is None:
                        child.kill()
                    child.wait(timeout=60)
