import pytest

from tabula import Table, infer_kind, infer_schema, kind_report


def test_narrowest_kind():
    assert infer_kind(["1", "-2", "3_000"]) == "int"
    assert infer_kind(["1", "2.5"]) == "float"
    assert infer_kind(["yes", "no", "1"]) == "bool"
    assert infer_kind(["0", "1", "1"]) == "int"
    assert infer_kind(["a", "1"]) == "str"
    assert infer_kind(["", None]) == "str"


def test_nan_is_not_a_float():
    assert infer_kind(["1.5", "nan"]) == "str"


def test_threshold():
    assert infer_kind(["1", "2", "3", "x"], threshold=0.75) == "int"
    with pytest.raises(ValueError):
        infer_kind(["1"], threshold=0)


def test_infer_schema_and_apply():
    t = Table(["id", "price", "ok", "name"], [("1", "2.5", "true", "pen"), ("2", "", "no", "cup")])
    schema = infer_schema(t)
    assert schema.kinds == {"id": "int", "price": "float", "ok": "bool"}
    assert schema.apply(t).rows == [(1, 2.5, True, "pen"), (2, None, False, "cup")]


def test_keep_text_and_sample():
    t = Table(["zip", "n"], [("01234", "1"), ("99999", "x")])
    assert infer_schema(t, keep_text=["zip"], sample=1).kinds == {"n": "int"}
    with pytest.raises(KeyError):
        infer_schema(t, keep_text=["nope"])


def test_kind_report():
    t = Table(["v"], [("1",), ("x",), ("",)])
    assert kind_report(t) == {"v": {"bool": 1, "int": 1, "float": 1, "str": 2, "empty": 1}}
