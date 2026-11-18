import pytest

from tabula import ParseError, read_rows, read_table


def test_plain_rows():
    assert read_rows("a,b\n1,2\n") == [["a", "b"], ["1", "2"]]


def test_quoted_delimiter_and_doubled_quote():
    assert read_rows('x,"a, b","say ""hi"""\n') == [["x", "a, b", 'say "hi"']]


def test_line_break_inside_quotes():
    assert read_rows('a,b\n"one\ntwo",3\n') == [["a", "b"], ["one\ntwo", "3"]]


def test_blank_lines_skipped_and_crlf():
    assert read_rows("a,b\r\n\r\n1,2\r\n") == [["a", "b"], ["1", "2"]]


def test_empty_fields_kept():
    assert read_rows("a,,c\n,,\n") == [["a", "", "c"], ["", "", ""]]


def test_other_delimiter():
    assert read_rows("a;b\n1;2", delimiter=";") == [["a", "b"], ["1", "2"]]


def test_unterminated_quote():
    with pytest.raises(ParseError) as err:
        read_rows('a\n"open\nmore')
    assert err.value.line == 2


def test_quote_inside_unquoted_field():
    with pytest.raises(ParseError):
        read_rows('ab"c\n')


def test_read_table_header_and_rows():
    t = read_table("name,qty\npen,3\ncup,1\n")
    assert t.columns == ["name", "qty"]
    assert t.rows == [("pen", "3"), ("cup", "1")]


def test_read_table_field_count_checked():
    with pytest.raises(ParseError) as err:
        read_table("a,b\n1,2\n3\n")
    assert err.value.line == 3


def test_read_table_duplicate_header():
    with pytest.raises(ParseError):
        read_table("a,a\n1,2\n")


def test_bad_delimiter_arguments():
    with pytest.raises(ValueError):
        read_rows("a", delimiter='"')
