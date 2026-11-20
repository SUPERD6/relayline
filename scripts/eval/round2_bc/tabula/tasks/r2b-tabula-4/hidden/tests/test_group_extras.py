import pytest

from tabula import AGGREGATES, Table, group_by, pivot
from tabula.aggregate import top_n

SALES = Table(["reg", "item", "qty"], [("n", "pen", 3), ("s", "pen", 1), ("n", "cup", None), ("n", "pad", 3),
                                       (None, "cup", 4), ("s", "box", 1), ("n", "box", 5)])


def test_common_value_tie_goes_to_first_seen():
    t = Table(["g", "v"], [("a", 5), ("a", 2), ("a", 2), ("a", 5), ("a", None), ("b", None), ("c", 7), ("c", 1)])
    assert group_by(t, "g", m=("v", "common")).rows == [("a", 5), ("b", None), ("c", 7)]
    assert "common" in AGGREGATES


def test_percentile_names():
    t = Table(["g", "v"], [("a", 1), ("a", 2), ("a", 3), ("a", 4), ("a", None), ("b", 8), ("c", None)])
    out = group_by(t, "g", lo=("v", "p0"), q=("v", "p25"), m=("v", "p50"), hi=("v", "p100"))
    assert out.rows == [("a", 1, 1, 2, 4), ("b", 8, 8, 8, 8), ("c", None, None, None, None)]
    out = group_by(t, "g", x=("v", "p30"), y=("v", "p51"), z=("v", "p99"))
    assert out.rows[0] == ("a", 2, 3, 4)


def test_percentile_is_always_a_value_of_the_group():
    t = Table(["g", "v"], [("a", 20), ("a", None), ("a", 10)])
    out = group_by(t, "g", m=("v", "p50"), u=("v", "p75"), w=("v", "p1"))
    assert out.rows == [("a", 10, 20, 10)]


@pytest.mark.parametrize("bad", ["p101", "p", "p05", "p2.5", "q50", "P50", "p-1"])
def test_bad_percentile_names(bad):
    with pytest.raises(ValueError):
        group_by(SALES, "reg", x=("qty", bad))


def test_pivot_takes_new_names():
    out = pivot(SALES, "reg", "item", "qty", func="p50")
    assert out.columns == ["reg", "box", "cup", "pad", "pen"]
    assert out.rows == [("n", 5, None, 3, 3), ("s", 1, None, None, 1), (None, None, 4, None, None)]
    assert pivot(SALES, "reg", "item", "qty", func="common").rows[0] == ("n", 5, None, 3, 3)


def test_dropna_leaves_out_missing_keys():
    assert group_by(SALES, "reg", total=("qty", "sum")).rows[-1] == (None, 4)
    assert group_by(SALES, "reg", dropna=True, total=("qty", "sum")).rows == [("n", 11), ("s", 2)]
    out = group_by(SALES, ["reg", "item"], dropna=True, k=("qty", "sum"))
    assert (None, "cup", 4) not in out.rows and len(out) == 6


def test_top_rows_per_group():
    assert top_n(SALES, "reg", "qty", 1).rows == [("n", "box", 5), ("s", "pen", 1), (None, "cup", 4)]
    assert top_n(SALES, "reg", "qty", 2).rows == [("n", "box", 5), ("n", "pen", 3), ("s", "pen", 1),
                                                  ("s", "box", 1), (None, "cup", 4)]


def test_smallest_rows_keep_tie_order():
    assert top_n(SALES, "reg", "qty", 2, largest=False).rows == [("n", "pen", 3), ("n", "pad", 3), ("s", "pen", 1),
                                                                 ("s", "box", 1), (None, "cup", 4)]


def test_missing_values_are_never_chosen():
    t = Table(["g", "v"], [("a", None), ("b", 1), ("a", None)])
    assert top_n(t, "g", "v", 3).rows == [("b", 1)]
    assert top_n(t, ["g"], "v", 1).columns == ["g", "v"]


def test_top_n_arguments():
    with pytest.raises(ValueError):
        top_n(SALES, "reg", "qty", 0)
    with pytest.raises(ValueError):
        top_n(SALES, [], "qty", 1)
    with pytest.raises(KeyError):
        top_n(SALES, "reg", "price", 1)
