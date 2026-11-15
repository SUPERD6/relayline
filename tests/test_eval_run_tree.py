"""scripts/eval/common.run_tree (issue #332): subprocess.run's results, but a timeout ends the whole process tree.
Only Python child processes; no real CLI is started."""
from pathlib import Path
import subprocess
import sys
import threading
import time
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/eval"))
import common  # noqa: E402
import preflight as PF  # noqa: E402

# A parent that starts a grandchild (POSIX: in a session of its own, as ccx starts its CLI), writes both pids, says
# so on stdout and stderr, then hangs. The grandchild hangs too.
TREE = r"""
import os, subprocess, sys, time
kw = {} if os.name == "nt" else {"start_new_session": True}
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"], **kw)
open(sys.argv[1], "w").write(f"{os.getpid()} {child.pid}")
print("started", flush=True)
print("on stderr", file=sys.stderr, flush=True)
time.sleep(120)
"""


def test_run_tree_returns_what_subprocess_run_did(tmp_path):
    code = "import sys; d = sys.stdin.read(); print(d.upper()); print('é', file=sys.stderr); sys.exit(3)"
    r = common.run_tree([sys.executable, "-X", "utf8", "-c", code], input="hi", cwd=tmp_path, timeout=60)
    assert isinstance(r, subprocess.CompletedProcess)
    assert (r.returncode, r.stdout.strip(), r.stderr.strip()) == (3, "HI", "é")
    r = common.run_tree([sys.executable, "-c", "import sys; print(repr(sys.stdin.read()))"], timeout=60)
    assert r.stdout.strip() == "''"         # no input: stdin is empty (DEVNULL), never the caller's terminal


def test_run_tree_timeout_ends_the_whole_tree(tmp_path):
    pids_file = tmp_path / "pids"
    pids = []
    try:
        with pytest.raises(subprocess.TimeoutExpired) as caught:
            common.run_tree([sys.executable, "-c", TREE, str(pids_file)], cwd=tmp_path, timeout=10)
        assert pids_file.exists(), "the tree never got going before the timeout"
        pids = [int(x) for x in pids_file.read_text().split()]
        assert len(set(pids)) == 2
        assert gone(pids) == [], "processes left after the timeout"
        # as with subprocess.run, the exception carries what was read so far (as text: text mode)
        assert "started" in (caught.value.stdout or "") and "on stderr" in (caught.value.stderr or "")
    finally:                    # never leave a stray process behind, even when an assertion above failed
        if not pids and pids_file.exists():
            pids = [int(x) for x in pids_file.read_text().split()]
        PF.kill([p for p in pids if PF.alive(p)])


def gone(pids: list[int], wait: float = 10) -> list[int]:
    """The pids still alive after up to `wait` seconds."""
    deadline = time.monotonic() + wait
    left = [p for p in pids if PF.alive(p)]
    while left and time.monotonic() < deadline:
        time.sleep(.5)
        left = [p for p in left if PF.alive(p)]
    return left


def test_stop_running_ends_trees_in_worker_threads(tmp_path):
    """Review of #332: the child runs in a group of its own and no longer gets the terminal's Ctrl+C, so a run_tree
    in a worker thread is ended by stop_running(); that worker raises KeyboardInterrupt, and so does a later call."""
    pids_file = tmp_path / "pids"
    seen, pids = [], []
    def work():
        try:
            common.run_tree([sys.executable, "-c", TREE, str(pids_file)], cwd=tmp_path, timeout=120)
            seen.append("returned")
        except BaseException as exc:            # noqa: BLE001 — the test records what the worker got
            seen.append(type(exc).__name__)
    worker = threading.Thread(target=work)
    try:
        worker.start()
        deadline = time.monotonic() + 30
        while not pids_file.exists() and time.monotonic() < deadline:
            time.sleep(.2)
        assert pids_file.exists(), "the tree never got going"
        time.sleep(.5)                          # the file is written before the pids are read back: let it finish
        pids = [int(x) for x in pids_file.read_text().split()]
        assert common.stop_running() == 1
        worker.join(60)
        assert not worker.is_alive() and seen == ["KeyboardInterrupt"]
        assert gone(pids) == [], "processes left after stop_running"
        with pytest.raises(KeyboardInterrupt):
            common.run_tree([sys.executable, "-c", "pass"], timeout=60)
    finally:
        common._STOPPING.clear()
        PF.kill([p for p in pids if PF.alive(p)])
        worker.join(60)


def test_map_stopping_on_ctrl_c_drops_the_queue_and_stops_the_trees(monkeypatch):
    stopped, ex = [], mock.Mock()
    ex.map.side_effect = KeyboardInterrupt
    monkeypatch.setattr(common, "stop_running", lambda: stopped.append(1))
    with pytest.raises(KeyboardInterrupt):
        common.map_stopping(ex, str, [1, 2])
    ex.shutdown.assert_called_once_with(wait=False, cancel_futures=True)
    assert stopped == [1]
    ex = mock.Mock()
    ex.map.side_effect = ValueError("a worker failed")      # other errors: as list(ex.map(...)), nothing stopped
    with pytest.raises(ValueError):
        common.map_stopping(ex, str, [1])
    assert stopped == [1] and not ex.shutdown.called
    ex.map.side_effect, ex.map.return_value = None, iter(["1", "2"])
    assert common.map_stopping(ex, str, [1, 2]) == ["1", "2"]


def test_eval_scripts_use_run_tree_for_their_timed_calls():
    """The 20 call sites of issue #332 (and strength_runner) go through common.run_tree, not subprocess.run."""
    sites = {"c2_lead_accept.py": 1, "f9_subagents.py": 1, "r2.py": 1, "seven_ab.py": 1, "seven_func.py": 2,
             "shared_context_ab.py": 2, "preflight_e2e.py": 1, "common.py": 1, "e8_handoff.py": 1,
             "j0_baseline.py": 1, "r3.py": 1, "r4.py": 3, "harness_audit.py": 1, "p2_review_replay.py": 1,
             "review_replay.py": 1, "rereview_replay.py": 1, "strength_runner.py": 2}
    for name, n in sites.items():
        text = (ROOT / "scripts/eval" / name).read_text(encoding="utf-8")
        calls = text.count("run_tree(") - text.count("def run_tree(")
        assert calls == n, (name, calls)
    for name in ("shared_context_ab.py", "r4.py", "review_replay.py", "rereview_replay.py"):   # threaded: Ctrl+C
        text = (ROOT / "scripts/eval" / name).read_text(encoding="utf-8")
        assert "map_stopping(ex, " in text and "list(ex.map(" not in text, name
