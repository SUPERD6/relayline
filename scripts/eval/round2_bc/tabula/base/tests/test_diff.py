import pytest

from tabula import Table, apply_diff, diff, render_diff

OLD = Table(["id", "qty", "note"], [(1, 3, "a"), (2, 1, "b"), (3, 5, "c")])
NEW = Table(["id", "qty", "tag"], [(3, 6, "t"), (1, 3, "u"), (4, 2, "v")])


def test_added_removed_changed():
    d = diff(OLD, NEW, "id")
    assert [r["id"] for r in d.added] == [4]
    assert [r["id"] for r in d.removed] == [2]
    assert d.changed == [{"key": {"id": 3}, "changes": {"qty": (5, 6)}}]
    assert d.added_columns == ["tag"] and d.removed_columns == ["note"]
    assert d.counts() == {"added": 1, "removed": 1, "changed": 1} and not d.empty


def test_render():
    text = render_diff(diff(OLD, NEW, "id"))
    assert text.splitlines() == ["+ column tag", "- column note", "+ id=4", "- id=2", "~ id=3: qty: 5 -> 6"]
    assert render_diff(diff(OLD, OLD, "id")) == ""


def test_apply_diff():
    out = apply_diff(OLD, diff(OLD, NEW, "id"))
    assert out.rows == [(1, 3, "a"), (3, 6, "c"), (4, 2, None)]


def test_key_must_be_unique():
    with pytest.raises(ValueError):
        diff(Table(["id"], [(1,), (1,)]), OLD, "id")
    with pytest.raises(ValueError):
        diff(OLD, NEW, [])
