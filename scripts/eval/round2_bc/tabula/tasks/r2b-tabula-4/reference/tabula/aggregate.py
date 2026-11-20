"""Grouping rows and computing aggregates per group; pivot tables; top rows per group."""
from __future__ import annotations

import math
import re
from typing import Any, Callable, Iterable

from .table import Table

_PERCENTILE = re.compile(r"p(0|[1-9][0-9]?|100)")


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


def agg_common(values: list):
    """The most frequent value that is not None; a tie goes to the tied value seen first (not the smallest)."""
    counts: dict = {}
    for v in _present(values):
        counts[v] = counts.get(v, 0) + 1
    if not counts:
        return None
    best = max(counts.values())
    return next(v for v, c in counts.items() if c == best)


def _percentile(n: int) -> Callable[[list], Any]:
    """Nearest rank, not interpolation: the value at 1-based position ceil(n/100 * count) of the sorted present
    values (at least position 1), so the result is always one of the group's own values."""
    def agg(values: list):
        present = sorted(_present(values))
        if not present:
            return None
        rank = max(1, -(-n * len(present) // 100))
        return present[rank - 1]
    return agg


AGGREGATES: dict[str, Callable[[list], Any]] = {
    "count": agg_count, "rows": agg_rows, "sum": agg_sum, "mean": agg_mean, "min": agg_min, "max": agg_max,
    "median": agg_median, "first": agg_first, "last": agg_last, "distinct": agg_distinct, "std": agg_std,
    "common": agg_common,
}


def _resolve(spec) -> tuple[str, Callable[[list], Any]]:
    """(column, function) from ('column', 'name') or ('column', callable). Besides the names in AGGREGATES, `pN`
    (N a whole number from 0 to 100 without leading zeros) is the N-th nearest-rank percentile (unlike
    `stats.quantile`, which interpolates)."""
    if not (isinstance(spec, tuple) and len(spec) == 2):
        raise TypeError("an aggregate is a (column, function) pair")
    column, func = spec
    if isinstance(func, str):
        m = _PERCENTILE.fullmatch(func)
        if m:
            func = _percentile(int(m.group(1)))
        elif func not in AGGREGATES:
            raise ValueError(f"unknown aggregate {func!r}")
        else:
            func = AGGREGATES[func]
    return column, func


def group_by(table: Table, keys: str | Iterable[str], dropna: bool = False, **aggregates) -> Table:
    """One row per distinct combination of `keys`, in order of first appearance, with one column per keyword:
    `total=("qty", "sum")`. Groups whose key is None are kept as their own group, unless `dropna` is true: then
    rows with None in any key column are left out."""
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
        key = tuple(row[i] for i in key_idx)
        if dropna and None in key:
            continue
        groups.setdefault(key, []).append(row)
    rows = []
    for key, members in groups.items():
        values = [specs[name][1]([m[value_idx[name]] for m in members]) for name in specs]
        rows.append(key + tuple(values))
    return Table(keys + list(specs), rows)


def pivot(table: Table, index: str, columns: str, values: str, func: str | Callable = "sum",
          fill=None) -> Table:
    """A wide table: one row per distinct `index` value (first-appearance order), one column per distinct
    `columns` value (sorted by its text), each cell the aggregate of `values` over the matching rows (`fill` when
    there are none)."""
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
    rows = [tuple([key] + [agg(cells[(key, h)]) if (key, h) in cells else fill for h in head_list])
            for key in order]
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


def top_n(table: Table, keys: str | Iterable[str], column: str, n: int, largest: bool = True) -> Table:
    """Per group of `keys` (first-appearance order, None keys a group of their own), the rows with the `n` largest
    (or smallest) values of `column`, best first; equal values keep their original order. Rows whose value is None
    are never chosen, so a group may give fewer than `n` rows, or none at all."""
    if n < 1:
        raise ValueError("n must be at least 1")
    keys = [keys] if isinstance(keys, str) else list(keys)
    if not keys:
        raise ValueError("top_n needs at least one key column")
    key_idx, vi = [table.index(k) for k in keys], table.index(column)
    groups: dict[tuple, list[tuple]] = {}
    for row in table.rows:
        members = groups.setdefault(tuple(row[i] for i in key_idx), [])
        if row[vi] is not None:
            members.append(row)
    rows = []
    for members in groups.values():
        # sorted() stays stable with reverse=True, so equal values keep their original order either way
        rows += sorted(members, key=lambda row: row[vi], reverse=largest)[:n]
    return Table(table.columns, rows)
