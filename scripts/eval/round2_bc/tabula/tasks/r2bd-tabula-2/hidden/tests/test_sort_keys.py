import pytest

from tabula import Table

ROWS = [("pen", 3, "a"), ("cup", None, "b"), ("ink", 3, "b"), ("box", 1, None), ("mug", None, "a")]


@pytest.fixture
def t():
    return Table(["item", "qty", "kind"], ROWS)


def test_single_key_keeps_old_call(t):
    assert t.sort_by("qty").column("item") == ["box", "pen", "ink", "cup", "mug"]
    assert t.sort_by("qty", reverse=True).column("item") == ["pen", "ink", "box", "cup", "mug"]


def test_two_keys_with_descending_prefix(t):
    assert t.sort_by("kind", "-qty").column("item") == ["pen", "mug", "ink", "cup", "box"]


def test_descending_first_key(t):
    assert t.sort_by("-qty", "item").column("item") == ["ink", "pen", "box", "cup", "mug"]


def test_missing_values_last_both_ways(t):
    assert t.sort_by("-kind").column("kind") == ["b", "b", "a", "a", None]
    assert t.sort_by("kind").column("kind") == ["a", "a", "b", "b", None]


def test_reverse_flips_every_key(t):
    assert t.sort_by("kind", "-qty", reverse=True).column("item") == ["ink", "cup", "pen", "mug", "box"]


def test_stable_for_equal_keys():
    t = Table(["k", "v"], [(1, "p"), (0, "x"), (1, "q"), (1, "r")])
    assert t.sort_by("-k").column("v") == ["p", "q", "r", "x"]


def test_column_named_with_dash():
    t = Table(["-x", "x"], [(2, 1), (1, 2)])
    assert t.sort_by("-x").column("-x") == [1, 2]


def test_errors(t):
    with pytest.raises(KeyError):
        t.sort_by("-price")
    with pytest.raises(ValueError):
        t.sort_by()
