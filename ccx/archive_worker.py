"""Windowless, detached session-start housekeeping. No model calls."""
from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path


def schedule(p) -> bool:
    """Best effort: no waiting for archival, no inherited pipes or console."""
    if os.environ.get("CCX_NO_START_ARCHIVE") == "1":
        return False
    from .winproc import BACKGROUND
    try:
        from .config import Paths
        p = Paths(p.hub.resolve())
        p.state.mkdir(parents=True, exist_ok=True)
        child = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), str(p.hub)],
                                 cwd=p.state, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, close_fds=True, **BACKGROUND)
        # A long-lived caller reaps its child; an exiting hook never waits for
        # this daemon thread. A child orphaned on POSIX is reaped by its adopter.
        threading.Thread(target=child.wait, name="ccx-archive-reaper", daemon=True).start()
        return True
    except (OSError, RuntimeError):
        return False


def run(p) -> int:
    from ccx.sessionguard import lock
    from ccx.archive import auto
    try:
        # Reuse the OS lock implementation, with an independent lock file.
        # A live worker is never displaced by a stale timestamp. A crash frees
        # the OS lock; a second worker skips instead of queuing duplicate work.
        with lock(p, timeout=0):
            return auto(p)
    except (OSError, TimeoutError):
        return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ccx.config import Paths
    from ccx.winproc import install
    install()
    try:
        run(Paths(Path(sys.argv[1])))
    except Exception:  # housekeeping must never affect the hook's output
        pass
