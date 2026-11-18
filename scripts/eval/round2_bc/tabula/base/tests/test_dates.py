from datetime import date, datetime

import pytest

from tabula import (CoercionError, Table, add_period, date_range, format_dates, parse_date, parse_dates,
                    period_label, period_start)


def test_parse_date():
    assert parse_date("2026-03-04") == date(2026, 3, 4)
    assert parse_date("2026-03-04T05:06") == datetime(2026, 3, 4, 5, 6)
    assert parse_date(" 2026-03-04 05:06:07 ") == datetime(2026, 3, 4, 5, 6, 7)
    with pytest.raises(ValueError):
        parse_date("03/04/2026")


def test_parse_dates_column():
    t = parse_dates(Table(["d", "x"], [("2026-01-02", "2026-01-02"), ("", "y")]), ["d"])
    assert t.rows == [(date(2026, 1, 2), "2026-01-02"), (None, "y")]
    with pytest.raises(CoercionError) as err:
        parse_dates(Table(["d"], [("soon",)]), ["d"])
    assert err.value.kind == "date"


def test_periods():
    d = date(2026, 5, 20)   # a Wednesday
    assert period_start(d, "week") == date(2026, 5, 18)
    assert period_start(datetime(2026, 5, 20, 9), "quarter") == date(2026, 4, 1)
    assert [period_label(d, p) for p in ("day", "week", "month", "quarter", "year")] == [
        "2026-05-20", "2026-W21", "2026-05", "2026-Q2", "2026"]
    with pytest.raises(ValueError):
        period_start(d, "decade")


def test_add_period_and_format():
    t = Table(["d"], [(date(2026, 1, 31),), (None,)])
    assert add_period(t, "d", "month").column("d_month") == ["2026-01", None]
    assert format_dates(t, ["d"], "%d.%m.%Y").column("d") == ["31.01.2026", None]


def test_date_range():
    assert date_range(date(2026, 1, 1), date(2026, 1, 5), 2) == [date(2026, 1, 1), date(2026, 1, 3),
                                                                 date(2026, 1, 5)]
    with pytest.raises(ValueError):
        date_range(date(2026, 1, 1), date(2026, 1, 2), 0)
