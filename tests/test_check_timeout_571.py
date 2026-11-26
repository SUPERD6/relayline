"""#571: a --check that hangs must be stopped at its timeout, grandchildren included."""
import os
import subprocess
import sys
import time

from ccx.runners import pid_alive
from ccx.workspace import run_check

PARENT = """\
import subprocess, sys, time
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
open("parent_571.pid", "w").write(str(__import__("os").getpid()))
open("grandchild_571.pid", "w").write(str(child.pid))
time.sleep(120)
"""


def test_timeout_fires_on_time_and_kills_grandchild(tmp_path):
    (tmp_path / "parent_571.py").write_text(PARENT, encoding="utf-8", newline="")
    grandchild = parent = None
    try:
        t0 = time.perf_counter()
        out = run_check(f'"{sys.executable}" parent_571.py', tmp_path, timeout=5)
        elapsed = time.perf_counter() - t0
        pid_file = tmp_path / "grandchild_571.pid"
        assert pid_file.is_file(), "the check never started its grandchild"
        grandchild = int(pid_file.read_text())
        parent = int((tmp_path / "parent_571.pid").read_text())
        assert out["exit"] == -1 and not out["passed"] and "timed out" in out["tail"]
        assert 5 <= elapsed < 20, elapsed          # not the 120 s the grandchild would have taken
        for _ in range(50):                        # the kernel needs a moment to reap it
            if not pid_alive(grandchild):
                break
            time.sleep(0.1)
        assert not pid_alive(grandchild) and not pid_alive(parent)
    finally:
        for pid in (grandchild, parent):           # our own recorded pids, cleaned up if the assertion failed
            if pid and pid_alive(pid):
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
                else:
                    os.kill(pid, 9)
