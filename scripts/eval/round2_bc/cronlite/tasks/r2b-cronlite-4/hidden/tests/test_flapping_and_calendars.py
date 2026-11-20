from datetime import datetime, timedelta

import pytest

from cronlite import BlackoutCalendar, CronError, CronExpr, RunLog, check, flapping, missed, weekend_calendar

D = datetime(2026, 4, 6, 0, 0)   # a Monday
H, M = timedelta(hours=1), timedelta(minutes=1)


def _log(outcomes, job="j"):
    log = RunLog()
    for k, ok in enumerate(outcomes):
        log.record(job, D + k * H, D + k * H + M, ok=ok)
    return log


def test_transitions():
    log = _log([True, False, True, True, False])
    assert log.transitions("j") == 3
    assert log.transitions("j", last=3) == 1
    assert log.transitions("j", last=1) == 0 and log.transitions("nobody") == 0
    assert log.stats("j")["transitions"] == 3
    assert log.transitions("j", since=D + 2 * H) == 1
    with pytest.raises(CronError):
        log.transitions("j", last=0)


def test_flapping():
    log = _log([True, False, True, True, False])
    alert = flapping(log, "j", window=5, threshold=3)
    assert alert.kind == "flapping" and alert.detail == "3 changes in the last 5 runs"
    assert flapping(log, "j", window=5, threshold=4) is None
    assert flapping(log, "j", window=9, threshold=3).detail == "3 changes in the last 5 runs"
    assert flapping(log, "j", window=3, threshold=1).detail.startswith("1 ")
    assert "last 3 runs" in flapping(log, "j", window=5, threshold=1, since=D + 2 * H).detail
    for bad in ({"window": 1}, {"threshold": 0}):
        with pytest.raises(CronError):
            flapping(log, "j", **bad)


def test_one_run_covers_one_firing():
    log = RunLog()
    log.record("j", D + M, D + 2 * M)
    every_minute = CronExpr.parse("* * * * *")
    assert missed(log, "j", every_minute, D - M, D + 2 * M) == [D + M, D + 2 * M]
    with pytest.raises(CronError):
        missed(log, "j", every_minute, D - M, D + 2 * M, tolerance=-M)


def test_run_before_firing_does_not_count():
    log = RunLog()
    log.record("j", D + 9 * H - M, D + 9 * H)
    assert missed(log, "j", CronExpr.parse("0 9 * * *"), D, D + 10 * H) == [D + 9 * H]


def test_missed_skips_closed_days():
    daily = CronExpr.parse("0 9 * * *")
    log = RunLog()
    log.record("j", datetime(2026, 4, 3, 9, 0), datetime(2026, 4, 3, 9, 5))      # Friday
    log.record("j", datetime(2026, 4, 6, 9, 2), datetime(2026, 4, 6, 9, 5))      # Monday, two minutes late
    start, end = datetime(2026, 4, 3), datetime(2026, 4, 6, 23, 0)
    assert missed(log, "j", daily, start, end) == [datetime(2026, 4, 4, 9, 0), datetime(2026, 4, 5, 9, 0)]
    assert missed(log, "j", daily, start, end, calendar=weekend_calendar()) == []


def test_check_orders_flapping_after_failing():
    log = _log([True, False, True, False, False])
    hourly = CronExpr.parse("0 * * * *")
    alerts = check(log, {"j": hourly}, D - M, D + 4 * H, fail_threshold=2, flap_threshold=3)
    assert [a.kind for a in alerts] == ["failing", "flapping"]
    assert [a.kind for a in check(log, {"j": hourly}, D - M, D + 4 * H, fail_threshold=2)] == ["failing"]
    short = check(log, {"j": hourly}, D - M, D + 4 * H, fail_threshold=2, flap_threshold=3, flap_window=2)
    assert [a.kind for a in short] == ["failing"]


def test_check_judges_flapping_on_the_checked_period():
    log = _log([True, False, True, False, True, True, True])
    hourly = CronExpr.parse("0 * * * *")
    assert check(log, {"j": hourly}, D + 4 * H - M, D + 6 * H, flap_threshold=2) == []
    assert flapping(log, "j", threshold=2) is not None


def test_check_uses_job_calendars():
    daily = CronExpr.parse("0 9 * * *")
    log = RunLog()
    log.record("j", datetime(2026, 4, 3, 9, 0), datetime(2026, 4, 3, 9, 5))
    start, end = datetime(2026, 4, 3), datetime(2026, 4, 5, 23, 0)
    assert [a.kind for a in check(log, {"j": daily}, start, end)] == ["missed"]
    assert check(log, {"j": daily}, start, end, calendars={"j": weekend_calendar()}) == []
    assert check(log, {"j": daily}, start, end, calendars={"*": weekend_calendar()}) == []
    own = {"*": weekend_calendar(), "j": BlackoutCalendar()}
    assert [a.kind for a in check(log, {"j": daily}, start, end, calendars=own)] == ["missed"]
