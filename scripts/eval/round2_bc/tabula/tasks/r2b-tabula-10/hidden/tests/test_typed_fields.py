import pytest

from tabula import ParseError, Table, read_rows, read_table, write_rows, write_table
from tabula.writer import format_field


def test_quoting_decides_the_type():
    assert read_rows('1,-2.5,"3","x",1e3,.5\n', quoting="nonnumeric") == [[1, -2.5, "3", "x", 1000.0, 0.5]]


def test_quoted_empty_text_is_not_missing():
    assert read_rows('"",,""""\n', quoting="nonnumeric") == [["", None, '"']]


def test_boolean_words():
    assert read_rows('true,false,"true"\n', quoting="nonnumeric") == [[True, False, "true"]]
    assert read_rows("Y,N\n", quoting="nonnumeric", true="Y", false="N") == [[True, False]]


def test_unquoted_text_is_an_error_on_its_line():
    with pytest.raises(ParseError) as err:
        read_rows('"a\nb",1\n3,abc\n', quoting="nonnumeric")
    assert err.value.line == 3


@pytest.mark.parametrize("bad", ["nan", " 3", "1_000", "+3", "True", "inf", "1.2.3"])
def test_not_quite_numbers(bad):
    with pytest.raises(ParseError):
        read_rows(bad + "\n", quoting="nonnumeric")


def test_default_reading_is_unchanged():
    assert read_rows('1,"",\n') == [["1", "", ""]]
    with pytest.raises(ValueError):
        read_rows("a\n", quoting="all")


def test_header_is_always_text():
    t = read_table('id,"2",x\n1,"a",\n', quoting="nonnumeric")
    assert t.columns == ["id", "2", "x"] and t.rows == [(1, "a", None)]


def test_writer_round_trip():
    t = Table(["id", "nm", "x", "ok", "z"], [(1, "007", 2.5, True, None), (2, "", -3.0, False, "a,b")])
    text = write_table(t, quoting="nonnumeric")
    assert text == '"id","nm","x","ok","z"\n1,"007",2.5,true,\n2,"",-3.0,false,"a,b"\n'
    assert read_table(text, quoting="nonnumeric") == t
    assert write_rows([[True, False]], quoting="nonnumeric", true="Y", false="N") == "Y,N\n"


def test_non_finite_floats_are_refused():
    for value in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError):
            format_field(value, quoting="nonnumeric")
    assert format_field(float("inf")) == "inf"
