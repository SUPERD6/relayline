"""scripts/eval/long_environment (issue #359): a baseline or hidden check that times out ends the whole process tree,
not only the shell. The repo is a scratch one whose only test starts a grandchild and hangs; no real CLI is started."""
from pathlib import Path
import subprocess
import sys
import time

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/eval"))
import long_environment as L  # noqa: E402
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


def gone(pids: list[int], wait: float = 10) -> list[int]:
    """The pids still alive after up to `wait` seconds."""
    deadline = time.monotonic() + wait
    left = [p for p in pids if PF.alive(p)]
    while left and time.monotonic() < deadline:
        time.sleep(.5)
        left = [p for p in left if PF.alive(p)]
    return left


@pytest.mark.parametrize("which", ["baseline", "hidden"])
def test_timeout_ends_pytest_and_its_children(tmp_path, which):
    repo = tmp_path / "repo"
    repo.mkdir()
    pids_file = tmp_path / "pids"
    (repo / "test_hang.py").write_text(HANG.format(pids=str(pids_file)), encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    pids = []
    t0 = time.monotonic()
    try:
        if which == "baseline":
            out = L.baseline(repo, sys.executable, repo / ".ccx-eval-tmp-acceptance", timeout=10)
        else:
            out = L.hidden(repo, ["test_hang.py"], sys.executable, timeout=10)
        elapsed = time.monotonic() - t0
        assert out["rc"] is None and out["summary"] == f"{which} timeout"
        assert pids_file.exists(), "the test never got going before the timeout"
        pids = [int(x) for x in pids_file.read_text().split()]
        assert len(set(pids)) == 2
        assert gone(pids) == [], "pytest or its child left after the timeout"
        assert elapsed < 45, "the call waited for pytest to finish instead of ending it"
    finally:                    # never leave a stray process behind, even when an assertion above failed
        if not pids and pids_file.exists():
            pids = [int(x) for x in pids_file.read_text().split()]
        PF.kill([p for p in pids if PF.alive(p)])
