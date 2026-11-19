from tabula import Table, render_markdown, render_text


def test_render_text_alignment():
    t = Table(["name", "qty"], [("pen", 3), ("notebook", None)])
    assert render_text(t) == "name      qty\n--------  ---\npen       3\nnotebook\n"


def test_render_text_bool():
    assert render_text(Table(["ok"], [(True,), (False,)])).splitlines()[2:] == ["yes", "no"]


def test_render_markdown_escapes_pipes():
    t = Table(["a|b"], [("x|y",)])
    assert render_markdown(t) == "| a\\|b |\n| --- |\n| x\\|y |\n"
