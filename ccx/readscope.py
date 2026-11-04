"""Ledger snapshots live for one report call, never across calls or processes."""
from contextvars import ContextVar
from functools import wraps

_rows = ContextVar("ccx_report_rows", default=None)


def read(path, loader):
    cache = _rows.get()
    if cache is None:
        return loader()
    key = path.resolve()
    if key not in cache:
        cache[key] = loader()
    return cache[key]


def once(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if _rows.get() is not None:
            return fn(*args, **kwargs)
        token = _rows.set({})
        try:
            return fn(*args, **kwargs)
        finally:
            _rows.reset(token)
    return wrapped
