import pytest

from tabula import JoinError, Table, TabulaError, anti_join, join, semi_join

ORDERS = Table(["oid", "cust", "amt"], [(1, 10, 5), (2, 11, 7), (3, 10, 2), (4, None, 1)])
CUSTS = Table(["cid", "nm"], [(10, "ann"), (12, "bo"), (None, "cy")])
ON = {"cust": "cid"}


def test_keys_with_different_names():
    out = join(ORDERS, CUSTS, ON)
    assert out.columns == ["cust", "oid", "amt", "nm"]
    assert out.rows == [(10, 1, 5, "ann"), (10, 3, 2, "ann")]


def test_unmatched_right_rows_fill_the_left_key_column():
    out = join(ORDERS, CUSTS, ON, how="right")
    assert out.rows == [(10, 1, 5, "ann"), (10, 3, 2, "ann"), (12, None, None, "bo"), (None, None, None, "cy")]


def test_semi_and_anti_accept_a_mapping():
    assert semi_join(ORDERS, CUSTS, ON).column("oid") == [1, 3]
    assert anti_join(ORDERS, CUSTS, ON).column("oid") == [2, 4]


def test_right_column_named_like_a_left_key_collides():
    other = Table(["cid", "cust"], [(10, "z")])
    with pytest.raises(ValueError):
        join(ORDERS, other, ON)


def test_indicator_column():
    out = join(ORDERS, CUSTS, ON, how="outer", indicator="src")
    assert out.columns == ["cust", "oid", "amt", "nm", "src"]
    assert out.column("src") == ["both", "left", "both", "left", "right", "right"]
    assert join(ORDERS, CUSTS, ON, indicator="src").column("src") == ["both", "both"]
    assert "src" not in join(ORDERS, CUSTS, ON).columns


def test_indicator_name_must_be_free():
    with pytest.raises(ValueError):
        join(ORDERS, CUSTS, ON, indicator="amt")


def test_validate_reports_side_and_key():
    assert len(join(ORDERS, CUSTS, ON, validate="m:1")) == 2
    with pytest.raises(JoinError) as err:
        join(ORDERS, CUSTS, ON, validate="1:m")
    assert err.value.side == "left" and err.value.key == (10,)
    assert isinstance(err.value, TabulaError)


def test_validate_ignores_missing_keys():
    many_none = Table(["cid", "nm"], [(None, "a"), (None, "b"), (10, "c")])
    assert join(ORDERS, many_none, ON, validate="m:1").rows == [(10, 1, 5, "c"), (10, 3, 2, "c")]


def test_one_to_one_checks_left_first_and_unmatched_keys_too():
    doubled = Table(["cid", "nm"], [(10, "a"), (10, "b")])
    with pytest.raises(JoinError) as err:
        join(ORDERS, doubled, ON, validate="1:1")
    assert err.value.side == "left"
    a = Table(["k", "v"], [(1, "a"), (2, "b")])
    b = Table(["k", "w"], [(3, "x"), (3, "y")])
    with pytest.raises(JoinError) as err:
        join(a, b, "k", validate="1:1")
    assert err.value.side == "right" and err.value.key == (3,)


def test_unknown_validate_rule():
    with pytest.raises(ValueError):
        join(ORDERS, CUSTS, ON, validate="n:n")
