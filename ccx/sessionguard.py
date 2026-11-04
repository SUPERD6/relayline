"""Serialize archival with restoration and publication of a continuing run."""
from contextlib import ExitStack, contextmanager
from threading import local

from .ability import _lock

_held = local()


@contextmanager
def lock(p, timeout=60):
    key = p.state.resolve()
    held = getattr(_held, "paths", set())
    if key in held:
        yield
        return
    with _lock(p, name="archive.lock", timeout=timeout):
        _held.paths = held | {key}
        try:
            yield
        finally:
            _held.paths = held


def guarded(fn):
    from functools import wraps
    @wraps(fn)
    def call(p, *args, **kwargs):
        with lock(p):
            return fn(p, *args, **kwargs)
    return call


def start(p, record, publish):
    """Serialize resume startup when possible; a busy archive must not fail work."""
    from . import archive
    if not record.get("session_id"):
        publish()
        return
    with ExitStack() as scope:
        try:
            scope.enter_context(lock(p))
        except TimeoutError:
            record["archive_restore_lock_timeout"] = True
            # Fall back to the original unsynchronized, best-effort restore.
            # Nested bring_back/restore guards must not wait for the same lock
            # again. Restore the thread-local state even when publish fails.
            held = getattr(_held, "paths", set())
            _held.paths = held | {p.state.resolve()}
            scope.callback(setattr, _held, "paths", held)
        if record.get("session_id"):
            try:
                archive.bring_back(p, record["session_id"])
            except Exception:  # preserve the resume's existing best-effort restoration
                pass
        publish()


def running_sessions(p):
    from . import ledger
    sessions = set()
    for f in p.runs.glob("*/run.json"):
        try:
            record = ledger.read_record(f)
        except (OSError, ValueError):
            continue
        if record.get("state") == "running":
            if record.get("session_id"):
                sessions.add(record["session_id"])
            sessions.update(a["session_id"] for a in record.get("attempts", []) if a.get("session_id"))
    return sessions
