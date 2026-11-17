"""scripts/eval/common.run_tree (issue #332): subprocess.run's results, but a timeout ends the whole process tree.
Only Python child processes; no real CLI is started."""
from pathlib import Path
import subprocess
from concurrent.futures import ThreadPoolExecutor
import random
import signal
import sys
import threading
import time
import traceback

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


def test_map_stopping_returns_and_raises_as_ex_map(monkeypatch):
    stopped = []
    monkeypatch.setattr(common, "stop_running", lambda: stopped.append(1))
    def slow_str(x):
        time.sleep(.05 * (3 - x))               # finish out of order: results still come back in order
        return str(x)
    with ThreadPoolExecutor(3) as ex:
        assert common.map_stopping(ex, slow_str, [0, 1, 2]) == ["0", "1", "2"]
    def fail(x):
        if x:
            raise ValueError(x)
        return x
    with ThreadPoolExecutor(2) as ex:           # other errors: raised as list(ex.map(...)) would, nothing stopped
        with pytest.raises(ValueError):
            common.map_stopping(ex, fail, [0, 1])
    assert stopped == []


def _shutdown_within(ex, seconds):
    """ex.shutdown(wait=True), but bounded: a worker still alive after `seconds` fails the test with every thread's
    stack instead of hanging the whole run (issue #373: a stuck worker held the suite for hours)."""
    ex.shutdown(wait=False)
    deadline = time.monotonic() + seconds
    threads = list(ex._threads)
    for th in threads:
        th.join(max(0, deadline - time.monotonic()))
    alive = [th for th in threads if th.is_alive()]
    if alive:
        frames = sys._current_frames()
        stacks = "\n".join(f"--- {th.name}\n" + "".join(traceback.format_stack(frames[th.ident]))
                           for th in alive if th.ident in frames)
        _release_stuck_condition_locks(alive, frames)
        pytest.fail(f"{len(alive)} worker thread(s) still running {seconds} s after shutdown:\n{stacks}")


def _release_stuck_condition_locks(threads, frames):
    """A worker blocked entering a threading.Condition waits for a lock a Ctrl+C left held in the main thread. Release
    it, so the failing test does not also hang the interpreter's exit, which joins the executor's workers."""
    for th in threads:
        frame = frames.get(th.ident)
        while frame is not None:
            cond = frame.f_locals.get("self")
            if frame.f_code.co_name == "__enter__" and isinstance(cond, threading.Condition):
                try:
                    cond._lock.release()
                except RuntimeError:            # not held, or held by another thread: nothing to do here
                    pass
                break
            frame = frame.f_back
    for th in threads:
        th.join(5)


def test_map_stopping_gets_ctrl_c_while_workers_run(monkeypatch):
    """Review of #332: on Windows an untimed wait on a future lets no Ctrl+C through until that work item ends; with
    timed waits the KeyboardInterrupt comes at once, the queue is dropped and stop_running() is called."""
    stopped, started = [], []
    monkeypatch.setattr(common, "stop_running", lambda: stopped.append(time.monotonic()))
    def hang(x):
        started.append(x)
        time.sleep(8)
    ex = ThreadPoolExecutor(2)
    timer = threading.Timer(1, signal.raise_signal, (signal.SIGINT,))
    t0 = time.monotonic()
    try:
        timer.start()
        with pytest.raises(KeyboardInterrupt):
            common.map_stopping(ex, hang, range(6))
        assert stopped and stopped[0] - t0 < 5, "Ctrl+C was held until a work item ended"
    finally:
        timer.cancel()
        _shutdown_within(ex, 30)                # the 2 running items end after 8 s
    assert len(started) == 2                    # the 4 queued items were dropped


def test_map_stopping_ctrl_c_leaves_no_future_locked(monkeypatch):
    """Issue #373: the Ctrl+C arrives at a random moment of the wait loop. It used to land, now and then, while the main
    thread held a future's lock inside concurrent.futures.wait; that lock was never released, the worker finishing
    that future blocked in set_result for good and shutdown(wait=True) never returned. Many short items and a Ctrl+C
    at a random moment make that moment likely. The Ctrl+C is armed by a work item once every item is submitted, so it
    falls in map_stopping's wait loop, not in this test's own ex.submit calls, and comes a few ms later, while later
    items are finishing (from inside the item the main thread would be woken by that item and catch it at a safe
    point)."""
    monkeypatch.setattr(common, "stop_running", lambda: 0)
    rng = random.Random(373)
    deadline = time.monotonic() + 6
    rounds = 0
    while time.monotonic() < deadline:
        submitted, ctrl_c_at = threading.Event(), rng.randrange(20, 80)
        timer = threading.Timer(rng.uniform(.002, .012), signal.raise_signal, (signal.SIGINT,))
        def item(i):
            if i == ctrl_c_at:
                submitted.wait(10)
                timer.start()
            time.sleep(.0005)
        def items():
            yield from range(200)
            submitted.set()
        ex = ThreadPoolExecutor(2)
        try:
            with pytest.raises(KeyboardInterrupt):
                common.map_stopping(ex, item, items())
        finally:
            if timer.is_alive():
                timer.join()
            _shutdown_within(ex, 10)
        rounds += 1
    assert rounds >= 10


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
