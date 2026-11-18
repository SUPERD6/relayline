import pytest

from tabula import OneOf, Pattern, Range, Required, Table, Unique, clean_rows, summary, validate

T = Table(["id", "age", "code", "kind"], [(1, 30, "AB1", "a"), (2, -1, "x", "b"), (2, None, None, "z"),
                                          (None, 200, "CD9", "a")])


def test_violations_ordered_by_row_then_rule():
    rules = [Required("id"), Range("age", 0, 120), Pattern("code", r"[A-Z]{2}\d"), OneOf("kind", "ab"),
             Unique("id")]
    found = validate(T, rules)
    assert [(v.row, v.rule) for v in found] == [(1, "range"), (1, "pattern"), (2, "one_of"), (2, "unique"),
                                                (3, "required"), (3, "range")]
    assert found[0].message == "-1 is below 0" and found[3].message == "repeats row 1"


def test_missing_values_pass_other_rules():
    assert validate(Table(["a"], [(None,)]), [Range("a", 0, 1), Pattern("a", "x"), OneOf("a", [1])]) == []


def test_required_blank_text():
    assert len(validate(Table(["a"], [("  ",)]), [Required("a")])) == 1


def test_range_type_error_and_bad_bounds():
    assert validate(Table(["a"], [("x",)]), [Range("a", 0)])[0].message == "'x' cannot be compared"
    with pytest.raises(ValueError):
        Range("a", 5, 1)


def test_summary_and_clean_rows():
    rules = [Range("age", 0, 120), Unique("id")]
    assert summary(validate(T, rules)) == {"range": 2, "unique": 1}
    assert clean_rows(T, rules).column("id") == [1]


def test_unique_needs_columns():
    with pytest.raises(ValueError):
        Unique()
