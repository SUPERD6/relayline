from datetime import datetime

import pytest

from cronlite import CronError, CronExpr, Registry, next_run

T0 = datetime(2026, 5, 4, 3, 0)


def test_delays_grow_and_are_capped():
    r = Registry()
    job = r.add("pull", "0 3 * * *", retries=5, retry_delay=3, backoff=2.5, max_delay=20)
    assert [job.delay(k) for k in range(1, 6)] == [3, 7, 18, 20, 20]


def test_failures_follow_backoff():
    r = Registry()
    r.add("pull", "0 3 * * *", retries=3, retry_delay=4, backoff=2)
    assert r.record_failure("pull", T0) == datetime(2026, 5, 4, 3, 4)
    assert r.record_failure("pull", datetime(2026, 5, 4, 3, 4, 30)) == datetime(2026, 5, 4, 3, 12)
    assert r.record_failure("pull", datetime(2026, 5, 4, 3, 12)) == datetime(2026, 5, 4, 3, 28)
    assert r.record_failure("pull", datetime(2026, 5, 4, 3, 28)) is None
    assert r.jobs["pull"].attempts == 0 and r.jobs["pull"].retry_at is None


def test_default_backoff_is_fixed_delay():
    r = Registry()
    job = r.add("x", "0 0 * * *", retries=3, retry_delay=6)
    assert [job.delay(k) for k in (1, 2, 3)] == [6, 6, 6]


def test_retry_dropped_when_schedule_comes_first():
    r = Registry()
    r.add("tick", "0,30 * * * *", retries=4, retry_delay=20, backoff=2)
    assert r.record_failure("tick", datetime(2026, 5, 4, 3, 0)) == datetime(2026, 5, 4, 3, 20)
    assert r.record_failure("tick", datetime(2026, 5, 4, 3, 20)) is None   # 3:60 is not before the 3:30 run
    assert r.jobs["tick"].attempts == 0
    assert r.record_failure("tick", datetime(2026, 5, 4, 3, 30)) == datetime(2026, 5, 4, 3, 50)


def test_retry_equal_to_schedule_also_dropped():
    r = Registry()
    r.add("q", "0,10,20,30,40,50 * * * *", retries=1, retry_delay=10)
    assert r.record_failure("q", T0) is None


def test_due_lists_each_job_once():
    r = Registry()
    r.add("a", "* * * * *", retries=1, retry_delay=1)
    r.jobs["a"].retry_at = datetime(2026, 5, 4, 2, 59)   # a pending retry on a minute the schedule also matches
    r.add("b", "0 3 * * *")
    assert r.due(datetime(2026, 5, 4, 2, 59)) == ["a"]


def test_next_due():
    r = Registry()
    assert r.next_due(T0) is None
    r.add("night", "0 4 * * *", retries=2, retry_delay=15)
    r.add("half", "30 * * * *")
    assert r.next_due(T0) == (datetime(2026, 5, 4, 3, 30), ["half"])
    r.record_failure("night", datetime(2026, 5, 4, 3, 0))
    assert r.next_due(T0) == (datetime(2026, 5, 4, 3, 15), ["night"])


def test_next_run_helper():
    e = CronExpr.parse("0 * * * *")
    assert next_run(e, T0) == datetime(2026, 5, 4, 4, 0)
    assert next_run(e, T0, datetime(2026, 5, 4, 3, 40)) == datetime(2026, 5, 4, 3, 40)
    assert next_run(e, T0, datetime(2026, 5, 4, 2, 0)) == datetime(2026, 5, 4, 4, 0)


def test_invalid_backoff_options():
    with pytest.raises(CronError):
        Registry().add("bad", "* * * * *", backoff=0.5)
    with pytest.raises(CronError):
        Registry().add("bad", "* * * * *", retry_delay=10, max_delay=5)
