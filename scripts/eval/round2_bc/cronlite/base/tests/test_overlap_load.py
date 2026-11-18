from datetime import datetime, timedelta

import pytest

from cronlite import (CronError, CronExpr, JobLoad, busy_minutes, concurrency, occupancy, overloaded, peak,
                      simulate, summarize, utilization)

T = [datetime(2026, 1, 1, 0, m) for m in (0, 10, 20, 30)]
LONG = timedelta(minutes=15)


def test_allow_and_skip():
    allowed = simulate(T, LONG, "allow")
    assert concurrency(allowed) == 2 and summarize(allowed)["dropped"] == 0
    skipped = simulate(T, LONG, "skip")
    assert [p.dropped for p in skipped] == [False, True, False, True]


def test_queue():
    plan = simulate(T, LONG, "queue", max_queue=1)
    assert [(p.due.minute, p.start.minute if p.start else None) for p in plan] == [(0, 0), (10, 15), (20, 30),
                                                                                   (30, 45)]
    s = summarize(plan)
    assert s["delayed"] == 3 and s["max_delay_seconds"] == 900 and concurrency(plan) == 1


def test_queue_limit_drops():
    plan = simulate(T, timedelta(minutes=40), "queue", max_queue=1)
    assert sum(p.dropped for p in plan) == 2


def test_simulate_errors():
    with pytest.raises(CronError):
        simulate(T, LONG, "maybe")
    with pytest.raises(CronError):
        simulate(T, [LONG], "skip")
    with pytest.raises(CronError):
        simulate(T, -LONG, "skip")


def test_load():
    jobs = [JobLoad("a", CronExpr.parse("0,30 * * * *"), 20), JobLoad("b", CronExpr.parse("10 * * * *"), 15)]
    assert busy_minutes(jobs, datetime(2026, 1, 1, 15)) == {"a": 960, "b": 360}
    start, end = datetime(2026, 1, 1, 0, 0), datetime(2026, 1, 1, 1, 0)
    occ = occupancy(jobs, start, end)
    assert occ[datetime(2026, 1, 1, 0, 15)] == ["a", "b"]
    assert peak(jobs, start, end) == (2, datetime(2026, 1, 1, 0, 10))
    assert len(overloaded(jobs, start, end, 1)) == 10        # 00:10 to 00:19, both running
    assert utilization(jobs, start, end, workers=2) == pytest.approx(0.4583, abs=1e-4)
    with pytest.raises(CronError):
        JobLoad("z", CronExpr.parse("* * * * *"), 0)
    with pytest.raises(CronError):
        utilization(jobs, start, start)
