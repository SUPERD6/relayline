import pytest

from tabula import Table, group_by, pivot, running_total

SALES = Table(["region", "item", "qty"], [("n", "pen", 3), ("s", "pen", 1), ("n", "cup", None), ("n", "pen", 2),
                                          (None, "cup", 4)])


def test_group_by_first_appearance_order():
    out = group_by(SALES, "region", total=("qty", "sum"), n=("qty", "rows"), counted=("qty", "count"))
    assert out.columns == ["region", "total", "n", "counted"]
    assert out.rows == [("n", 5, 3, 2), ("s", 1, 1, 1), (None, 4, 1, 1)]


def test_group_by_two_keys_and_callable():
    out = group_by(SALES, ["region", "item"], top=("qty", lambda vs: max(v or 0 for v in vs)))
    assert out.rows == [("n", "pen", 3), ("s", "pen", 1), ("n", "cup", 0), (None, "cup", 4)]


def test_aggregates_skip_missing():
    out = group_by(SALES, "item", mean=("qty", "mean"), med=("qty", "median"), lo=("qty", "min"),
                   hi=("qty", "max"), first=("region", "first"), last=("region", "last"), d=("region", "distinct"))
    assert out.rows[0] == ("pen", 2.0, 2, 1, 3, "n", "n", 2)
    assert out.rows[1] == ("cup", 4.0, 4, 4, 4, "n", "n", 1)


def test_std_and_empty_groups():
    t = Table(["g", "v"], [("a", 2), ("a", 4), ("b", None)])
    out = group_by(t, "g", s=("v", "std"), total=("v", "sum"))
    assert out.rows[0][1] == pytest.approx(1.41421356)
    assert out.rows[1] == ("b", None, None)


def test_group_by_errors():
    with pytest.raises(ValueError):
        group_by(SALES, [])
    with pytest.raises(ValueError):
        group_by(SALES, "region", region=("qty", "sum"))
    with pytest.raises(ValueError):
        group_by(SALES, "region", x=("qty", "mode"))
    with pytest.raises(TypeError):
        group_by(SALES, "region", x="qty")


def test_pivot():
    out = pivot(SALES, "region", "item", "qty", fill=0)
    assert out.columns == ["region", "cup", "pen"]
    assert out.rows == [("n", None, 5), ("s", 0, 1), (None, 4, 0)]


def test_running_total():
    out = running_total(SALES, "qty")
    assert out.column("qty_total") == [3, 4, 4, 6, 10]
    with pytest.raises(ValueError):
        running_total(out, "qty")
