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


FILL_METHODS = ("value", "forward", "backward", "interpolate")


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _gaps(col: list) -> list[tuple[int, int]]:
    """(start, end) of every maximal run of None values, end exclusive."""
    out, start = [], None
    for n, v in enumerate(col + [0]):  # a sentinel closes a trailing run
        if v is None and start is None:
            start = n
        elif v is not None and start is not None:
            out.append((start, n))
            start = None
    return out


def _fill_column(col: list, method: str, value, limit: int | None) -> list:
    out = list(col)
    for start, end in _gaps(col):
        size = end - start
        before = col[start - 1] if start > 0 else None
        after = col[end] if end < len(col) else None
        if method == "interpolate":
            if start == 0 or end == len(col) or (limit is not None and size > limit):
                continue  # an open-ended run, or one longer than the limit, stays missing as a whole
            if not (_is_number(before) and _is_number(after)):
                raise TypeError(f"cannot interpolate between {before!r} and {after!r}")
            for k, n in enumerate(range(start, end), 1):
                out[n] = before + (after - before) * k / (size + 1)
            continue
        positions = list(range(start, end))
        if method == "backward":
            if end == len(col):
                continue
            chosen = positions if limit is None else positions[max(0, size - limit):]
            fill = after
        elif method == "forward":
            if start == 0:
                continue
            chosen = positions if limit is None else positions[:limit]
            fill = before
        else:
            chosen = positions if limit is None else positions[:limit]
            fill = value
        for n in chosen:
            out[n] = fill
    return out


def fill_missing(table: Table, value=None, columns: Iterable[str] | None = None, method: str = "value",
                 limit: int | None = None) -> Table:
    """Replace None: with `value` (method "value"), with the previous non-missing value of the same column
    (method "forward"; a leading None stays None), with the next one ("backward"; a trailing None stays None), or
    by linear interpolation between the numbers on both sides of a run ("interpolate"; open-ended runs stay None).
    `limit` caps how many values of each run of None are filled: the first ones for "value" and "forward", the last
    ones for "backward"; "interpolate" leaves a longer run untouched."""
    if method not in FILL_METHODS:
        raise ValueError(f"method must be one of {', '.join(FILL_METHODS)}")
    if limit is not None and (not isinstance(limit, int) or isinstance(limit, bool) or limit < 1):
        raise ValueError("limit must be a whole number of at least 1")
    idx = _columns(table, columns)
    cols = {i: _fill_column([row[i] for row in table.rows], method, value, limit) for i in set(idx)}
    rows = [tuple(cols[i][n] if i in cols else v for i, v in enumerate(row)) for n, row in enumerate(table.rows)]
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
