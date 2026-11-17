"""scripts/eval/long_check.check_tree (issue #391): a pytest run that times out ends the whole process tree,
not only pytest. The tree is a scratch one whose only test starts a grandchild and hangs; no real CLI is started."""
import io
from pathlib import Path
import sys
import tarfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/eval"))
import long_check as LC  # noqa: E402
import preflight as PF  # noqa: E402

HANG = """
import os, subprocess, sys, time

def test_hang():
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"], stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    open({pids!r}, "w").write(f"{{os.getpid()}} {{child.pid}}")
    time.sleep(60)
"""


def gone(pids, wait=10):
    deadline = time.monotonic() + wait
    left = [p for p in pids if PF.alive(p)]
    while left and time.monotonic() < deadline:
        time.sleep(.5)
        left = [p for p in left if PF.alive(p)]
    return left


def test_check_tree_timeout_ends_pytest_and_its_children(tmp_path):
    pids_file = tmp_path / "pids"
    buf = io.BytesIO()
    body = HANG.format(pids=str(pids_file)).encode("utf-8")
    with tarfile.open(fileobj=buf, mode="w") as tf:
        info = tarfile.TarInfo("test_hang.py")
        info.size = len(body)
        tf.addfile(info, io.BytesIO(body))
    pids = []
    t0 = time.monotonic()
    try:
        out = LC.check_tree(buf.getvalue(), {}, ["test_hang.py"], sys.executable, tmp_path / "work", timeout=10)
        elapsed = time.monotonic() - t0
        assert out == {"rc": None, "summary": "timeout"}
        assert pids_file.exists(), "the test never got going before the timeout"
        pids = [int(x) for x in pids_file.read_text().split()]
        assert len(set(pids)) == 2
        assert gone(pids) == [], "pytest or its child left after the timeout"
        assert elapsed < 45, "the call waited for pytest to finish instead of ending it"
    finally:
        if not pids and pids_file.exists():
            pids = [int(x) for x in pids_file.read_text().split()]
        PF.kill([p for p in pids if PF.alive(p)])
