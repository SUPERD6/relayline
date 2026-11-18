from tabula import Table, numeric_columns, render_markdown, render_text


def test_render_text_alignment():
    t = Table(["item", "qty"], [("pen", 3), ("notebook", None)])
    assert render_text(t) == "item      qty\n--------  ---\npen         3\nnotebook\n"


def test_render_text_bool():
    assert render_text(Table(["ok"], [(True,), (False,)])).splitlines()[2:] == ["yes", "no"]


def test_render_markdown_escapes_pipes():
    t = Table(["a|b"], [("x|y",)])
    assert render_markdown(t) == "| a\\|b |\n| --- |\n| x\\|y |\n"


def test_numeric_header_right_aligned_and_mixed_column_left():
    t = Table(["code", "price"], [("a1", 2.5), (7, 10.25)])
    out = render_text(t).splitlines()
    assert out[0] == "code  price"
    assert out[2] == "a1      2.5"
    assert out[3] == "7     10.25"


def test_bool_and_empty_columns_left_aligned():
    t = Table(["flag", "void", "n"], [(True, None, 1), (False, None, 22)])
    assert render_text(t).splitlines()[2:] == ["yes          1", "no          22"]


def test_numeric_columns_helper():
    t = Table(["i", "f", "b", "e", "s"], [(1, 2.0, True, None, "3"), (None, 1, False, None, "4")])
    assert numeric_columns(t) == [True, True, False, False, False]
    assert numeric_columns(Table(["x"], [])) == [False]


def test_markdown_alignment_row():
    t = Table(["what", "n", "ok"], [("x", 1, True)])
    assert render_markdown(t).splitlines()[1] == "| --- | ---: | --- |"
