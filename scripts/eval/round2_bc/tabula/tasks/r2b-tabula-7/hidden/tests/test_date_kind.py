from datetime import date, datetime

import pytest

from tabula import CoercionError, Schema, Table, from_jsonl, infer_kind, infer_schema, kind_report, to_jsonl


def test_schema_reads_dates_and_datetimes():
    t = Table(["d", "n"], [("2026-03-04", "1"), (" 2026-03-04 05:06 ", "2"), ("", "3")])
    out = Schema({"d": "date", "n": "int"}).apply(t)
    assert out.column("d") == [date(2026, 3, 4), datetime(2026, 3, 4, 5, 6), None]


def test_impossible_day_is_a_coercion_error():
    with pytest.raises(CoercionError) as err:
        Schema({"d": "date"}).coerce_value("d", "2026-02-30")
    assert err.value.kind == "date" and err.value.value == "2026-02-30"


def test_inference_finds_dates_only_when_asked():
    vals = ["2026-01-05", "2026-01-06 10:00", ""]
    assert infer_kind(vals) == "str"
    assert infer_kind(vals, dates=True) == "date"
    assert infer_kind(["20260105", "20260106"], dates=True) == "int"
    assert infer_kind(["2026-01-05", "2026-02-30"], dates=True) == "str"
    assert infer_kind(["2026-01-05", "2026-01-06", "x"], threshold=0.6, dates=True) == "date"


def test_infer_schema_with_dates():
    t = Table(["d", "q"], [("2026-01-05", "1"), ("2026-01-07", "2")])
    assert infer_schema(t, dates=True).kinds == {"d": "date", "q": "int"}
    assert infer_schema(t).kinds == {"q": "int"}
    assert kind_report(t)["d"] == {"bool": 0, "int": 0, "float": 0, "str": 2, "empty": 0}


def test_jsonl_writes_iso_text():
    t = Table(["d", "x"], [(date(2026, 3, 4), 1), (datetime(2026, 3, 4, 5, 6, 7, 890), None)])
    assert to_jsonl(t) == '{"d":"2026-03-04","x":1}\n{"d":"2026-03-04T05:06:07","x":null}\n'


def test_jsonl_reads_dates_back():
    text = '{"d":"2026-03-04","x":1}\n{"d":"2026-03-04T05:06:07"}\n{"d":""}\n'
    t = from_jsonl(text, dates=["d"])
    assert t.column("d") == [date(2026, 3, 4), datetime(2026, 3, 4, 5, 6, 7), None]
    assert from_jsonl(text).column("d")[0] == "2026-03-04"
    back = Table(["d"], [(date(2026, 1, 2),), (datetime(2026, 1, 2, 3, 4),), (None,)])
    assert from_jsonl(to_jsonl(back), dates=["d"]) == back


def test_jsonl_date_errors():
    with pytest.raises(CoercionError) as err:
        from_jsonl('{"d": 5}\n', dates=["d"])
    assert err.value.column == "d" and err.value.kind == "date"
    with pytest.raises(CoercionError):
        from_jsonl('{"d": "soon"}\n', dates=["d"])
    with pytest.raises(KeyError):
        from_jsonl('{"d": "2026-03-04"}\n', dates=["e"])
