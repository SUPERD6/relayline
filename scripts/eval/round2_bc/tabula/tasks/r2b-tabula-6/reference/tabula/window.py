"""Window functions over a column, in row order: rolling aggregates, ranks, differences, shifts. With `by`, each
function runs separately inside every group of rows sharing the same `by` values, and the results stay in the
table's row order."""
from __future__ import annotations

from typing import Callable, Iterable

from .table import Table


def _add(table: Table, name: str, values: list) -> Table:
    if name in table.columns:
        raise ValueError(f"column {name!r} already exists")
    return Table(table.columns + [name], [row + (v,) for row, v in zip(table.rows, values)])


def _over(table: Table, column: str, by: str | Iterable[str] | None, compute: Callable[[list], list]) -> list:
    """`compute` applied to the column's values of each group (row order inside the group), put back in place."""
    col = table.column(column)
    if by is None:
        return compute(col)
    keys = [by] if isinstance(by, str) else list(by)
    if not keys:
        raise ValueError("by needs at least one column")
    idx = [table.index(k) for k in keys]
    groups: dict[tuple, list[int]] = {}
    for n, row in enumerate(table.rows):
        groups.setdefault(tuple(row[i] for i in idx), []).append(n)
    out: list = [None] * len(col)
    for positions in groups.values():
        for n, value in zip(positions, compute([col[n] for n in positions])):
            out[n] = value
    return out


def rolling_mean(table: Table, column: str, size: int, name: str | None = None, min_values: int = 1,
                 by: str | Iterable[str] | None = None) -> Table:
    """Mean of the last `size` rows' values (the current row included), ignoring None; None when fewer than
    `min_values` numbers are in the window."""
    if size < 1 or min_values < 1:
        raise ValueError("size and min_values must be at least 1")

    def compute(col):
        out = []
        for n in range(len(col)):
            window = [v for v in col[max(0, n - size + 1):n + 1] if v is not None]
            out.append(sum(window) / len(window) if len(window) >= min_values else None)
        return out
    return _add(table, name or f"{column}_mean{size}", _over(table, column, by, compute))


def rank(table: Table, column: str, name: str | None = None, descending: bool = False,
         method: str = "min", by: str | Iterable[str] | None = None) -> Table:
    """Rank of each value (1 = smallest, or largest when `descending`). Ties get the lowest rank of the tie
    (`min`) or consecutive ranks without gaps (`dense`). None values get rank None."""
    if method not in ("min", "dense"):
        raise ValueError("method must be 'min' or 'dense'")

    def compute(col):
        present = sorted({v for v in col if v is not None}, reverse=descending)
        if method == "dense":
            ranks = {v: k for k, v in enumerate(present, 1)}
        else:
            ordered = sorted((v for v in col if v is not None), reverse=descending)
            ranks = {}
            for k, v in enumerate(ordered, 1):
                ranks.setdefault(v, k)
        return [None if v is None else ranks[v] for v in col]
    return _add(table, name or f"{column}_rank", _over(table, column, by, compute))


def difference(table: Table, column: str, name: str | None = None, lag: int = 1,
               by: str | Iterable[str] | None = None) -> Table:
    """Value minus the value `lag` rows earlier; None for the first rows and wherever either value is None."""
    if lag < 1:
        raise ValueError("lag must be at least 1")

    def compute(col):
        return [None if n < lag or col[n] is None or col[n - lag] is None else col[n] - col[n - lag]
                for n in range(len(col))]
    return _add(table, name or f"{column}_diff", _over(table, column, by, compute))


def share(table: Table, column: str, name: str | None = None, digits: int | None = None,
          by: str | Iterable[str] | None = None) -> Table:
    """Each value divided by the column total (None values count as 0 in the total and stay None)."""
    def compute(col):
        total = sum(v for v in col if v is not None)
        return [None if v is None or total == 0 else (round(v / total, digits) if digits is not None else v / total)
                for v in col]
    return _add(table, name or f"{column}_share", _over(table, column, by, compute))


def shift(table: Table, column: str, periods: int = 1, name: str | None = None, fill=None,
          by: str | Iterable[str] | None = None) -> Table:
    """The value `periods` rows earlier (a negative number looks that many rows ahead); `fill` where there is no
    such row. A None value is copied as None, never replaced by `fill`."""
    if not isinstance(periods, int) or isinstance(periods, bool) or periods == 0:
        raise ValueError("periods must be a non-zero whole number")

    def compute(col):
        return [col[n - periods] if 0 <= n - periods < len(col) else fill for n in range(len(col))]
    return _add(table, name or f"{column}_shift{periods}", _over(table, column, by, compute))
