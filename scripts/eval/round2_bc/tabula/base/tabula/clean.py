"""Tidying text values and rows before analysis."""
from __future__ import annotations

import re
from typing import Callable, Iterable

from .table import Table

_SPACES = re.compile(r"\s+")


def _columns(table: Table, columns: Iterable[str] | None) -> list[int]:
    names = table.columns if columns is None else list(columns)
    return [table.index(c) for c in names]


def map_values(table: Table, func: Callable, columns: Iterable[str] | None = None, skip_none: bool = True) -> Table:
    """`func` applied to every value of the given columns (default: all); None values are left alone unless
    `skip_none` is False."""
    idx = set(_columns(table, columns))
    rows = [tuple((v if (skip_none and v is None) or i not in idx else func(v)) for i, v in enumerate(row))
            for row in table.rows]
    return Table(table.columns, rows)


def strip(table: Table, columns: Iterable[str] | None = None, collapse: bool = False) -> Table:
    """Text values without leading/trailing whitespace; with `collapse`, inner runs of whitespace become one space.
    Values that are not text are unchanged."""
    def fix(v):
        if not isinstance(v, str):
            return v
        v = v.strip()
        return _SPACES.sub(" ", v) if collapse else v
    return map_values(table, fix, columns)


def blank_to_none(table: Table, columns: Iterable[str] | None = None) -> Table:
    """Text values that are empty or only whitespace become None."""
    return map_values(table, lambda v: None if isinstance(v, str) and not v.strip() else v, columns)


def fill_missing(table: Table, value=None, columns: Iterable[str] | None = None, method: str = "value") -> Table:
    """Replace None: with `value` (method "value"), or with the previous non-missing value of the same column
    (method "forward"; a leading None stays None)."""
    if method not in ("value", "forward"):
        raise ValueError("method must be 'value' or 'forward'")
    idx = set(_columns(table, columns))
    last: dict[int, object] = {}
    rows = []
    for row in table.rows:
        out = []
        for i, v in enumerate(row):
            if i in idx and v is None:
                v = value if method == "value" else last.get(i)
            if v is not None:
                last[i] = v
            out.append(v)
        rows.append(tuple(out))
    return Table(table.columns, rows)


def dedupe(table: Table, columns: Iterable[str] | None = None, keep: str = "first") -> Table:
    """Rows with a repeated combination of `columns` (default: all) removed, keeping the first or last one; the
    kept rows stay in their original order."""
    if keep not in ("first", "last"):
        raise ValueError("keep must be 'first' or 'last'")
    idx = _columns(table, columns)
    keys = [tuple(row[i] for i in idx) for row in table.rows]
    if keep == "first":
        seen, chosen = set(), []
        for n, k in enumerate(keys):
            if k not in seen:
                seen.add(k)
                chosen.append(n)
    else:
        last = {k: n for n, k in enumerate(keys)}
        chosen = sorted(last.values())
    return Table(table.columns, [table.rows[n] for n in chosen])


def normalize_case(table: Table, columns: Iterable[str], case: str = "lower") -> Table:
    """Text values of the given columns in lower, upper or title case."""
    funcs = {"lower": str.lower, "upper": str.upper, "title": str.title}
    if case not in funcs:
        raise ValueError("case must be lower, upper or title")
    return map_values(table, lambda v: funcs[case](v) if isinstance(v, str) else v, columns)


def drop_empty_rows(table: Table) -> Table:
    """Rows in which every value is None or blank text removed."""
    def empty(v):
        return v is None or (isinstance(v, str) and not v.strip())
    return Table(table.columns, [row for row in table.rows if not all(empty(v) for v in row)])
