import pytest

from tabula import Table, anti_join, join, semi_join

PEOPLE = Table(["id", "name", "team"], [(1, "ann", "x"), (2, "bob", "y"), (3, "cy", None), (None, "dot", "x")])
TEAMS = Table(["team", "name"], [("x", "red"), ("z", "blue"), ("x", "rose")])


def test_inner_join_with_suffixes():
    out = join(PEOPLE, TEAMS, "team")
    assert out.columns == ["team", "id", "name_left", "name_right"]
    assert out.rows == [("x", 1, "ann", "red"), ("x", 1, "ann", "rose"), ("x", None, "dot", "red"),
                        ("x", None, "dot", "rose")]


def test_left_right_outer():
    left = join(PEOPLE, TEAMS, "team", how="left")
    assert ("y", 2, "bob", None) in left.rows and (None, 3, "cy", None) in left.rows
    right = join(PEOPLE, TEAMS, "team", how="right")
    assert right.rows[-1] == ("z", None, None, "blue")
    outer = join(PEOPLE, TEAMS, "team", how="outer")
    assert len(outer) == 7


def test_none_keys_never_match():
    a = Table(["k", "v"], [(None, 1)])
    b = Table(["k", "w"], [(None, 2)])
    assert join(a, b, "k").rows == []
    assert join(a, b, "k", how="outer").rows == [(None, 1, None), (None, None, 2)]


def test_multi_key_and_errors():
    a = Table(["x", "y", "v"], [(1, 1, "a"), (1, 2, "b")])
    b = Table(["x", "y", "w"], [(1, 2, "c")])
    assert join(a, b, ["x", "y"]).rows == [(1, 2, "b", "c")]
    with pytest.raises(ValueError):
        join(a, b, "x", how="cross")
    with pytest.raises(ValueError):
        join(PEOPLE, TEAMS, "team", suffixes=("_s", "_s"))
    with pytest.raises(ValueError):
        join(a, b, [])


def test_semi_and_anti():
    assert semi_join(PEOPLE, TEAMS, "team").column("name") == ["ann", "dot"]
    assert anti_join(PEOPLE, TEAMS, "team").column("name") == ["bob", "cy"]
