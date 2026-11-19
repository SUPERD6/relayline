from datetime import datetime, timedelta

import pytest

from cronlite import CronError, CronExpr, Run, RunLog, check, failing, missed, slow

D = datetime(2026, 4, 1, 0, 0)


def _log():
    log = RunLog()
    log.record("a", D, D + timedelta(minutes=2))
    log.record("a", D + timedelta(hours=1), D + timedelta(hours=1, minutes=30), ok=False, error="timeout")
    log.record("a", D + timedelta(hours=2), D + timedelta(hours=2, minutes=1), ok=False, error="timeout")
    log.record("b", D + timedelta(minutes=1), D + timedelta(minutes=3), ok=False)
    return log


def test_streaks_and_stats():
    log = _log()
    assert log.streak("a") == -2 and log.streak("b") == -1 and log.streak("zz") == 0
    s = log.stats("a")
    assert s["runs"] == 3 and s["failures"] == 2 and s["success_rate"] == pytest.approx(1 / 3)
    assert s["max_seconds"] == 1800 and s["mean_seconds"] == pytest.approx((120 + 1800 + 60) / 3)
    assert log.last("a", ok=True).started == D and log.jobs() == ["a", "b"]


def test_reasons_counts_busiest_and_window():
    log = _log()
    assert log.failure_reasons() == {"timeout": 2, "failed": 1}
    assert log.daily_counts("a") == {"2026-04-01": (1, 2)}
    assert log.busiest_hour() == 0
    assert len(log.window(D, timedelta(minutes=30))) == 2


def test_overlap_prune_and_round_trip():
    log = RunLog()
    log.record("x", D, D + timedelta(minutes=10))
    log.record("x", D + timedelta(minutes=5), D + timedelta(minutes=6))
    assert len(log.overlapping("x")) == 1
    copy = RunLog.from_list(log.to_list())
    assert copy.runs == log.runs
    assert log.prune(D + timedelta(minutes=1)) == 1 and len(log.runs) == 1


def test_bad_runs():
    with pytest.raises(CronError):
        RunLog().record("x", D, D - timedelta(seconds=1))
    with pytest.raises(CronError):
        Run.from_dict({"job": "x"})


def test_alerts():
    log = _log()
    assert failing(log, "a", 2).detail == "2 failures in a row, last: timeout"
    assert failing(log, "a", 3) is None
    every_hour = CronExpr.parse("0 * * * *")
    gone = missed(log, "a", every_hour, D - timedelta(minutes=1), D + timedelta(hours=3))
    assert gone == [datetime(2026, 4, 1, 3, 0)]
    assert slow(log, "a", timedelta(minutes=5)) == [D + timedelta(hours=1)]
    alerts = check(log, {"a": every_hour, "b": every_hour}, D - timedelta(minutes=1), D + timedelta(hours=1),
                   fail_threshold=1, slow_limit=timedelta(minutes=5))
    assert [(x.job, x.kind) for x in alerts] == [("a", "failing"), ("a", "slow"), ("b", "failing"),
                                                 ("b", "missed")]
    with pytest.raises(CronError):
        failing(log, "a", 0)
