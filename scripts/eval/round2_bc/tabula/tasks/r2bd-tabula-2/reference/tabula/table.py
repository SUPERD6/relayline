"""An immutable table: named columns and rows of values."""
from __future__ import annotations

from collections import Counter
from typing import Any, Callable, Iterable


class Table:
    def __init__(self, columns: Iterable[str], rows: Iterable[tuple] = ()):
        self.columns = list(columns)
        self.rows = [tuple(r) for r in rows]
        for row in self.rows:
            if len(row) != len(self.columns):
                raise ValueError(f"row has {len(row)} values for {len(self.columns)} columns")

    def __len__(self) -> int:
        return len(self.rows)

    def __eq__(self, other) -> bool:
        return isinstance(other, Table) and self.columns == other.columns and self.rows == other.rows

    def __repr__(self) -> str:
        return f"Table({self.columns!r}, {len(self.rows)} rows)"

    def index(self, column: str) -> int:
        try:
            return self.columns.index(column)
        except ValueError:
            raise KeyError(column) from None

    def column(self, name: str) -> list:
        i = self.index(name)
        return [row[i] for row in self.rows]

    def _derive(self, columns: list[str], rows: list[tuple]) -> "Table":
        return Table(columns, rows)

    def select(self, *names: str) -> "Table":
        idx = [self.index(n) for n in names]
        return self._derive(list(names), [tuple(row[i] for i in idx) for row in self.rows])

    def where(self, predicate: Callable[[dict], bool]) -> "Table":
        return self._derive(self.columns, [row for row in self.rows if predicate(dict(zip(self.columns, row)))])

    def _sort_key(self, key: str) -> tuple[int, bool]:
        """(column position, descending) for one sort key; a leading '-' means descending unless the table has a
        column with that exact name."""
        if key in self.columns or not key.startswith("-"):
            return self.index(key), False
        return self.index(key[1:]), True

    def sort_by(self, *keys: str, reverse: bool = False) -> "Table":
        """Stable sort by one or more keys, the first key most significant. `-name` sorts that key descending;
        `reverse` flips every key. Missing values (None) come after all other values of their key, whichever the
        direction."""
        if not keys:
            raise ValueError("sort_by needs at least one column")
        specs = [(i, desc != reverse) for i, desc in (self._sort_key(k) for k in keys)]
        rows = list(self.rows)
        for i, desc in reversed(specs):  # least significant first; sorted() is stable
            present = [r for r in rows if r[i] is not None]
            missing = [r for r in rows if r[i] is None]
            rows = sorted(present, key=lambda r: r[i], reverse=desc) + missing
        return self._derive(self.columns, rows)

    def group_count(self, column: str) -> dict[Any, int]:
        return dict(Counter(self.column(column)))

    def to_dicts(self) -> list[dict]:
        return [dict(zip(self.columns, row)) for row in self.rows]
