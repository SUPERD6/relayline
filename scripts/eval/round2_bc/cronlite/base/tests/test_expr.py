from datetime import datetime

import pytest

from cronlite import CronError, CronExpr, next_after, upcoming


def test_parse_and_match():
    e = CronExpr.parse("30 9 * * *")
    assert e.matches(datetime(2026, 3, 4, 9, 30))
    assert not e.matches(datetime(2026, 3, 4, 9, 31))


def test_alias():
    assert CronExpr.parse("@daily").matches(datetime(2026, 1, 2, 0, 0))


def test_wrong_field_count():
    with pytest.raises(CronError):
        CronExpr.parse("1 2 3")


def test_weekday_sunday_is_zero():
    e = CronExpr.parse("0 12 * * 0")
    assert e.matches(datetime(2026, 3, 1, 12, 0))      # a Sunday
    assert not e.matches(datetime(2026, 3, 2, 12, 0))


def test_day_or_weekday_when_both_restricted():
    e = CronExpr.parse("0 0 13 * 5")
    assert e.matches(datetime(2026, 3, 13, 0, 0))      # the 13th
    assert e.matches(datetime(2026, 3, 6, 0, 0))       # a Friday


def test_next_after_skips_ahead():
    e = CronExpr.parse("15 8 1 * *")
    assert next_after(e, datetime(2026, 1, 1, 8, 15)) == datetime(2026, 2, 1, 8, 15)


def test_next_after_drops_seconds():
    e = CronExpr.parse("* * * * *")
    assert next_after(e, datetime(2026, 1, 1, 0, 0, 59)) == datetime(2026, 1, 1, 0, 1)


def test_upcoming():
    e = CronExpr.parse("0 * * * *")
    assert upcoming(e, datetime(2026, 1, 1, 0, 30), 3) == [
        datetime(2026, 1, 1, 1, 0), datetime(2026, 1, 1, 2, 0), datetime(2026, 1, 1, 3, 0)]


def test_never_fires():
    with pytest.raises(CronError):
        next_after(CronExpr.parse("0 0 31 2 *"), datetime(2026, 1, 1))
