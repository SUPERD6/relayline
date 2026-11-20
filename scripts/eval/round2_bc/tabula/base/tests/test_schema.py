import pytest

from tabula import CoercionError, Schema, Table


def test_kinds_applied():
    t = Table(["n", "x", "ok", "s"], [("1_000", "2.5", "Yes", "hi")])
    out = Schema({"n": "int", "x": "float", "ok": "bool"}).apply(t)
    assert out.rows == [(1000, 2.5, True, "hi")]


def test_empty_is_none():
    t = Table(["n"], [("",)])
    assert Schema({"n": "int"}).apply(t).rows == [(None,)]


def test_bad_value_names_column():
    t = Table(["n"], [("abc",)])
    with pytest.raises(CoercionError) as err:
        Schema({"n": "int"}).apply(t)
    assert err.value.column == "n" and err.value.value == "abc" and err.value.kind == "int"


def test_bool_rejects_other_words():
    with pytest.raises(CoercionError):
        Schema({"b": "bool"}).coerce_value("b", "maybe")


def test_unknown_kind():
    with pytest.raises(ValueError):
        Schema({"n": "decimal"})


def test_missing_column():
    with pytest.raises(KeyError):
        Schema({"zz": "int"}).apply(Table(["n"], []))
