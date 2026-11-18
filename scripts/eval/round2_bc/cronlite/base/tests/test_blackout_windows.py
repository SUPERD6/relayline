from datetime import date, datetime, time

import pytest

from cronlite import (BlackoutCalendar, CronError, CronExpr, WindowSet, next_open_after, parse_calendar,
                      parse_window, runs_between, suppressed, weekend_calendar)


def test_calendar_closed_days():
    cal = BlackoutCalendar({"2026-12-25"}, {0}, [("2026-08-03", "2026-08-05")])
    assert cal.is_closed(date(2026, 12, 25)) and cal.is_closed(datetime(2026, 3, 1, 9))   # Sunday
    assert cal.is_closed("2026-08-04") and not cal.is_closed("2026-08-06")
    assert cal.closed_days("2026-08-01", "2026-08-09") == [date(2026, 8, 2), date(2026, 8, 3), date(2026, 8, 4),
                                                           date(2026, 8, 5), date(2026, 8, 9)]


def test_calendar_errors():
    with pytest.raises(CronError):
        BlackoutCalendar(weekdays={7})
    with pytest.raises(CronError):
        BlackoutCalendar(periods=[("2026-02-02", "2026-02-01")])
    with pytest.raises(CronError):
        BlackoutCalendar({"tomorrow"})


def test_next_open_after_skips_closed_days():
    e = CronExpr.parse("0 9 * * *")
    cal = weekend_calendar({"2026-03-02"})
    assert next_open_after(e, datetime(2026, 2, 27, 10, 0), cal) == datetime(2026, 3, 3, 9, 0)
    every_minute = CronExpr.parse("* * * * *")
    assert next_open_after(every_minute, datetime(2026, 2, 28, 0, 0), cal) == datetime(2026, 3, 3, 0, 0)
    with pytest.raises(CronError):
        next_open_after(e, datetime(2026, 1, 1), BlackoutCalendar(weekdays=set(range(7))))


def test_runs_between_and_suppressed():
    e = CronExpr.parse("0 12 * * *")
    cal = BlackoutCalendar({"2026-01-02"})
    start, end = datetime(2026, 1, 1), datetime(2026, 1, 3, 12, 0)
    assert runs_between(e, start, end, cal) == [datetime(2026, 1, 1, 12), datetime(2026, 1, 3, 12)]
    assert suppressed(e, start, end, cal) == [datetime(2026, 1, 2, 12)]
    assert len(runs_between(e, start, end, limit=2)) == 2


def test_merge_and_parse_calendar():
    cal = parse_calendar("# holidays\n2026-12-25\n2026-12-28..2026-12-30  # freeze\nclosed sat Sun\n\n")
    assert cal.is_closed("2026-12-29") and cal.is_closed("2026-03-07") and not cal.is_closed("2026-03-09")
    merged = cal.merge(BlackoutCalendar({"2026-03-09"}))
    assert merged.is_closed("2026-03-09")
    with pytest.raises(CronError) as err:
        parse_calendar("2026-01-01\nclosed funday\n")
    assert str(err.value).startswith("line 2")


def test_windows():
    w = parse_window("22:00-06:00")
    assert w.contains(time(23, 0)) and w.contains(time(5, 59)) and not w.contains(time(6, 0))
    assert str(parse_window("9:05-17:00")) == "09:05-17:00"
    with pytest.raises(CronError):
        parse_window("9-17")
    ws = WindowSet(["09:00-12:00", "13:00-17:00"])
    assert ws.allows(datetime(2026, 1, 1, 9, 0)) and not ws.allows(datetime(2026, 1, 1, 12, 30))
    assert ws.next_allowed(datetime(2026, 1, 1, 12, 10, 30)) == datetime(2026, 1, 1, 13, 0)
    assert ws.next_allowed(datetime(2026, 1, 1, 18, 0)) == datetime(2026, 1, 2, 9, 0)
    assert ws.open_minutes_per_day() == 7 * 60


def test_window_placement():
    ws = WindowSet(["09:00-17:00"])
    due = [datetime(2026, 1, 1, 8, 0), datetime(2026, 1, 1, 10, 0)]
    assert ws.place(due) == [(due[0], datetime(2026, 1, 1, 9, 0)), (due[1], due[1])]
    assert ws.place(due, mode="drop")[0] == (due[0], None)
    with pytest.raises(CronError):
        ws.place(due, mode="later")
    with pytest.raises(CronError):
        WindowSet([])
