"""An immutable table: named columns and rows of values, optionally with the source line of each row."""
from __future__ import annotations

from collections import Counter
from typing import Any, Callable, Iterable


class Table:
    def __init__(self, columns: Iterable[str], rows: Iterable[tuple] = (), lines: Iterable[int] | None = None):
        self.columns = list(columns)
        self.rows = [tuple(r) for r in rows]
        for row in self.rows:
            if len(row) != len(self.columns):
                raise ValueError(f"row has {len(row)} values for {len(self.columns)} columns")
        self.lines = None if lines is None else list(lines)
        if self.lines is not None and len(self.lines) != len(self.rows):
            raise ValueError(f"{len(self.lines)} line numbers for {len(self.rows)} rows")

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

    def _derive(self, columns: list[str], rows: list[tuple], keep: list[int] | None = None) -> "Table":
        """A new table; `keep` lists, for each new row, the position of the old row it came from (default: the
        same positions), so the source lines follow their rows."""
        if self.lines is None:
            return Table(columns, rows)
        keep = list(range(len(rows))) if keep is None else keep
        return Table(columns, rows, lines=[self.lines[i] for i in keep])

    def select(self, *names: str) -> "Table":
        idx = [self.index(n) for n in names]
        return self._derive(list(names), [tuple(row[i] for i in idx) for row in self.rows])

    def where(self, predicate: Callable[[dict], bool]) -> "Table":
        keep = [k for k, row in enumerate(self.rows) if predicate(dict(zip(self.columns, row)))]
        return self._derive(self.columns, [self.rows[k] for k in keep], keep)

    def sort_by(self, column: str, reverse: bool = False) -> "Table":
        i = self.index(column)
        keep = sorted(range(len(self.rows)), key=lambda k: self.rows[k][i], reverse=reverse)
        return self._derive(self.columns, [self.rows[k] for k in keep], keep)

    def group_count(self, column: str) -> dict[Any, int]:
        return dict(Counter(self.column(column)))

    def to_dicts(self) -> list[dict]:
        return [dict(zip(self.columns, row)) for row in self.rows]
