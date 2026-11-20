import pytest

from tabula import ParseError, Table, read_rows, read_table, write_rows, write_table


def test_comment_lines_are_skipped():
    assert read_rows("# made by me\na,b\n#x,y\n1,2\n", comment="#") == [["a", "b"], ["1", "2"]]
    assert read_rows("a;b\r\n%x;y\r\n1;2", delimiter=";", comment="%") == [["a", "b"], ["1", "2"]]


def test_marker_elsewhere_is_ordinary_text():
    assert read_rows('a,#b\n #c,d\n"#e",f\n', comment="#") == [["a", "#b"], [" #c", "d"], ["#e", "f"]]
    assert read_rows('a\n"x\n#y"\n', comment="#") == [["a"], ["x\n#y"]]


def test_without_a_marker_nothing_is_a_comment():
    assert read_rows("#a,b\n") == [["#a", "b"]]


def test_comment_line_may_hold_quotes():
    assert read_rows('#say "hi\nk\n', comment="#") == [["k"]]


def test_error_lines_count_comment_lines():
    with pytest.raises(ParseError) as err:
        read_table("h1,h2\n# skip\n#\n1,2\n3\n", comment="#")
    assert err.value.line == 5
    t = read_table("#top\nh1,h2\n1,2\n", comment="#")
    assert t.columns == ["h1", "h2"] and t.rows == [("1", "2")]


@pytest.mark.parametrize("mk", [",", '"', "##", ""])
def test_bad_markers(mk):
    with pytest.raises(ValueError):
        read_rows("a\n", comment=mk)


def test_preamble_lines():
    t = Table(["a", "b"], [(1, "x")])
    assert write_table(t, comment="#", preamble=["made by me", ""]) == "# made by me\n#\na,b\n1,x\n"
    assert write_table(t, comment=";", preamble=["v2"], line_end="\r\n") == "; v2\r\na,b\r\n1,x\r\n"


def test_preamble_needs_marker_and_single_lines():
    t = Table(["a"], [(1,)])
    with pytest.raises(ValueError):
        write_table(t, preamble=["x"])
    with pytest.raises(ValueError):
        write_table(t, comment="#", preamble=["two\nlines"])


def test_first_field_starting_with_marker_is_quoted():
    t = Table(["#k", "v"], [("#1", "#2"), ("ok", "#3")])
    text = write_table(t, comment="#")
    assert text == '"#k",v\n"#1",#2\nok,#3\n'
    assert read_table(text, comment="#") == t
    assert write_rows([["#1"]]) == "#1\n"
    assert write_rows([["#1", "#2"]], comment="#") == '"#1",#2\n'


def test_marker_field_cannot_be_written_unquoted():
    with pytest.raises(ValueError):
        write_rows([["#1"]], comment="#", quoting="none")
    assert write_rows([["#1"]], comment="#", quoting="all") == '"#1"\n'
