"""Window functions over a column, in row order: rolling aggregates, ranks, differences."""
from __future__ import annotations

from typing import Iterable

from .stats import apportion
from .table import Table


def _add(table: Table, name: str, values: list) -> Table:
    if name in table.columns:
        raise ValueError(f"column {name!r} already exists")
    return Table(table.columns + [name], [row + (v,) for row, v in zip(table.rows, values)])


def rolling_mean(table: Table, column: str, size: int, name: str | None = None, min_values: int = 1) -> Table:
    """Mean of the last `size` rows' values (the current row included), ignoring None; None when fewer than
    `min_values` numbers are in the window."""
    if size < 1 or min_values < 1:
        raise ValueError("size and min_values must be at least 1")
    col = table.column(column)
    out = []
    for n in range(len(col)):
        window = [v for v in col[max(0, n - size + 1):n + 1] if v is not None]
        out.append(sum(window) / len(window) if len(window) >= min_values else None)
    return _add(table, name or f"{column}_mean{size}", out)


def rank(table: Table, column: str, name: str | None = None, descending: bool = False,
         method: str = "min") -> Table:
    """Rank of each value (1 = smallest, or largest when `descending`). Ties get the lowest rank of the tie
    (`min`) or consecutive ranks without gaps (`dense`). None values get rank None."""
    if method not in ("min", "dense"):
        raise ValueError("method must be 'min' or 'dense'")
    col = table.column(column)
    present = sorted({v for v in col if v is not None}, reverse=descending)
    if method == "dense":
        ranks = {v: k for k, v in enumerate(present, 1)}
    else:
        ordered = sorted((v for v in col if v is not None), reverse=descending)
        ranks = {}
        for k, v in enumerate(ordered, 1):
            ranks.setdefault(v, k)
    return _add(table, name or f"{column}_rank", [None if v is None else ranks[v] for v in col])


def difference(table: Table, column: str, name: str | None = None, lag: int = 1) -> Table:
    """Value minus the value `lag` rows earlier; None for the first rows and wherever either value is None."""
    if lag < 1:
        raise ValueError("lag must be at least 1")
    col = table.column(column)
    out = [None if n < lag or col[n] is None or col[n - lag] is None else col[n] - col[n - lag]
           for n in range(len(col))]
    return _add(table, name or f"{column}_diff", out)


def share(table: Table, column: str, name: str | None = None, digits: int | None = None,
          by: str | Iterable[str] | None = None) -> Table:
    """Each value divided by the column total (None values count as 0 in the total and stay None). With `by`, the
    total is that of the rows sharing the same `by` values. With `digits`, the shares are rounded by
    `stats.apportion`, so the rounded shares of one total add up to exactly 1."""
    col = table.column(column)
    groups: dict[tuple, list[int]] = {}
    if by is None:
        groups[()] = list(range(len(col)))
    else:
        keys = [by] if isinstance(by, str) else list(by)
        if not keys:
            raise ValueError("by needs at least one column")
        idx = [table.index(k) for k in keys]
        for n, row in enumerate(table.rows):
            groups.setdefault(tuple(row[i] for i in idx), []).append(n)
    out: list = [None] * len(col)
    for positions in groups.values():
        values = [col[n] for n in positions]
        if digits is not None:
            parts = apportion(values, digits)
        else:
            total = sum(v for v in values if v is not None)
            parts = [None if v is None or total == 0 else v / total for v in values]
        for n, part in zip(positions, parts):
            out[n] = part
    return _add(table, name or f"{column}_share", out)
