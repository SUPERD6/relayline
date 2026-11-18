import io
from datetime import datetime, timedelta, timezone

import pytest

from cronlite import (CronError, CronExpr, Registry, busiest_minute, calendar, canonical, collisions, dumps,
                      equivalent, firings, format_offset, gaps, lint, lint_all, loads, merge, next_after_in,
                      parse_offset, per_day, per_hour, per_day_upper_bound, preset, same_moment,
                      spread_suggestion, to_local, to_utc)
from cronlite.cli import run
from cronlite.ical import escape, fold


def test_store_round_trip_with_state():
    r = Registry()
    r.add("b", "0 0 * * *", retries=2)
    r.add("a", "@hourly")
    r.record_failure("b", datetime(2026, 1, 1))
    copy = loads(dumps(r))
    assert sorted(copy.jobs) == ["a", "b"] and copy.jobs["b"].retry_at == datetime(2026, 1, 1, 0, 5)
    assert loads(dumps(r), with_state=False).jobs["b"].attempts == 0
    with pytest.raises(CronError):
        loads('{"format": 2, "jobs": []}')
    with pytest.raises(CronError):
        loads('{"format": 1, "jobs": [{"name": "x", "schedule": "* * * * *", "colour": 1}]}')


def test_store_merge():
    a, b = Registry(), Registry()
    a.add("x", "0 * * * *")
    b.add("x", "30 * * * *")
    with pytest.raises(CronError):
        merge(a, b)
    assert merge(a, b, replace=True).jobs["x"].expr.text == "30 * * * *"


def test_offsets():
    assert format_offset(parse_offset("+05:30")) == "+05:30"
    assert format_offset(parse_offset("UTC-8")) == "-08:00"
    assert parse_offset("Z") is timezone.utc
    for bad in ("+15:00", "+05:61", "five"):
        with pytest.raises(CronError):
            parse_offset(bad)


def test_local_schedules():
    tz = parse_offset("+02:00")
    assert to_utc(datetime(2026, 1, 1, 9, 0), tz) == datetime(2026, 1, 1, 7, 0)
    assert to_local(datetime(2026, 1, 1, 23, 0), tz) == datetime(2026, 1, 2, 1, 0)
    e = CronExpr.parse("0 9 * * *")
    assert next_after_in(e, datetime(2026, 1, 1, 8, 0), tz) == datetime(2026, 1, 2, 7, 0)
    assert same_moment(e, tz, CronExpr.parse("0 7 * * *"), timezone.utc, datetime(2026, 1, 1)) == \
        datetime(2026, 1, 1, 7, 0)
    assert same_moment(e, tz, CronExpr.parse("0 8 * * *"), timezone.utc, datetime(2026, 1, 1),
                       timedelta(days=2)) is None


def test_analysis():
    e = CronExpr.parse("0 9,17 * * *")
    times = firings(e, datetime(2026, 1, 1), datetime(2026, 1, 2, 23, 59))
    assert per_day(times) == {"2026-01-01": 2, "2026-01-02": 2}
    assert per_hour(times)[9] == 2
    assert gaps(times)["min"] == timedelta(hours=8) and gaps(times[:1])["max"] is None
    jobs = {"a": CronExpr.parse("0 * * * *"), "b": CronExpr.parse("0,30 * * * *"), "c": CronExpr.parse("0 2 * * *")}
    hits = collisions(jobs, datetime(2026, 1, 1, 1, 0), datetime(2026, 1, 1, 2, 0))
    assert hits == {datetime(2026, 1, 1, 2, 0): ["a", "b", "c"]}
    assert busiest_minute(jobs, datetime(2026, 1, 1, 1, 0), datetime(2026, 1, 1, 2, 0)) == \
        (datetime(2026, 1, 1, 2, 0), 3)
    assert spread_suggestion(jobs, [5, 10, 15]) == {"a": 5, "c": 10}
    with pytest.raises(CronError):
        firings(CronExpr.parse("* * * * *"), datetime(2026, 1, 1), datetime(2026, 1, 2), limit=10)


def test_lint():
    assert [w.code for w in lint("0 0 13 * 5")] == ["day-and-weekday"]
    assert [w.code for w in lint("0 0 31 4,6 *")] == ["never"]
    assert [w.code for w in lint("0 0 31 * *")] == ["missing-days"]
    assert [w.code for w in lint("0 0 29 2 *")] == ["leap-only"]
    assert [w.code for w in lint("* * * * *")] == ["every-minute"]
    assert lint_all({"x": "0 * * * *", "y": "0 * * * *", "z": "5 * * * *"}) == {"x": ["duplicate"],
                                                                                "y": ["duplicate"]}


def test_canonical():
    assert canonical("30,0 9 * 1,2,3,4,5,6,7,8,9,10,11,12 *") == "0,30 9 * * *"
    assert canonical("0 0 * * *", use_aliases=True) == "@daily"
    assert equivalent("@hourly", "0 * * * *") and not equivalent("0 * * * *", "1 * * * *")
    assert per_day_upper_bound("0,30 9,10 * * *") == 4
    assert preset("nightly").matches(datetime(2026, 1, 1, 2, 30))


def test_ical():
    assert escape("a,b;c\nd") == "a\\,b\\;c\\nd"
    assert fold("x" * 80) == ["x" * 75, " " + "x" * 5]
    text = calendar({"backup": CronExpr.parse("0 3 * * *")}, datetime(2026, 1, 1), count=2)
    lines = text.split("\r\n")
    assert lines[0] == "BEGIN:VCALENDAR" and text.endswith("END:VCALENDAR\r\n")
    assert lines.count("BEGIN:VEVENT") == 2 and "DTSTART:20260101T030000" in lines


def test_cli():
    out = io.StringIO()
    assert run(["next", "0 12 * * *", "--from", "2026-01-01T13:00", "--count", "2"], out) == 0
    assert out.getvalue() == "2026-01-02 12:00\n2026-01-03 12:00\n"
    out = io.StringIO()
    assert run(["phrase", "daily at 06:15"], out) == 0 and out.getvalue() == "15 6 * * *\n"
    out = io.StringIO()
    assert run(["describe", "0 6 * * *"], out) == 0 and out.getvalue() == "at 06:00\n"
    assert run(["lint", "1 2 3"], io.StringIO()) == 2
