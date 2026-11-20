import pytest

from tabula import Table, from_jsonl, from_records, to_jsonl, to_records

REC = [{"id": 1, "who": {"nm": "ann", "geo": {"cc": "de"}}, "tags": ["x", "y"]},
       {"id": 2, "who": {"nm": "bo"}, "tags": []}]


def test_flatten_nested_dicts_into_path_columns():
    t = from_records(REC, flatten=True)
    assert t.columns == ["id", "who.nm", "who.geo.cc", "tags"]
    assert t.rows == [(1, "ann", "de", ["x", "y"]), (2, "bo", None, [])]
    assert from_records(REC).columns == ["id", "who", "tags"]


def test_flatten_with_another_separator_and_explicit_columns():
    assert from_records([{"a": {"b": 1}}], flatten=True, sep="/").columns == ["a/b"]
    assert from_records(REC, columns=["who.nm"], flatten=True).rows == [("ann",), ("bo",)]


def test_empty_nested_dict_is_a_plain_value():
    t = from_records([{"a": {}, "b": {"c": 1}}], flatten=True)
    assert t.columns == ["a", "b.c"] and t.rows == [({}, 1)]


def test_two_paths_with_one_name_collide():
    with pytest.raises(ValueError):
        from_records([{"a.b": 1, "a": {"b": 2}}], flatten=True)


def test_nest_is_the_inverse():
    t = from_records(REC, flatten=True)
    out = to_records(t, nest=True)
    assert out[0] == REC[0]
    assert out[1] == {"id": 2, "who": {"nm": "bo", "geo": {"cc": None}}, "tags": []}


def test_nest_with_drop_none_leaves_no_empty_dicts():
    t = from_records(REC, flatten=True)
    assert to_records(t, nest=True, drop_none=True)[1] == {"id": 2, "who": {"nm": "bo"}, "tags": []}
    t = Table(["k", "p.q", "p.r"], [(1, None, None)])
    assert to_records(t, nest=True, drop_none=True) == [{"k": 1}]


def test_value_column_cannot_also_be_a_parent():
    t = Table(["a", "a.b"], [(1, 2)])
    with pytest.raises(ValueError):
        to_records(t, nest=True)
    assert to_records(t) == [{"a": 1, "a.b": 2}]
    assert to_records(Table(["ab", "a.b"], [(1, 2)]), nest=True) == [{"ab": 1, "a": {"b": 2}}]


def test_jsonl_round_trip_through_nesting():
    t = from_records(REC, flatten=True)
    text = to_jsonl(t, nest=True)
    assert text.splitlines()[0] == '{"id":1,"who":{"nm":"ann","geo":{"cc":"de"}},"tags":["x","y"]}'
    assert from_jsonl(text, flatten=True) == t


def test_separator_must_not_be_empty():
    with pytest.raises(ValueError):
        from_records(REC, flatten=True, sep="")
    with pytest.raises(ValueError):
        to_records(Table(["a"], []), nest=True, sep="")
