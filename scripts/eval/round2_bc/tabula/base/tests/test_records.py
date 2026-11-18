import pytest

from tabula import ParseError, Table, concat, from_jsonl, from_records, rename, to_jsonl, to_records


def test_from_records_union_of_keys():
    t = from_records([{"a": 1}, {"b": 2, "a": 3}])
    assert t.columns == ["a", "b"] and t.rows == [(1, None), (3, 2)]
    assert from_records([{"a": 1, "z": 9}], columns=["a"]).rows == [(1,)]


def test_to_records_drop_none():
    t = Table(["a", "b"], [(1, None)])
    assert to_records(t) == [{"a": 1, "b": None}]
    assert to_records(t, drop_none=True) == [{"a": 1}]


def test_jsonl_round_trip():
    t = Table(["k", "v"], [("é", 1.5), ("x", None)])
    text = to_jsonl(t)
    assert text == '{"k":"é","v":1.5}\n{"k":"x","v":null}\n'
    assert from_jsonl(text + "\n") == t


def test_jsonl_errors_name_line():
    with pytest.raises(ParseError) as err:
        from_jsonl('{"a": 1}\n\n[1]\n')
    assert err.value.line == 3
    with pytest.raises(ParseError):
        from_jsonl("{oops}")


def test_rename_and_concat():
    t = Table(["a", "b"], [(1, 2)])
    assert rename(t, {"a": "x"}).columns == ["x", "b"]
    with pytest.raises(ValueError):
        rename(t, {"a": "b"})
    with pytest.raises(KeyError):
        rename(t, {"zz": "y"})
    out = concat([t, Table(["b", "c"], [(5, 6)])], fill=0)
    assert out.columns == ["a", "b", "c"] and out.rows == [(1, 2, 0), (0, 5, 6)]
