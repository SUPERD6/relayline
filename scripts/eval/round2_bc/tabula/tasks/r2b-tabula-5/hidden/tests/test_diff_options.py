import pytest

from tabula import Table, apply_diff, diff, render_diff

OLD = Table(["id", "qty", "ok", "note"], [(1, 3, True, "a"), (2, 1.5, False, "b"), (3, 5, None, "c"), (4, 0, True, "d")])
NEW = Table(["id", "qty", "ok", "note"], [(1, 3.0, 1, "a"), (2, 1.52, False, "B"), (3, 5, 0, "c"), (4, None, True, "d")])


def changes(d):
    return [c["changes"] for c in d.changed]


def test_types_matter_but_int_and_float_are_numbers():
    d = diff(OLD, NEW, "id")
    assert changes(d) == [{"ok": (True, 1)}, {"qty": (1.5, 1.52), "note": ("b", "B")}, {"ok": (None, 0)},
                          {"qty": (0, None)}]


def test_tolerance_for_numbers_only():
    d = diff(OLD, NEW, "id", tolerance=0.05)
    assert changes(d) == [{"ok": (True, 1)}, {"note": ("b", "B")}, {"ok": (None, 0)}, {"qty": (0, None)}]
    one, two = Table(["id", "v"], [(1, 1.0)]), Table(["id", "v"], [(1, 1.5)])
    assert diff(one, two, "id", tolerance=0.5).empty
    assert not diff(one, two, "id", tolerance=0.25).empty
    flags = diff(Table(["id", "f"], [(1, True)]), Table(["id", "f"], [(1, False)]), "id", tolerance=1)
    assert changes(flags) == [{"f": (True, False)}]


def test_tolerance_per_column():
    d = diff(OLD, NEW, "id", tolerance={"qty": 0.05})
    assert changes(d) == [{"ok": (True, 1)}, {"note": ("b", "B")}, {"ok": (None, 0)}, {"qty": (0, None)}]
    one, two = Table(["id", "a", "b"], [(1, 1.0, 1.0)]), Table(["id", "a", "b"], [(1, 1.25, 1.25)])
    assert changes(diff(one, two, "id", tolerance={"a": 0.5})) == [{"b": (1.0, 1.25)}]
    for bad in ({"id": 1}, {"zz": 1}, {"note": 1}):
        with pytest.raises(KeyError):
            diff(OLD, NEW, "id", tolerance=bad, ignore="note")
    with pytest.raises(ValueError):
        diff(OLD, NEW, "id", tolerance={"qty": -0.5})


def test_ignored_columns_are_not_compared_or_listed():
    d = diff(OLD, NEW, "id", ignore=["note", "ok"])
    assert changes(d) == [{"qty": (1.5, 1.52)}, {"qty": (0, None)}]
    extra = Table(["id", "x"], [(1, 0)])
    d = diff(extra, Table(["id", "y"], [(1, 0)]), "id", ignore="x")
    assert d.removed_columns == [] and d.added_columns == ["y"]


def test_bad_options():
    with pytest.raises(ValueError):
        diff(OLD, NEW, "id", ignore=["id"])
    with pytest.raises(KeyError):
        diff(OLD, NEW, "id", ignore=["zz"])
    with pytest.raises(ValueError):
        diff(OLD, NEW, "id", tolerance=-1)


def test_column_counts():
    counts = diff(OLD, NEW, "id").column_counts()
    assert list(counts.items()) == [("ok", 2), ("qty", 2), ("note", 1)]
    assert diff(OLD, OLD, "id").column_counts() == {}


def test_render_limit():
    d = diff(OLD, NEW, "id")
    assert render_diff(d, limit=2).splitlines() == ["~ id=1: ok: True -> 1",
                                                    "~ id=2: qty: 1.5 -> 1.52; note: 'b' -> 'B'", "... and 2 more"]
    assert render_diff(d, limit=4) == render_diff(d)
    narrow = diff(OLD.select("id", "qty", "note"), NEW.select("id", "qty"), "id")
    assert render_diff(narrow, limit=0) == "- column note\n... and 2 more\n"
    with pytest.raises(ValueError):
        render_diff(d, limit=-1)


def test_apply_keeps_ignored_values():
    out = apply_diff(OLD, diff(OLD, NEW, "id", ignore=["note"]))
    assert out.rows[1] == (2, 1.52, False, "b")
