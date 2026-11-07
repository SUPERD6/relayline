"""Quiet SessionStart maintenance, independent of how much context is printed."""
from __future__ import annotations

import os


def maintain(p) -> None:
    """Keep the existing order, guards and failure isolation for startup upkeep."""
    from .hookbudget import check

    check()
    try:
        from .delegate import soft_verdicts
        soft_verdicts(p)
        from .ability import after_verdict
        after_verdict(p)
    except Exception:  # noqa: BLE001 — never break session start
        pass
    if os.environ.get("CCX_NO_START_ARCHIVE") != "1":
        try:
            check()
            from .archive_worker import schedule
            schedule(p)
        except Exception:  # noqa: BLE001
            pass
    try:
        check()
        from . import projects
        from .config import load_config
        projects.refresh_later(p, load_config(p))
    except Exception:  # noqa: BLE001
        pass
    if os.environ.get("CCX_NO_BENCH_REFRESH") != "1":
        check()
        try:
            from . import learn
            learn.refresh_benchmarks_later(p)
        except Exception:  # noqa: BLE001
            pass
