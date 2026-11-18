import pytest

from tabula import Table, read_rows, write_rows, write_table
from tabula.writer import column_widths, format_field


def test_minimal_quoting_round_trip():
    rows = [["a", "b,c", 'say "x"', "two\nlines", " pad"]]
    text = write_rows(rows)
    assert text == 'a,"b,c","say ""x""","two\nlines"," pad"\n'
    assert read_rows(text) == rows


def test_values_written_as_text():
    assert write_rows([[1, 2.0, 2.5, True, None]]) == "1,2.0,2.5,true,\n"
    assert write_rows([[True, False]], true="Y", false="N") == "Y,N\n"


def test_quoting_modes():
    assert format_field("x", quoting="all") == '"x"'
    assert format_field(3, quoting="nonnumeric") == "3"
    assert format_field("3", quoting="nonnumeric") == '"3"'
    assert format_field(None, quoting="nonnumeric") == ""
    with pytest.raises(ValueError):
        format_field("a,b", quoting="none")
    with pytest.raises(ValueError):
        format_field("a", quoting="sometimes")


def test_write_table_header_and_crlf():
    t = Table(["n", "s"], [(1, "x")])
    assert write_table(t) == "n,s\n1,x\n"
    assert write_table(t, header=False, line_end="\r\n") == "1,x\r\n"
    assert write_table(t, quoting="nonnumeric") == '"n","s"\n1,"x"\n'


def test_bad_arguments():
    with pytest.raises(ValueError):
        write_rows([["a"]], delimiter=";;")
    with pytest.raises(ValueError):
        write_rows([["a"]], line_end="\r")


def test_column_widths():
    t = Table(["id", "note"], [(7, "a,b"), (1234, "c")])
    assert column_widths(t) == {"id": 4, "note": 5}
