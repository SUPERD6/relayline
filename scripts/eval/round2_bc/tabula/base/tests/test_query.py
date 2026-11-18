import pytest

from tabula import QueryError, Table, compile_query, query
from tabula.query import tokenize

T = Table(["name", "qty", "kind", "ok"], [("pen", 3, "a", True), ("cup", None, "b", False), ("pad", 10, "a", None)])


def test_comparisons_and_logic():
    assert query(T, "qty >= 3 and kind == 'a'").column("name") == ["pen", "pad"]
    assert query(T, "not (kind == 'a') or qty < 5").column("name") == ["pen", "cup"]
    assert query(T, "name ~ 'p.*' and ok == true").column("name") == ["pen"]


def test_null_handling():
    assert query(T, "qty == null").column("name") == ["cup"]
    assert query(T, "qty != null").column("name") == ["pen", "pad"]
    assert query(T, "qty > 0").column("name") == ["pen", "pad"]     # None never compares
    with pytest.raises(QueryError):
        compile_query("qty > null", T.columns)


def test_strings_with_doubled_quotes():
    assert [t.value for t in tokenize("'it''s'")][:1] == ["it's"]
    assert [t.kind for t in tokenize('x == "a" and 2.5e1 < y')] == ["NAME", "OP", "STR", "KW", "NUM", "OP",
                                                                   "NAME", "END"]


def test_errors_carry_position():
    with pytest.raises(QueryError) as err:
        compile_query("qty > 1 and price < 2", T.columns)
    assert err.value.position == 12
    for bad in ("qty >", "(qty > 1", "qty > 1 )", "'open", "qty $ 1"):
        with pytest.raises(QueryError):
            compile_query(bad, T.columns)


def test_mixed_types_are_false():
    assert query(T, "name > 3").rows == []
