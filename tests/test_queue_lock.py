"""The queue lock on Windows: creating a lock file that was just unlinked is denied (PermissionError, the file is
"delete pending"), not FileExistsError. That used to escape `_lock`, so a `q run` item came back as an error row
without its run (tests/test_lanes.py::test_queue_default_is_unchanged, KeyError: 'run' on Windows CI; the likely
cause, not reproduced locally). Also: the lock never waits forever, a lasting denial fails at once, a fresh lock is
never taken over, a release removes only its own lock, and a `q run` row that fails after its run keeps the run."""
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from ccx import queue as wq
from ccx.commands import workqueue


def _tmp(case: unittest.TestCase) -> Path:
    d = Path(tempfile.mkdtemp())
    case.addCleanup(shutil.rmtree, d, ignore_errors=True)
    return d


MONO_OFFSET = 10 ** 6       # the fake time.monotonic is this far behind the fake time.time
PAUSE_MAX = 0.05            # the longest sleep of the lock's retry loop with its jitter fixed at 0.5
EPS = 1e-9


class TestLockRetries(unittest.TestCase):
    def setUp(self):
        self.root = _tmp(self)
        self.lock = wq.qdir(self.root) / "queue.lock"

    def flaky_open(self, fails, only_lock=True):
        real, n = os.open, {"left": fails}

        def fake(path, *a, **k):
            mine = Path(path) == self.lock if only_lock else Path(path).parent == wq.qdir(self.root)
            if mine and n["left"] > 0:
                n["left"] -= 1
                raise PermissionError(13, "Permission denied", str(path))
            return real(path, *a, **k)
        return fake

    def in_thread(self, fn, wait=5.0):
        out = {}

        def go():
            try:
                fn()
                out["ok"] = True
            except Exception as e:  # noqa: BLE001
                out["err"] = e
        th = threading.Thread(target=go, daemon=True)
        th.start()
        th.join(wait)
        self.assertFalse(th.is_alive(), "the lock kept waiting")
        return out

    def _clock(self, stack, start=None, on_sleep=None):
        """ccx.queue's time on a fake clock: it moves only when the lock sleeps (or a fake wait moves it), so how slow
        the runner is changes nothing, and time.time and time.monotonic move in step. On the wall clock they do not:
        PR #222's CI (windows 3.11) measured 0.298 s with time.time across a wait that _stale had counted as more than
        0.3 s on time.monotonic. monotonic stays a different number (MONO_OFFSET behind), so code that compares it with
        an mtime fails here as it would for real. The jitter is fixed (random() = 0.5): each sleep is the pause itself,
        at most PAUSE_MAX. Starts at the real time unless told, so files written just now are just now on it; it can run
        ahead of the real time (a release that retries for 2 s), so judge staleness only by mtimes set on it.
        on_sleep(clock) runs after each sleep (others acting while this waiter sleeps). -> the clock (now, first,
        sleeps, calls)."""
        clock = SimpleNamespace(now=time.time() if start is None else start, first=None, sleeps=0, calls=0)

        def now():
            clock.calls += 1                           # a retry loop that never sleeps would never reach a deadline
            self.assertLess(clock.calls, 10 ** 5, "the lock kept retrying without sleeping")
            return clock.now

        def sleep(s):
            if clock.first is None:
                clock.first = clock.now
            clock.sleeps += 1
            clock.now += s
            if on_sleep:
                on_sleep(clock)
        stack.enter_context(mock.patch.object(wq, "time", SimpleNamespace(
            time=now, monotonic=lambda: now() - MONO_OFFSET, sleep=sleep, monotonic_ns=time.monotonic_ns)))
        stack.enter_context(mock.patch.object(wq, "random", SimpleNamespace(random=lambda: 0.5)))
        return clock

    def test_denied_create_is_retried_on_windows(self):
        with mock.patch.object(wq, "_WINDOWS", True), mock.patch("ccx.queue.os.open", self.flaky_open(3)):
            wq.update(self.root, "q1", status="doing")
        self.assertEqual(len(wq.load(self.root)["order"]), 0)          # an update of no item: written, ignored
        self.assertIn('"status": "doing"', (wq.qdir(self.root) / "queue.jsonl").read_text(encoding="utf-8"))
        self.assertFalse(self.lock.exists())

    def test_denied_create_raises_at_once_elsewhere(self):
        with ExitStack() as stack:
            clock = self._clock(stack)
            with mock.patch.object(wq, "_WINDOWS", False), mock.patch("ccx.queue.os.open", self.flaky_open(10 ** 6)):
                with self.assertRaises(PermissionError):
                    with wq._lock(self.root, timeout=10):
                        pass
        self.assertEqual(clock.sleeps, 0)

    def test_folder_not_writable_raises_at_once_on_windows(self):
        with ExitStack() as stack:         # the default timeout: no 2 * 10 s stall when no file can be created at all
            clock = self._clock(stack)
            with mock.patch.object(wq, "_WINDOWS", True), \
                    mock.patch("ccx.queue.os.open", self.flaky_open(10 ** 6, only_lock=False)):
                with self.assertRaises(PermissionError):
                    with wq._lock(self.root):
                        pass
        self.assertEqual(clock.sleeps, 0)

    def test_lasting_denial_of_the_lock_raises_after_the_deadline(self):
        with ExitStack() as stack:
            clock = self._clock(stack)
            t = clock.now
            with mock.patch.object(wq, "_WINDOWS", True), mock.patch("ccx.queue.os.open", self.flaky_open(10 ** 6)):
                with self.assertRaises(PermissionError):
                    with wq._lock(self.root, timeout=0.2):
                        pass
        self.assertGreaterEqual(clock.now - t, 0.4)
        self.assertLess(clock.now - t, 0.4 + PAUSE_MAX + EPS)
        wq.update(self.root, "q1", status="doing")     # the failed wait gave this process's turn back: writes work
        self.assertFalse(self.lock.exists())

    def test_lock_that_cannot_be_taken_over_does_not_hang(self):
        wq.qdir(self.root).mkdir(parents=True)
        self.lock.write_bytes(b"crashed")
        real = Path.unlink

        def unlink(p, *a, **k):            # held open by a hung writer (Windows): the takeover is denied
            if p == self.lock:
                raise PermissionError(13, "Permission denied", str(p))
            return real(p, *a, **k)
        with ExitStack() as stack:
            clock = self._clock(stack)
            old = clock.now - 100
            os.utime(self.lock, (old, old))
            t = clock.now
            with mock.patch.object(Path, "unlink", unlink):
                out = self.in_thread(lambda: wq._lock(self.root, timeout=0.2).__enter__())
        self.assertIsInstance(out.get("err"), PermissionError)
        self.assertGreaterEqual(clock.now - t, 0.4)
        self.assertLess(clock.now - t, 0.4 + PAUSE_MAX + EPS)

    @unittest.skipUnless(os.name == "nt", "a handle blocks deleting the file only on Windows")
    def test_real_open_handle_does_not_hang(self):
        wq.qdir(self.root).mkdir(parents=True)
        with ExitStack() as stack, open(self.lock, "w"):
            clock = self._clock(stack)
            old = clock.now - 100
            os.utime(self.lock, (old, old))
            t = clock.now
            out = self.in_thread(lambda: wq._lock(self.root, timeout=0.2).__enter__())
        self.assertIsInstance(out.get("err"), PermissionError)          # the deadline, not the fake clock's guard
        self.assertGreaterEqual(clock.now - t, 0.4)
        self.assertLess(clock.now - t, 0.4 + PAUSE_MAX + EPS)

    def test_fresh_lock_is_never_taken_over(self):
        wq.qdir(self.root).mkdir(parents=True)
        self.lock.write_bytes(b"another writer")

        def retake(clock):                 # taken again just now, every time this waiter looks (contention)
            os.utime(self.lock, (clock.now, clock.now))
        with ExitStack() as stack:
            clock = self._clock(stack, on_sleep=retake)
            os.utime(self.lock, (clock.now, clock.now))
            t = clock.now
            with self.assertRaises(RuntimeError):     # waited past timeout, but the lock is never old: no takeover
                with wq._lock(self.root, timeout=0.2):
                    pass
        self.assertGreaterEqual(clock.now - t, 0.4)
        self.assertLess(clock.now - t, 0.4 + PAUSE_MAX + EPS)  # after 2 * timeout without a change of hands
        self.assertEqual(self.lock.read_bytes(), b"another writer")

    def test_lock_from_the_future_is_taken_over_before_the_deadline(self):
        wq.qdir(self.root).mkdir(parents=True)
        self.lock.write_bytes(b"crashed, server clock ahead")
        with ExitStack() as stack:
            clock = self._clock(stack)
            new = clock.now + 3600         # clock skew on a shared folder, or a restored file: mtime never "old"
            os.utime(self.lock, (new, new))
            t = clock.now
            with wq._lock(self.root, timeout=0.3):    # unchanged for > timeout as this waiter watched it: taken over
                pass
        self.assertGreaterEqual(clock.now - t, 0.3)
        self.assertLess(clock.now - t, 0.3 + PAUSE_MAX + EPS)  # the first look after timeout, not 2 * timeout
        self.assertFalse(self.lock.exists())
        wq.update(self.root, "q1", status="doing")                     # and later writes work again
        self.assertFalse(self.lock.exists())

    def test_unmarked_lock_is_released_only_while_still_unmarked(self):
        def no_write(fd, data):
            raise OSError(28, "No space left on device")
        with mock.patch("ccx.queue.os.write", no_write):
            with wq._lock(self.root, timeout=5):
                pass
        self.assertFalse(self.lock.exists())                            # ours (still empty): released
        with mock.patch("ccx.queue.os.write", no_write):
            with wq._lock(self.root, timeout=5):
                self.lock.write_bytes(b"the writer that took it over")
        self.assertEqual(self.lock.read_bytes(), b"the writer that took it over")

    def test_stale_lock_is_taken_over_at_once(self):
        wq.qdir(self.root).mkdir(parents=True)
        self.lock.write_bytes(b"crashed")
        with ExitStack() as stack:
            clock = self._clock(stack)
            old = clock.now - 100
            os.utime(self.lock, (old, old))
            with wq._lock(self.root, timeout=5):
                pass
        self.assertEqual(clock.sleeps, 0)
        self.assertFalse(self.lock.exists())

    def test_release_leaves_a_lock_that_is_no_longer_ours(self):
        with wq._lock(self.root, timeout=5):
            self.lock.write_bytes(b"the writer that took it over")
        self.assertEqual(self.lock.read_bytes(), b"the writer that took it over")

    def test_denied_release_is_retried_and_never_fails_the_write(self):
        real, n = Path.unlink, {"left": 2}

        def unlink(p, *a, **k):
            if p == self.lock and n["left"] > 0:
                n["left"] -= 1
                raise PermissionError(13, "Permission denied", str(p))
            return real(p, *a, **k)
        with ExitStack() as stack:                     # its retries sleep on the fake clock, not for 2 s
            clock = self._clock(stack)
            with mock.patch.object(Path, "unlink", unlink):
                wq.update(self.root, "q1", status="doing")
            self.assertFalse(self.lock.exists())
            self.assertEqual(clock.sleeps, 2)                              # one short wait per denial
            with mock.patch.object(Path, "unlink", lambda p, *a, **k: (_ for _ in ()).throw(PermissionError(13, "x"))):
                wq.update(self.root, "q1", status="done")                  # the release keeps failing: still no raise
            self.assertTrue(self.lock.exists())
            self.assertEqual(clock.sleeps, 2 + 100)                        # it kept trying (about 2 s) first
            old = clock.now - 100
            os.utime(self.lock, (old, old))
            with wq._lock(self.root, timeout=0.2):                         # left behind: taken over once stale
                pass

    def _many_threads(self, n, t):
        errs = []

        def work():
            for _ in range(n):
                try:
                    wq.update(self.root, "q1", status="doing")
                except Exception as e:  # noqa: BLE001
                    errs.append(repr(e))
        ts = [threading.Thread(target=work) for _ in range(t)]
        for th in ts:
            th.start()
        for th in ts:
            th.join()
        self.assertEqual(errs, [])
        lines = (wq.qdir(self.root) / "queue.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), n * t)

    def test_threads_never_lose_a_write(self):
        # threads of one process take turns in-process first: this covers that path (fairness, no starvation)
        self._many_threads(150, 6)

    def test_threads_meeting_only_at_the_lock_file_never_lose_a_write(self):
        # each call its own in-process lock: the threads meet at the file, as processes do, and on Windows hit the
        # "delete pending" create race under thread contention
        with mock.patch("ccx.queue._local_lock", lambda lock: wq._Turns()):
            self._many_threads(60, 4)

    def test_processes_never_lose_a_write(self):
        # writers in separate processes meet only at the lock file (threads of one process take turns in-process)
        n, procs = 60, 4
        code = ("import sys; sys.path.insert(0, sys.argv[1]); from pathlib import Path; from ccx import queue as wq\n"
                "for _ in range(int(sys.argv[3])): wq.update(Path(sys.argv[2]), 'q1', status='doing')\n")
        repo = str(Path(__file__).resolve().parent.parent)
        ps = [subprocess.Popen([sys.executable, "-c", code, repo, str(self.root), str(n)],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(procs)]
        outs = [p.communicate(timeout=300) for p in ps]
        self.assertEqual([p.returncode for p in ps], [0] * procs, outs)
        lines = (wq.qdir(self.root) / "queue.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), n * procs)
        self.assertFalse(self.lock.exists())

    def test_holder_changes_with_a_new_writer_not_with_a_touch(self):
        d = wq.qdir(self.root)
        d.mkdir(parents=True)
        self.assertIsNone(wq._holder(self.lock))                       # none there
        self.lock.write_bytes(b"writer 1")
        first = wq._holder(self.lock)
        later = time.time() + 5
        os.utime(self.lock, (later, later))
        self.assertEqual(wq._holder(self.lock), first)                 # touched by its holder: the same one
        os.link(self.lock, d / "held")                                 # keep the old file alive: a new id
        self.lock.unlink()
        self.lock.write_bytes(b"writer 2")
        second = wq._holder(self.lock)
        self.assertNotEqual(second, first)                             # a new file: another writer
        self.lock.write_bytes(b"writer 3")                             # same id, another token (an inode reused at once)
        self.assertNotEqual(wq._holder(self.lock), second)

    def _busy_elsewhere(self, stack, seconds, every=0.02):
        """Other writers (as other processes would) on a fake clock: ccx.queue's time moves only when it sleeps or
        waits, so how slow the runner is changes nothing. The lock file is there and is replaced by a new holder (a new
        file, its own token) every `every` seconds of that clock, never absent; removed `seconds` after the waiter
        first sleeps. All on the waiter's own thread, so nothing races it. A real thread doing this raced the waiter on
        the wall clock: on PR #207's CI (windows 3.12) its last unlink met the waiter's read of the file (WinError 32),
        the thread died, the lock file stayed and stopped changing hands, and the waiter gave up after 2 * timeout.
        -> the clock (now, first, calls)."""
        d = wq.qdir(self.root)
        d.mkdir(parents=True, exist_ok=True)
        self.lock.write_bytes(b"another 0")

        def others(clock):
            if not self.lock.read_bytes().startswith(b"another"):
                return                                 # ours (a sleep in the release): leave it
            if clock.now - clock.first >= seconds:
                self.lock.unlink()                     # the others are done
                return
            n = int((clock.now - clock.first) / every)
            if n > clock.writers:                      # the next writer took it
                clock.writers = n
                tmp = d / "next"
                tmp.write_bytes(f"another {n}".encode())
                os.replace(tmp, self.lock)
        clock = self._clock(stack, start=1000.0, on_sleep=others)
        clock.writers = 0
        stack.enter_context(mock.patch("ccx.queue._stale", return_value=False))   # not a takeover test
        return clock

    def test_busy_lock_that_keeps_changing_hands_is_waited_for(self):
        # CI windows 3.12: a writer gave up after 2 * timeout in all while the others kept writing. The deadline
        # counts from the last time the lock changed hands, so only a lock that stays the same one fails
        with ExitStack() as stack:
            clock = self._busy_elsewhere(stack, 2.5)  # 5 * timeout: well past the old 2 * timeout limit
            with wq._lock(self.root, timeout=0.5):
                self.assertFalse(self.lock.read_bytes().startswith(b"another"))     # ours, after the others
        self.assertGreater(clock.writers, 100)        # it saw them come and go

    def test_lock_file_that_stops_changing_hands_fails_after_2x_timeout(self):
        with ExitStack() as stack:
            clock = self._busy_elsewhere(stack, 10 ** 6, every=10 ** 6)           # one writer, never done
            with self.assertRaises(RuntimeError):
                with wq._lock(self.root, timeout=0.5):
                    pass
        self.assertGreaterEqual(clock.now - clock.first, 1.0)
        self.assertLess(clock.now - clock.first, 1.2)

    def test_long_wait_in_process_does_not_eat_the_file_deadline(self):
        # a thread that queued behind its siblings for more than 2 * timeout, then met another process's lock file,
        # failed on its first poll: the file deadline counted from before the in-process wait
        timeout, queued = 0.5, 1.5
        with ExitStack() as stack:
            clock = self._busy_elsewhere(stack, 2.5)
            turns = wq._Turns()

            class Siblings:                            # the in-process turn changes hands every 0.05 s for `queued` s
                start = clock.now

                def acquire(self, timeout=-1):
                    clock.now += timeout
                    turns.n += max(1, int(timeout / 0.05))
                    return clock.now - self.start >= queued

                def release(self):
                    pass
            turns.lock = Siblings()
            stack.enter_context(mock.patch.object(wq, "_local_lock", return_value=turns))
            with wq._lock(self.root, timeout=timeout):
                self.assertFalse(self.lock.read_bytes().startswith(b"another"))
        self.assertGreater(clock.writers, 100)

    def test_thread_hung_holding_the_lock_fails_the_others_after_2x_timeout(self):
        with ExitStack() as stack:
            clock = self._clock(stack)
            turns = wq._Turns()

            class Hung:                                # held by a sibling that never lets go: no turn changes hands
                def acquire(self, timeout=-1):
                    clock.now += timeout
                    return False

                def release(self):
                    pass
            turns.lock = Hung()
            stack.enter_context(mock.patch.object(wq, "_local_lock", return_value=turns))
            t = clock.now
            with self.assertRaises(RuntimeError):
                with wq._lock(self.root, timeout=0.25):   # waits of 0.1 s: past 2 * timeout at the 6th, 0.6 s
                    pass
        self.assertGreaterEqual(clock.now - t, 0.5)
        self.assertLess(clock.now - t, 0.65)           # not MAX_WAIT_FACTOR * timeout (7.5 s)

    def test_probe_names_differ_within_one_clock_tick(self):
        # monotonic_ns is ~15 ms coarse on Windows before 3.13: two threads probing in one tick shared a name, and
        # one hit the other's deleted probe ("delete pending") and called a busy lock a folder it may not write
        d = wq.qdir(self.root)
        d.mkdir(parents=True)
        made, real = [], os.open

        def record(path, *a, **k):
            made.append(Path(path).name)
            return real(path, *a, **k)
        with mock.patch("ccx.queue.time.monotonic_ns", return_value=1), mock.patch("ccx.queue.os.open", record):
            self.assertTrue(wq._can_create(d))
            self.assertTrue(wq._can_create(d))
        self.assertEqual(len(set(made)), 2, made)


class TestFailedRow(unittest.TestCase):
    def test_error_row_says_status_and_why_even_if_the_write_back_fails(self):
        it = {"id": "q1", "brief": "look", "to": "codex", "mode": "read"}
        with mock.patch.object(workqueue, "resolve", side_effect=RuntimeError("boom")), \
                mock.patch.object(workqueue.wq, "update", side_effect=PermissionError(13, "denied")):
            row = workqueue._one(it, _tmp(self), "claude", SimpleNamespace(), {})
        self.assertEqual(row["status"], "failed")
        self.assertIn("RuntimeError: boom", row["error"])
        self.assertIn("PermissionError", row["not_recorded"])
        self.assertNotIn("run", row)                                   # nothing ran

    def test_failure_after_the_run_keeps_the_run_and_its_cost(self):
        root = _tmp(self)
        it = wq.add(root, "x", "look at x", to="codex", mode="read", minutes=5)
        it["cost_usd"] = 0.25
        rec = {"run_id": "r-1", "to": "codex", "ok": True, "result": "done"}
        with mock.patch.object(workqueue, "resolve", return_value=({"to": "codex"}, {})), \
                mock.patch.object(workqueue, "run", return_value=rec), \
                mock.patch.object(workqueue, "compact", return_value={"status": "done"}), \
                mock.patch.object(workqueue, "_cost", return_value=0.5), \
                mock.patch.object(workqueue, "_tree_fields", side_effect=RuntimeError("after the run")):
            row = workqueue._one(it, root, "claude", SimpleNamespace(), {})
        self.assertEqual((row["status"], row["run"]), ("failed", "r-1"))
        self.assertIn("after the run", row["error"])
        got = wq.load(root)["items"][it["id"]]
        self.assertEqual((got["status"], got["run"], got["agent"]), ("failed", "r-1", "codex"))
        self.assertAlmostEqual(got["cost_usd"], 0.75)
        self.assertAlmostEqual(wq.spent(wq.load(root)), 0.75)
        self.assertIsNone(got.get("live"))                             # no stale `live` for `ccx show --any --wait`

    def test_run_that_raises_keeps_the_run_it_was_started_as(self):
        root = _tmp(self)
        it = wq.add(root, "x", "look at x", to="codex", mode="read", minutes=5)
        p = SimpleNamespace(runs=root / "runs")
        seen = {}

        def boom(req, _p):
            seen["run_id"] = req.run_id
            raise RuntimeError("the run itself broke")
        with mock.patch.object(workqueue, "resolve", return_value=({"to": "codex"}, {})), \
                mock.patch.object(workqueue, "run", side_effect=boom):
            row = workqueue._one(it, root, "claude", p, {})
        self.assertEqual((row["status"], row["run"]), ("failed", seen["run_id"]))
        got = wq.load(root)["items"][it["id"]]
        self.assertEqual((got["status"], got["run"]), ("failed", seen["run_id"]))
        self.assertIsNone(got.get("live"))

    def test_run_that_raises_after_writing_its_record_keeps_its_cost(self):
        root = _tmp(self)
        it = wq.add(root, "x", "look at x", to="codex", mode="read", minutes=5)
        p = SimpleNamespace(runs=root / "runs")

        def boom(req, _p):
            d = p.runs / req.run_id
            d.mkdir(parents=True, exist_ok=True)      # as delegate.run: ledger.new_run_id made it already
            (d / "run.json").write_text('{"run_id": "%s", "to": "codex"}' % req.run_id, encoding="utf-8")
            raise RuntimeError("after the record")
        with mock.patch.object(workqueue, "resolve", return_value=({"to": "codex"}, {})), \
                mock.patch.object(workqueue, "run", side_effect=boom), \
                mock.patch.object(workqueue, "_cost", return_value=0.4):
            row = workqueue._one(it, root, "claude", p, {})
        got = wq.load(root)["items"][it["id"]]
        self.assertEqual((got["status"], got["run"], got["agent"]), ("failed", row["run"], "codex"))
        self.assertAlmostEqual(got["cost_usd"], 0.4)
        self.assertIsNone(got.get("live"))


if __name__ == "__main__":
    unittest.main()
