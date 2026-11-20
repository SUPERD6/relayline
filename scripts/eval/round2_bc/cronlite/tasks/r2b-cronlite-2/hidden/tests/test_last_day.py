from datetime import datetime

import pytest

from cronlite import CronError, CronExpr, canonical, describe, equivalent, lint, lint_all, next_after, parse_field


def test_parse_last_day():
    spec = parse_field("day", "L")
    assert spec.last and not spec.wildcard and spec.values == frozenset()
    mixed = parse_field("day", " 3 , l ")
    assert mixed.last and mixed.values == frozenset({3})
    assert parse_field("day", "3").last is False


@pytest.mark.parametrize("name", ["minute", "hour", "month", "weekday"])
def test_last_only_in_day_field(name):
    with pytest.raises(CronError) as err:
        parse_field(name, "L")
    assert str(err.value).startswith(name)


def test_matches_the_last_day_of_each_month():
    e = CronExpr.parse("0 12 L * *")
    assert e.matches(datetime(2026, 4, 30, 12, 0)) and not e.matches(datetime(2026, 4, 29, 12, 0))
    assert e.matches(datetime(2026, 2, 28, 12, 0))
    assert e.matches(datetime(2028, 2, 29, 12, 0)) and not e.matches(datetime(2028, 2, 28, 12, 0))
    assert e.matches(datetime(2026, 12, 31, 12, 0))


def test_next_after_with_last_day():
    e = CronExpr.parse("0 12 L * *")
    assert next_after(e, datetime(2026, 1, 31, 12, 0)) == datetime(2026, 2, 28, 12, 0)
    both = CronExpr.parse("0 0 2,L * *")
    assert next_after(both, datetime(2026, 6, 2, 0, 0)) == datetime(2026, 6, 30, 0, 0)


def test_last_day_is_a_restriction_for_the_either_rule():
    e = CronExpr.parse("0 0 L * 1")
    assert e.matches(datetime(2026, 3, 2, 0, 0))     # a Monday that is not the last day
    assert e.matches(datetime(2026, 3, 31, 0, 0))    # the last day, a Tuesday
    assert not e.matches(datetime(2026, 3, 3, 0, 0))


def test_canonical_text():
    assert canonical("0 0 L,5 * *") == "0 0 5,L * *"
    assert canonical("0 0 l * *") == "0 0 L * *"
    assert equivalent("0 0 L * *", "0 0 l * *") and not equivalent("0 0 L * *", "0 0 31 * *")


def test_describe_last_day():
    assert describe("0 6 L * *") == "at 06:00 on the last day of the month"
    assert describe("0 6 1,L * *") == "at 06:00 on the 1st and last day of the month"
    assert describe("0 6 L * 5") == "at 06:00 on the last day of the month or on Friday"


def test_lint_last_day_exists_in_every_month():
    assert lint("0 0 L * *") == []
    assert lint("0 0 L 2 *") == []
    assert [w.code for w in lint("0 0 31,L 4 *")] == ["missing-days"]


def test_duplicates_tell_last_day_apart():
    assert lint_all({"a": "0 0 1,L * *", "b": "0 0 1 * *"}) == {}
    assert lint_all({"a": "0 0 1,L * *", "b": "0 0 L,1 * *"}) == {"a": ["duplicate"], "b": ["duplicate"]}
