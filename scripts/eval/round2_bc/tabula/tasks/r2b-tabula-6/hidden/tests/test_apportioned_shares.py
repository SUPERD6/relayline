import pytest

from tabula import Table, pivot, share
from tabula.stats import apportion


def test_rounded_parts_add_up_to_one():
    assert apportion([1, 1, 1], 2) == [0.34, 0.33, 0.33]
    assert apportion([2] * 7, 1) == [0.2, 0.2, 0.2, 0.1, 0.1, 0.1, 0.1]
    assert apportion([3, 3, 1], 2) == [0.43, 0.43, 0.14]


def test_largest_remainder_gets_the_unit_and_ties_go_first():
    assert apportion([1, 2], 1) == [0.3, 0.7]
    assert apportion([1, None, 3], 1) == [0.3, None, 0.7]
    assert apportion([1, 1], 0) == [1.0, 0.0]
    assert apportion([1, 4, 1], 1) == [0.2, 0.7, 0.1]


def test_zero_total_and_bad_values():
    assert apportion([0, None, 0], 2) == [None, None, None]
    for bad in ([1, -1], [True, 1], ["x"]):
        with pytest.raises(ValueError):
            apportion(bad, 2)
    with pytest.raises(ValueError):
        apportion([1], -1)


T = Table(["g", "v"], [("a", 1), ("b", 5), ("a", 1), ("a", 1), ("b", None)])


def test_share_digits_apportions_the_column():
    assert share(T, "v", digits=2).column("v_share") == [0.13, 0.63, 0.12, 0.12, None]


def test_share_per_group():
    assert share(T, "v", digits=2, by="g").column("v_share") == [0.34, 1.0, 0.33, 0.33, None]
    out = share(T, "v", by="g").column("v_share")
    assert out[0] == pytest.approx(1 / 3) and out[1] == 1.0 and out[4] is None


def test_share_arguments():
    with pytest.raises(ValueError):
        share(Table(["v"], [(-1,), (3,)]), "v", digits=1)
    assert share(Table(["v"], [(-1,), (3,)]), "v").column("v_share") == [-0.5, 1.5]
    with pytest.raises(ValueError):
        share(T, "v", by=[])
    with pytest.raises(KeyError):
        share(T, "v", by="zz")


S = Table(["r", "c", "q"], [("x", "a", 1), ("x", "b", 1), ("x", "c", 1), ("y", "a", 2), ("y", "b", None)])


def test_pivot_row_shares():
    out = pivot(S, "r", "c", "q", fill=0, normalize="rows", digits=2)
    assert out.columns == ["r", "a", "b", "c"]
    assert out.rows == [("x", 0.34, 0.33, 0.33), ("y", 1.0, None, 0)]
    assert pivot(S, "r", "c", "q", normalize="rows").rows[1] == ("y", 1.0, None, None)


def test_pivot_table_shares_in_row_major_order():
    t = Table(["r", "c", "q"], [("x", "a", 1), ("y", "a", 1), ("y", "b", 1)])
    assert pivot(t, "r", "c", "q", normalize="all", digits=1).rows == [("x", 0.4, None), ("y", 0.3, 0.3)]
    square = Table(["r", "c", "q"], [("x", "a", 1), ("x", "b", 1), ("y", "a", 1), ("y", "b", 1)])
    assert pivot(square, "r", "c", "q", normalize="all", digits=1).rows == [("x", 0.3, 0.3), ("y", 0.2, 0.2)]


def test_pivot_arguments():
    with pytest.raises(ValueError):
        pivot(S, "r", "c", "q", normalize="cols")
    with pytest.raises(ValueError):
        pivot(S, "r", "c", "q", digits=2)
