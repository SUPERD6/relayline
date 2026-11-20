from datetime import datetime

import pytest

from cronlite import CronError, CronExpr, next_after, parse_field


def test_range():
    assert parse_field("hour", "9-12").values == frozenset({9, 10, 11, 12})


def test_star_step():
    f = parse_field("minute", "*/20")
    assert f.values == frozenset({0, 20, 40}) and f.wildcard is False


def test_range_step_and_list():
    assert parse_field("day", "1-9/4,30").values == frozenset({1, 5, 9, 30})


def test_number_step_runs_to_the_top():
    assert parse_field("month", "10/1").values == frozenset({10, 11, 12})
    assert parse_field("hour", "20/3").values == frozenset({20, 23})


def test_weekday_seven_is_sunday():
    assert parse_field("weekday", "7").values == frozenset({0})
    assert parse_field("weekday", "5-7").values == frozenset({5, 6, 0})
    assert parse_field("weekday", "*").values == frozenset(range(7))


def test_seven_only_for_weekday():
    with pytest.raises(CronError):
        parse_field("month", "7-13")


@pytest.mark.parametrize("text", ["*/0", "*/x", "5-2", "1-99", "3-", "1,,2", "-4"])
def test_invalid_parts(text):
    with pytest.raises(CronError) as err:
        parse_field("hour", text)
    assert str(err.value).startswith("hour")


def test_month_and_weekday_names():
    assert parse_field("month", "Jan,MAR-may").values == frozenset({1, 3, 4, 5})
    assert parse_field("weekday", "mon-Fri/2").values == frozenset({1, 3, 5})
    assert parse_field("weekday", "SAT,sun").values == frozenset({6, 0})
    assert CronExpr.parse("0 9 * jun-aug Sat").matches(datetime(2026, 7, 4, 9, 0))


def test_names_only_in_their_fields():
    with pytest.raises(CronError):
        parse_field("day", "mon")
    with pytest.raises(CronError):
        parse_field("weekday", "fri-sun")     # sun is 0: the range runs backwards
    with pytest.raises(CronError):
        parse_field("month", "janu")


def test_step_restricts_day_for_either_rule():
    e = CronExpr.parse("0 0 */10 * 1")
    assert e.matches(datetime(2026, 3, 11, 0, 0))   # day 11 is in 1,11,21,31
    assert e.matches(datetime(2026, 3, 2, 0, 0))    # a Monday
    assert not e.matches(datetime(2026, 3, 3, 0, 0))


def test_schedule_with_steps():
    e = CronExpr.parse("*/15 9-10 * * 1-5")
    assert next_after(e, datetime(2026, 3, 6, 10, 45)) == datetime(2026, 3, 9, 9, 0)   # Friday evening -> Monday
