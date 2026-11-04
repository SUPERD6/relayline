"""Bounded process-local cache of Codex discovery headers, invalidated by stat."""
from __future__ import annotations

import json
from functools import lru_cache


@lru_cache(maxsize=256)
def _header(path, stamp):
    with path.open(encoding="utf-8", errors="replace") as fh:
        return (json.loads(fh.readline()) or {}).get("payload") or {}


def header(path):
    st = path.stat()
    return _header(path, (st.st_mtime_ns, st.st_size, st.st_ino, st.st_ctime_ns))
