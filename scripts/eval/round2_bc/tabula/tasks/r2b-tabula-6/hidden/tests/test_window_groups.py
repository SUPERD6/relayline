import pytest

from tabula import Table, difference, rank, rolling_mean, share
from tabula.window import shift

T = Table(["g", "v"], [("a", 4), ("b", 1), ("a", None), ("b", 3), ("a", 2), (None, 5), ("b", 3)])


def test_rolling_mean_per_group_keeps_row_order():
    out = rolling_mean(T, "v", 2, by="g")
    assert out.column("v_mean2") == [4, 1, 4, 2, 2, 5, 3]
    assert [row[:2] for row in out.rows] == T.rows


def test_rank_per_group():
    assert rank(T, "v", by="g").column("v_rank") == [2, 1, None, 2, 1, 1, 2]
    assert rank(T, "v", by="g", descending=True).column("v_rank") == [1, 3, None, 1, 2, 1, 1]
    assert rank(T, "v", by="g", method="dense").column("v_rank") == [2, 1, None, 2, 1, 1, 2]


def test_difference_restarts_in_each_group():
    assert difference(T, "v", by="g").column("v_diff") == [None, None, None, 2, None, None, 0]
    t = Table(["g", "h", "v"], [("a", 1, 1), ("a", 2, 5), ("a", 1, 3)])
    assert difference(t, "v", by=["g", "h"]).column("v_diff") == [None, None, 2]


def test_share_of_group_total():
    assert share(T, "v", by="g", digits=2).column("v_share") == [0.67, 0.14, None, 0.43, 0.33, 1.0, 0.43]
    t = Table(["g", "v"], [("x", 0), ("y", 2), ("x", 0)])
    assert share(t, "v", by="g").column("v_share") == [None, 1.0, None]


def test_shift_back_and_ahead():
    assert shift(T, "v", by="g").column("v_shift1") == [None, None, 4, 1, None, None, 3]
    assert shift(T, "v", -1, by="g", fill=0).column("v_shift-1") == [None, 3, 2, 3, 0, 0, 0]
    assert shift(T, "v", 2).column("v_shift2") == [None, None, 4, 1, None, 3, 2]
    assert shift(T, "v", name="prev").columns == ["g", "v", "prev"]


def test_bad_arguments():
    with pytest.raises(KeyError):
        rank(T, "v", by="zz")
    with pytest.raises(ValueError):
        share(T, "v", by=[])
    with pytest.raises(ValueError):
        shift(T, "v", 0)
    with pytest.raises(ValueError):
        shift(T, "v", name="g")
