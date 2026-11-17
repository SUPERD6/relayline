"""Shared by the timeout tests of scripts/eval (#359, #391): a pytest test that starts a grandchild and hangs, and the
checks that a timed-out call ended pytest and the grandchild. No real CLI is started."""
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/eval"))
import preflight as PF  # noqa: E402

# The test pytest runs: starts a grandchild (no pipes of ours), writes both pids, then hangs longer than the timeout.
HANG = """
import os, subprocess, sys, time

def test_hang():
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"], stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    open({pids!r}, "w").write(f"{{os.getpid()}} {{child.pid}}")
    time.sleep(60)
"""


def hang_source(pids_file: Path) -> str:
    return HANG.format(pids=str(pids_file))


def gone(pids: list[int], wait: float = 10) -> list[int]:
    """The pids still alive after up to `wait` seconds."""
    deadline = time.monotonic() + wait
    left = [p for p in pids if PF.alive(p)]
    while left and time.monotonic() < deadline:
        time.sleep(.5)
        left = [p for p in left if PF.alive(p)]
    return left


def run_and_check_tree_ended(pids_file: Path, call, limit: float = 45):
    """Run `call()` (a timed check over the hanging test); assert pytest and its child are gone and the call did not
    wait for the test to finish. Returns the call's result for further asserts. Only the pids the test wrote are
    killed on the way out, never by name."""
    pids: list[int] = []
    t0 = time.monotonic()
    try:
        out = call()
        elapsed = time.monotonic() - t0
        assert pids_file.exists(), "the test never got going before the timeout"
        pids = [int(x) for x in pids_file.read_text().split()]
        assert len(set(pids)) == 2
        assert gone(pids) == [], "pytest or its child left after the timeout"
        assert elapsed < limit, "the call waited for pytest to finish instead of ending it"
        return out
    finally:                    # never leave a stray process behind, even when an assertion above failed
        if not pids and pids_file.exists():
            pids = [int(x) for x in pids_file.read_text().split()]
        PF.kill([p for p in pids if PF.alive(p)])
