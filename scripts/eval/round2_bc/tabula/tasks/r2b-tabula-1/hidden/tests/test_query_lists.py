import pytest

from tabula import QueryError, Table, compile_query, query

T = Table(["sku", "qty", "kind"], [("a1", 3, "x"), ("b2", None, "y"), ("c3", 7, "z"), ("d4", 5, "x")])


def skus(text):
    return query(T, text).column("sku")


def test_in_matches_any_listed_value():
    assert skus("kind in ('x', 'z')") == ["a1", "c3", "d4"]
    assert skus("qty in (5, 3)") == ["a1", "d4"]
    assert skus("qty in (4)") == []


def test_listed_null_matches_missing_values():
    assert skus("qty in (null, 7)") == ["b2", "c3"]


def test_not_in_is_never_true_for_a_missing_value():
    assert skus("qty not in (3)") == ["c3", "d4"]
    assert skus("not qty in (3)") == ["b2", "c3", "d4"]


def test_between_is_inclusive_and_owns_its_and():
    assert skus("qty between 3 and 5") == ["a1", "d4"]
    assert skus("qty between 3 and 7 and kind == 'x'") == ["a1", "d4"]
    assert skus("qty between 7 and 3") == []


def test_between_is_false_for_missing_or_mixed_values():
    assert skus("kind between 1 and 9") == []
    assert skus("qty between 0 and 9 or sku == 'b2'") == ["a1", "b2", "c3", "d4"]


def test_new_keywords_ignore_case():
    assert skus("qty IN (3) or qty BETWEEN 6 AND 8") == ["a1", "c3"]


def test_list_errors_carry_position():
    with pytest.raises(QueryError) as err:
        compile_query("qty in 3", T.columns)
    assert err.value.position == 7
    with pytest.raises(QueryError) as err:
        compile_query("qty in (1, kind)", T.columns)
    assert err.value.position == 11


@pytest.mark.parametrize("bad", ["qty in ()", "qty in (1 2)", "qty between 1", "qty not 3",
                                 "qty between null and 3"])
def test_malformed_lists_and_ranges_are_rejected(bad):
    with pytest.raises(QueryError):
        compile_query(bad, T.columns)
