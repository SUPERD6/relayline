import pytest

from tabula import Table


@pytest.fixture
def t():
    return Table(["name", "qty", "kind"], [("pen", 3, "a"), ("cup", 1, "b"), ("ink", 2, "a")])


def test_select(t):
    assert t.select("qty", "name").rows == [(3, "pen"), (1, "cup"), (2, "ink")]


def test_where(t):
    assert t.where(lambda r: r["kind"] == "a").column("name") == ["pen", "ink"]


def test_sort_by(t):
    assert t.sort_by("qty").column("name") == ["cup", "ink", "pen"]
    assert t.sort_by("qty", reverse=True).column("name") == ["pen", "ink", "cup"]


def test_group_count(t):
    assert t.group_count("kind") == {"a": 2, "b": 1}


def test_unknown_column(t):
    with pytest.raises(KeyError):
        t.column("price")


def test_row_width_checked():
    with pytest.raises(ValueError):
        Table(["a", "b"], [(1,)])


def test_to_dicts_and_len(t):
    assert len(t) == 3
    assert t.to_dicts()[1] == {"name": "cup", "qty": 1, "kind": "b"}


def test_equality(t):
    assert t == Table(t.columns, t.rows)
    assert t != t.select("name")
