import pytest

from tabula import Table, column_stats, correlation, describe, histogram, quantile


def test_quantile_interpolates():
    assert quantile([1, 2, 3, 4], 0.5) == 2.5
    assert quantile([5], 0.9) == 5
    assert quantile([], 0.5) is None
    with pytest.raises(ValueError):
        quantile([1], 2)


def test_column_stats_ignores_non_numbers():
    s = column_stats([1, 2, None, "x", True, 3])
    assert s["count"] == 3 and s["missing"] == 1 and s["mean"] == 2 and s["median"] == 2
    assert s["std"] == pytest.approx(1.0)


def test_describe_default_columns_and_rounding():
    t = Table(["name", "a", "b"], [("x", 1, 2.0), ("y", 2, None), ("z", 4, 3.0)])
    d = describe(t, digits=2)
    assert d.columns == ["stat", "a", "b"]
    rows = dict((r[0], r[1:]) for r in d.rows)
    assert rows["count"] == (3, 2) and rows["missing"] == (0, 1)
    assert rows["mean"] == (2.33, 2.5) and rows["max"] == (4, 3.0)


def test_describe_rejects_stat_column():
    with pytest.raises(ValueError):
        describe(Table(["stat"], [(1,)]))


def test_histogram():
    assert histogram([0, 1, 2, 3, 4], bins=2) == [(0, 2.0, 2), (2.0, 4.0, 3)]
    assert histogram([10, 50], bins=1, low=0, high=20) == [(0, 20, 1)]
    assert histogram([]) == []
    with pytest.raises(ValueError):
        histogram([1], bins=0)


def test_correlation():
    assert correlation([1, 2, 3], [2, 4, 6]) == pytest.approx(1.0)
    assert correlation([1, 2, None], [3, 2, 1]) == pytest.approx(-1.0)
    assert correlation([1, 1], [2, 3]) is None
