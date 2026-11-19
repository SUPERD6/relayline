import pytest

from tabula import CoercionError, ParseError, Schema, Table, read_table

TEXT = 'item,qty\n"multi\nrow",4\n\nplain,x\nlast,7\n'


def test_rows_record_their_start_line():
    t = read_table(TEXT)
    assert t.lines == [2, 5, 6]


def test_field_count_error_uses_start_line():
    with pytest.raises(ParseError) as err:
        read_table('a,b\n"p\nq",1\n\nlonely\n')
    assert err.value.line == 5


def test_lines_follow_rows():
    t = read_table(TEXT)
    assert t.where(lambda r: r["item"] != "plain").lines == [2, 6]
    assert t.sort_by("item").lines == [6, 2, 5]
    assert t.select("qty").lines == [2, 5, 6]


def test_coercion_error_names_line():
    with pytest.raises(CoercionError) as err:
        Schema({"qty": "int"}).apply(read_table(TEXT))
    assert err.value.line == 5 and err.value.column == "qty" and err.value.value == "x"
    assert str(err.value).startswith("line 5: ")


def test_coerced_table_keeps_lines():
    t = read_table("qty\n1\n\n2\n")
    assert Schema({"qty": "int"}).apply(t).lines == [2, 4]


def test_null_tokens_per_column():
    t = Table(["n", "s"], [(" NA ", "NA"), ("-", "-"), ("na", "ok")])
    schema = Schema({"n": "int"}, nulls={"n": ["NA", "-"]})
    assert schema.coerce_value("n", " NA ") is None
    assert schema.coerce_value("n", "-") is None
    assert schema.apply(t.select("n", "s").where(lambda r: r["n"] != "na")).rows == [(None, "NA"), (None, "-")]
    with pytest.raises(CoercionError):
        schema.coerce_value("n", "na")


def test_null_token_column_must_exist():
    with pytest.raises(KeyError):
        Schema({}, nulls={"zz": ["?"]}).apply(Table(["a"], [("1",)]))


def test_table_without_lines():
    t = Table(["n"], [("bad",)])
    assert t.lines is None and t.where(lambda r: True).lines is None
    with pytest.raises(CoercionError) as err:
        Schema({"n": "int"}).apply(t)
    assert err.value.line is None and str(err.value) == str(CoercionError("n", "bad", "int"))


def test_line_count_must_match_rows():
    with pytest.raises(ValueError):
        Table(["a"], [(1,)], lines=[1, 2])
