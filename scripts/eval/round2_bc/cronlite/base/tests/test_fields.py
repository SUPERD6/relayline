import pytest

from cronlite import CronError, parse_field


def test_wildcard_covers_bounds():
    f = parse_field("hour", "*")
    assert f.wildcard and f.values == frozenset(range(24))


def test_list():
    assert parse_field("minute", "0, 15,30").values == frozenset({0, 15, 30})


def test_out_of_bounds():
    with pytest.raises(CronError):
        parse_field("month", "13")


def test_not_a_number():
    with pytest.raises(CronError):
        parse_field("day", "x")


def test_unknown_field():
    with pytest.raises(CronError):
        parse_field("second", "1")
