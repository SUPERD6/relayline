import pytest

from tabula import (Table, blank_to_none, dedupe, drop_empty_rows, fill_missing, map_values, normalize_case,
                    strip)

T = Table(["a", "b"], [("  x  y ", 1), ("", None), ("z", None), ("  ", 4)])


def test_strip_and_collapse():
    assert strip(T, ["a"]).column("a") == ["x  y", "", "z", ""]
    assert strip(T, collapse=True).column("a")[0] == "x y"


def test_blank_to_none_and_drop_empty():
    t = blank_to_none(T)
    assert t.column("a") == ["  x  y ", None, "z", None]
    assert len(drop_empty_rows(t)) == 3


def test_fill_missing():
    assert fill_missing(T, 0, ["b"]).column("b") == [1, 0, 0, 4]
    assert fill_missing(T, columns=["b"], method="forward").column("b") == [1, 1, 1, 4]
    assert fill_missing(Table(["v"], [(None,), (2,)]), method="forward").column("v") == [None, 2]
    with pytest.raises(ValueError):
        fill_missing(T, method="back")


def test_dedupe():
    t = Table(["k", "v"], [(1, "a"), (2, "b"), (1, "c")])
    assert dedupe(t, ["k"]).column("v") == ["a", "b"]
    assert dedupe(t, ["k"], keep="last").column("v") == ["b", "c"]
    with pytest.raises(ValueError):
        dedupe(t, keep="middle")


def test_case_and_map():
    t = Table(["s"], [("hello World",), (None,)])
    assert normalize_case(t, ["s"], "title").column("s") == ["Hello World", None]
    assert map_values(t, lambda v: 0, skip_none=False).column("s") == [0, 0]
    with pytest.raises(ValueError):
        normalize_case(t, ["s"], "camel")
