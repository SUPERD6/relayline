import json
from datetime import datetime

import pytest

from cronlite import CronError, Registry, dumps, loads, merge

AT = datetime(2026, 6, 1, 4, 0)


def test_tags_are_cleaned_and_sorted():
    r = Registry()
    job = r.add("backup", "0 4 * * *", tags=[" Storage", "nightly", "NIGHTLY"])
    assert job.tags == ("nightly", "storage")
    assert r.add("solo", "0 5 * * *", tags="Reports").tags == ("reports",)
    assert r.add("untagged", "0 6 * * *").tags == ()


@pytest.mark.parametrize("bad", [["two words"], [""], ["a_b"], [7]])
def test_bad_tags(bad):
    with pytest.raises(CronError):
        Registry().add("x", "* * * * *", tags=bad)


def test_tagged_lookup():
    r = Registry()
    r.add("b", "0 * * * *", tags=["ops"])
    r.add("a", "0 * * * *", tags=["ops", "db"], paused=True)
    r.add("c", "0 * * * *")
    assert r.tagged(" OPS ") == ["a", "b"]
    assert r.tagged("db") == ["a"] and r.tagged("web") == []


def test_paused_jobs_do_not_run():
    r = Registry()
    r.add("a", "0 4 * * *")
    r.add("b", "0 4 * * *", paused=True)
    assert r.due(AT) == ["a"]
    r.pause("a")
    assert r.due(AT) == []
    r.resume("b")
    assert r.due(AT) == ["b"]


def test_pause_drops_pending_retry():
    r = Registry()
    r.add("sync", "0 4 * * *", retries=3, retry_delay=7)
    retry = r.record_failure("sync", AT)
    r.pause("sync")
    job = r.jobs["sync"]
    assert job.retry_at is None and job.attempts == 0
    r.resume("sync")
    assert r.due(retry) == []


def test_failure_of_paused_job_schedules_nothing():
    r = Registry()
    r.add("sync", "0 4 * * *", retries=3, paused=True)
    assert r.record_failure("sync", AT) is None
    assert r.jobs["sync"].attempts == 0 and r.jobs["sync"].retry_at is None


def test_paused_must_be_a_bool():
    with pytest.raises(CronError):
        Registry().add("x", "* * * * *", paused="no")


def test_default_jobs_save_exactly_as_before():
    r = Registry()
    r.add("a", "0 4 * * *", retries=1)
    row = json.loads(dumps(r))["jobs"][0]
    assert len(row) == 5   # the five keys a saved job always had


def test_round_trip_keeps_tags_and_pause():
    r = Registry()
    r.add("a", "0 4 * * *", tags=["ops", "db"], paused=True)
    r.add("b", "0 5 * * *", tags=["web"])
    copy = loads(dumps(r))
    assert copy.jobs["a"].tags == ("db", "ops") and copy.jobs["a"].paused is True
    assert copy.jobs["b"].paused is False
    assert loads(dumps(r), with_state=False).jobs["a"].paused is True


def test_loading_a_paused_job_ignores_saved_retry():
    text = json.dumps({"format": 1, "jobs": [{"name": "a", "schedule": "0 4 * * *", "retries": 2, "paused": True,
                                              "state": {"attempts": 1, "retry_at": "2026-06-01T04:05:00"}}]})
    job = loads(text).jobs["a"]
    assert job.paused and job.retry_at is None and job.attempts == 0


@pytest.mark.parametrize("extra", [{"paused": "yes"}, {"paused": 1}, {"tags": "ops"}, {"tags": ["bad tag"]}])
def test_bad_saved_flags(extra):
    row = {"name": "a", "schedule": "0 4 * * *", **extra}
    with pytest.raises(CronError):
        loads(json.dumps({"format": 1, "jobs": [row]}))


def test_merge_keeps_tags_and_pause():
    one, two = Registry(), Registry()
    one.add("a", "0 4 * * *", tags=["ops"], paused=True)
    two.add("b", "0 5 * * *", tags=["web"], paused=True)
    out = merge(one, two)
    assert out.jobs["a"].paused and out.jobs["a"].tags == ("ops",)
    assert out.jobs["b"].paused and out.jobs["b"].tags == ("web",)
