import pytest

from tabula import Table, fill_missing

V = Table(["k", "v"], [("a", None), ("b", 1), ("c", None), ("d", None), ("e", None), ("f", 7), ("g", None)])


def filled(**kw):
    return fill_missing(V, columns=["v"], **kw).column("v")


def test_backward_takes_the_next_value():
    assert filled(method="backward") == [1, 1, 7, 7, 7, 7, None]


def test_interpolate_between_numbers():
    assert filled(method="interpolate") == [None, 1, 2.5, 4.0, 5.5, 7, None]
    out = fill_missing(Table(["v"], [(2,), (None,), (4,)]), method="interpolate").column("v")
    assert out == [2, 3.0, 4] and isinstance(out[1], float)


def test_limit_per_run():
    assert filled(method="forward", limit=2) == [None, 1, 1, 1, None, 7, 7]
    assert filled(method="backward", limit=1) == [1, 1, None, None, 7, 7, None]
    assert filled(method="backward", limit=2) == [1, 1, None, 7, 7, 7, None]
    assert fill_missing(V, 0, method="value", limit=2).column("v") == [0, 1, 0, 0, None, 7, 0]


def test_interpolate_leaves_long_runs_whole():
    assert filled(method="interpolate", limit=2) == [None, 1, None, None, None, 7, None]
    assert filled(method="interpolate", limit=3) == [None, 1, 2.5, 4.0, 5.5, 7, None]


def test_interpolate_needs_numbers_on_both_sides():
    with pytest.raises(TypeError):
        fill_missing(Table(["v"], [("x",), (None,), (3,)]), method="interpolate")
    with pytest.raises(TypeError):
        fill_missing(Table(["v"], [(True,), (None,), (3,)]), method="interpolate")
    t = Table(["s", "v"], [("x", 1), (None, None), ("y", 3)])
    assert fill_missing(t, columns=["v"], method="interpolate").rows == [("x", 1), (None, 2.0), ("y", 3)]


def test_open_ended_runs_ignore_their_neighbour():
    assert fill_missing(Table(["v"], [("x",), (None,)]), method="interpolate").column("v") == ["x", None]
    assert fill_missing(Table(["v"], [(None,), (True,)]), method="interpolate").column("v") == [None, True]


def test_bad_method_or_limit():
    with pytest.raises(ValueError):
        filled(method="linear")
    with pytest.raises(ValueError):
        filled(method="forward", limit=0)
