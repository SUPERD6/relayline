import pytest

from tabula import Table, difference, rank, rolling_mean, share

T = Table(["v"], [(4,), (None,), (2,), (4,), (10,)])


def test_rolling_mean():
    assert rolling_mean(T, "v", 2).column("v_mean2") == [4, 4, 2, 3, 7]
    assert rolling_mean(T, "v", 2, min_values=2).column("v_mean2") == [None, None, None, 3, 7]
    with pytest.raises(ValueError):
        rolling_mean(T, "v", 0)


def test_rank_methods():
    assert rank(T, "v").column("v_rank") == [2, None, 1, 2, 4]
    assert rank(T, "v", method="dense").column("v_rank") == [2, None, 1, 2, 3]
    assert rank(T, "v", descending=True).column("v_rank") == [2, None, 4, 2, 1]
    with pytest.raises(ValueError):
        rank(T, "v", method="avg")


def test_difference_and_share():
    assert difference(T, "v").column("v_diff") == [None, None, None, 2, 6]
    assert difference(T, "v", lag=2).column("v_diff") == [None, None, -2, None, 8]
    assert share(T, "v", digits=2).column("v_share") == [0.2, None, 0.1, 0.2, 0.5]


def test_name_clash():
    with pytest.raises(ValueError):
        share(T, "v", name="v")
