"""Column types and coercion of text values."""
from __future__ import annotations

from .errors import CoercionError
from .table import Table

TRUE = {"true", "yes", "1"}
FALSE = {"false", "no", "0"}


def _int(text: str) -> int:
    return int(text.replace("_", ""))


def _float(text: str) -> float:
    return float(text)


def _bool(text: str) -> bool:
    low = text.strip().lower()
    if low in TRUE:
        return True
    if low in FALSE:
        return False
    raise ValueError(text)


KINDS = {"int": _int, "float": _float, "bool": _bool, "str": str}


class Schema:
    """Maps column names to kinds (int, float, bool, str). Columns not named stay text. An empty value is None."""

    def __init__(self, kinds: dict[str, str]):
        unknown = sorted(set(kinds.values()) - set(KINDS))
        if unknown:
            raise ValueError(f"unknown kind(s): {', '.join(unknown)}")
        self.kinds = dict(kinds)

    def coerce_value(self, column: str, text):
        if text is None or text == "":
            return None
        kind = self.kinds.get(column, "str")
        try:
            return KINDS[kind](text)
        except ValueError:
            raise CoercionError(column, text, kind) from None

    def apply(self, table: Table) -> Table:
        missing = sorted(set(self.kinds) - set(table.columns))
        if missing:
            raise KeyError(", ".join(missing))
        rows = [tuple(self.coerce_value(c, v) for c, v in zip(table.columns, row)) for row in table.rows]
        return table._derive(table.columns, rows)
