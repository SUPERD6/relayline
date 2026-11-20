from datetime import date, datetime, timedelta

import pytest

from cronlite import (BlackoutCalendar, CronError, CronExpr, WindowSet, placement_counts, plan_runs,
                      weekend_calendar)

FRI, SAT, MON = date(2026, 3, 6), date(2026, 3, 7), date(2026, 3, 9)


def at(day, hour, minute=0):
    return datetime(day.year, day.month, day.day, hour, minute)


def test_next_open_day():
    cal = weekend_calendar()
    assert cal.next_open_day(SAT) == MON
    assert cal.next_open_day(at(FRI, 23)) == FRI
    with pytest.raises(CronError):
        BlackoutCalendar(weekdays=set(range(7))).next_open_day(FRI)


def test_run_due_on_a_closed_day_is_dropped():
    ws = WindowSet(["09:00-17:00"])
    cal = weekend_calendar()
    assert ws.place([at(SAT, 10)], calendar=cal) == [(at(SAT, 10), None)]
    assert ws.place([at(SAT, 7)], mode="drop", calendar=cal) == [(at(SAT, 7), None)]


def test_deferral_skips_closed_days():
    ws = WindowSet(["09:00-17:00"])
    cal = weekend_calendar()
    assert ws.place([at(FRI, 18)], calendar=cal) == [(at(FRI, 18), at(MON, 9))]
    assert ws.place([at(FRI, 18)]) == [(at(FRI, 18), at(SAT, 9))]


def test_next_allowed_with_calendar():
    ws = WindowSet(["01:00-05:00"])
    cal = BlackoutCalendar(weekdays={6})
    assert ws.next_allowed(at(FRI, 6), cal) == at(date(2026, 3, 8), 1)
    assert ws.next_allowed(datetime(2026, 3, 6, 2, 30, 40), cal) == at(FRI, 2, 30)


def test_max_defer():
    ws = WindowSet(["09:00-17:00"])
    hour = timedelta(hours=1)
    assert ws.place([at(FRI, 8)], max_defer=hour) == [(at(FRI, 8), at(FRI, 9))]
    assert ws.place([at(FRI, 7, 59)], max_defer=hour) == [(at(FRI, 7, 59), None)]
    assert ws.place([at(FRI, 18)], calendar=weekend_calendar(), max_defer=timedelta(days=2)) == [
        (at(FRI, 18), None)]
    with pytest.raises(CronError):
        ws.place([at(FRI, 8)], max_defer=-hour)


def test_plan_runs_and_counts():
    e = CronExpr.parse("0 8,12 * * *")
    placed = plan_runs(e, datetime(2026, 3, 5), datetime(2026, 3, 9, 23, 59), ["09:00-17:00"], weekend_calendar())
    assert placed[:3] == [(datetime(2026, 3, 5, 8), datetime(2026, 3, 5, 9)),
                          (datetime(2026, 3, 5, 12), datetime(2026, 3, 5, 12)),
                          (at(FRI, 8), at(FRI, 9))]
    assert len(placed) == 10 and placed[-2] == (at(MON, 8), at(MON, 9))
    assert placement_counts(placed) == {"on_time": 3, "deferred": 3, "dropped": 4}
    assert placement_counts([]) == {"on_time": 0, "deferred": 0, "dropped": 0}
