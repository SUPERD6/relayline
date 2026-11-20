"""Grouping rows and computing aggregates per group; pivot tables."""
from __future__ import annotations

import math
from typing import Any, Callable, Iterable

from .stats import apportion
from .table import Table

NORMALIZE = (None, "rows", "all")
_EMPTY = object()  # a pivot cell without any matching row


def _present(values: Iterable) -> list:
    return [v for v in values if v is not None]


def agg_count(values: list) -> int:
    """Number of values that are not None."""
    return len(_present(values))


def agg_rows(values: list) -> int:
    """Number of rows, missing values included."""
    return len(values)


def agg_sum(values: list):
    present = _present(values)
    return sum(present) if present else None


def agg_mean(values: list):
    present = _present(values)
    return sum(present) / len(present) if present else None


def agg_min(values: list):
    present = _present(values)
    return min(present) if present else None


def agg_max(values: list):
    present = _present(values)
    return max(present) if present else None


def agg_median(values: list):
    present = sorted(_present(values))
    if not present:
        return None
    mid = len(present) // 2
    if len(present) % 2:
        return present[mid]
    return (present[mid - 1] + present[mid]) / 2


def agg_first(values: list):
    present = _present(values)
    return present[0] if present else None


def agg_last(values: list):
    present = _present(values)
    return present[-1] if present else None


def agg_distinct(values: list) -> int:
    return len(set(_present(values)))


def agg_std(values: list):
    """Sample standard deviation; None with fewer than two values."""
    present = _present(values)
    if len(present) < 2:
        return None
    mean = sum(present) / len(present)
    return math.sqrt(sum((v - mean) ** 2 for v in present) / (len(present) - 1))


AGGREGATES: dict[str, Callable[[list], Any]] = {
    "count": agg_count, "rows": agg_rows, "sum": agg_sum, "mean": agg_mean, "min": agg_min, "max": agg_max,
    "median": agg_median, "first": agg_first, "last": agg_last, "distinct": agg_distinct, "std": agg_std,
}


def _resolve(spec) -> tuple[str, Callable[[list], Any]]:
    """(column, function) from ('column', 'name') or ('column', callable)."""
    if not (isinstance(spec, tuple) and len(spec) == 2):
        raise TypeError("an aggregate is a (column, function) pair")
    column, func = spec
    if isinstance(func, str):
        if func not in AGGREGATES:
            raise ValueError(f"unknown aggregate {func!r}")
        func = AGGREGATES[func]
    return column, func


def group_by(table: Table, keys: str | Iterable[str], **aggregates) -> Table:
    """One row per distinct combination of `keys`, in order of first appearance, with one column per keyword:
    `total=("qty", "sum")`. Groups whose key is None are kept as their own group."""
    keys = [keys] if isinstance(keys, str) else list(keys)
    if not keys:
        raise ValueError("group_by needs at least one key column")
    key_idx = [table.index(k) for k in keys]
    specs = {name: _resolve(spec) for name, spec in aggregates.items()}
    clash = set(specs) & set(keys)
    if clash:
        raise ValueError(f"aggregate name(s) also used as keys: {', '.join(sorted(clash))}")
    value_idx = {name: table.index(col) for name, (col, _) in specs.items()}
    groups: dict[tuple, list[tuple]] = {}
    for row in table.rows:
        groups.setdefault(tuple(row[i] for i in key_idx), []).append(row)
    rows = []
    for key, members in groups.items():
        values = [specs[name][1]([m[value_idx[name]] for m in members]) for name in specs]
        rows.append(key + tuple(values))
    return Table(keys + list(specs), rows)


def _shares(cells: list, digits: int | None) -> list:
    """Shares of the counted cells (None and empty cells count as 0 and are left as they are)."""
    counted = [None if v is _EMPTY else v for v in cells]
    if digits is not None:
        parts = apportion(counted, digits)
    else:
        total = sum(v for v in counted if v is not None)
        parts = [None if v is None or total == 0 else v / total for v in counted]
    return [v if v is _EMPTY else p for v, p in zip(cells, parts)]


def pivot(table: Table, index: str, columns: str, values: str, func: str | Callable = "sum",
          fill=None, normalize: str | None = None, digits: int | None = None) -> Table:
    """A wide table: one row per distinct `index` value (first-appearance order), one column per distinct
    `columns` value (sorted by its text), each cell the aggregate of `values` over the matching rows (`fill` when
    there are none). `normalize` turns the cells into shares of their row's total ("rows") or of the whole
    table's total ("all"); with `digits` they are rounded by `stats.apportion`, so each total's rounded shares add
    up to exactly 1. Cells without rows keep `fill`."""
    if normalize not in NORMALIZE:
        raise ValueError("normalize must be None, 'rows' or 'all'")
    if digits is not None and normalize is None:
        raise ValueError("digits needs normalize")
    _, agg = _resolve((values, func))
    ii, ci, vi = table.index(index), table.index(columns), table.index(values)
    order: list = []
    cells: dict[tuple, list] = {}
    heads = set()
    for row in table.rows:
        if row[ii] not in order:
            order.append(row[ii])
        heads.add(row[ci])
        cells.setdefault((row[ii], row[ci]), []).append(row[vi])
    head_list = sorted(heads, key=lambda h: (h is None, str(h)))
    names = [index] + [("" if h is None else str(h)) for h in head_list]
    if len(set(names)) != len(names):
        raise ValueError("pivot columns collide with the index name or with each other")
    grid = [[agg(cells[(key, h)]) if (key, h) in cells else _EMPTY for h in head_list] for key in order]
    if normalize == "rows":
        grid = [_shares(line, digits) for line in grid]
    elif normalize == "all":
        flat = _shares([v for line in grid for v in line], digits)
        grid = [flat[k * len(head_list):(k + 1) * len(head_list)] for k in range(len(grid))]
    rows = [tuple([key] + [fill if v is _EMPTY else v for v in line]) for key, line in zip(order, grid)]
    return Table(names, rows)


def running_total(table: Table, column: str, name: str | None = None) -> Table:
    """The table with one more column holding the cumulative sum of `column` (None values add nothing)."""
    i = table.index(column)
    name = name or f"{column}_total"
    if name in table.columns:
        raise ValueError(f"column {name!r} already exists")
    total, rows = 0, []
    for row in table.rows:
        total += row[i] or 0
        rows.append(row + (total,))
    return Table(table.columns + [name], rows)
