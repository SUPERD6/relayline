from datetime import datetime

import pytest

from cronlite import CronError, Registry


def test_due_lists_matching_jobs_in_name_order():
    r = Registry()
    r.add("b", "0 * * * *")
    r.add("a", "0 * * * *")
    r.add("c", "30 * * * *")
    assert r.due(datetime(2026, 1, 1, 5, 0, 12)) == ["a", "b"]


def test_duplicate_name():
    r = Registry()
    r.add("a", "* * * * *")
    with pytest.raises(CronError):
        r.add("a", "* * * * *")


def test_retry_after_fixed_delay():
    r = Registry()
    r.add("sync", "0 0 * * *", retries=2, retry_delay=10)
    at = datetime(2026, 1, 1, 0, 0)
    assert r.record_failure("sync", at) == datetime(2026, 1, 1, 0, 10)
    assert r.due(datetime(2026, 1, 1, 0, 10)) == ["sync"]
    assert r.record_failure("sync", datetime(2026, 1, 1, 0, 10)) == datetime(2026, 1, 1, 0, 20)
    assert r.record_failure("sync", datetime(2026, 1, 1, 0, 20)) is None


def test_success_resets():
    r = Registry()
    r.add("x", "0 0 * * *", retries=1)
    r.record_failure("x", datetime(2026, 1, 1))
    r.record_success("x")
    assert r.jobs["x"].retry_at is None and r.jobs["x"].attempts == 0


def test_invalid_options():
    with pytest.raises(CronError):
        Registry().add("x", "* * * * *", retry_delay=0)
