"""Joining two tables on key columns."""
from __future__ import annotations

from typing import Iterable

from .table import Table

HOWS = ("inner", "left", "right", "outer")


def _key_list(on) -> list[str]:
    keys = [on] if isinstance(on, str) else list(on)
    if not keys:
        raise ValueError("join needs at least one key column")
    return keys


def _output_columns(left: Table, right: Table, keys: list[str], suffixes: tuple[str, str]) -> tuple[list[str],
                                                                                                    list[str]]:
    """Names of the left and right non-key columns in the result; a name present on both sides gets the suffixes."""
    left_rest = [c for c in left.columns if c not in keys]
    right_rest = [c for c in right.columns if c not in keys]
    both = set(left_rest) & set(right_rest)
    if both and suffixes[0] == suffixes[1]:
        raise ValueError("suffixes must differ when non-key columns share names")
    left_names = [c + suffixes[0] if c in both else c for c in left_rest]
    right_names = [c + suffixes[1] if c in both else c for c in right_rest]
    clash = set(keys) & (set(left_names) | set(right_names))
    if clash or len(set(left_names) | set(right_names)) != len(left_names) + len(right_names):
        raise ValueError("joined column names collide")
    return left_names, right_names


def join(left: Table, right: Table, on: str | Iterable[str], how: str = "inner",
         suffixes: tuple[str, str] = ("_left", "_right")) -> Table:
    """Rows of `left` and `right` whose key columns are equal. Key columns appear once, first; then the other left
    columns, then the other right columns. Rows with a None in any key never match (but `left`/`right`/`outer` keep
    them unmatched). Order: left rows in their order, each followed by its right matches in right order; for
    `right` and `outer`, unmatched right rows come last in right order."""
    if how not in HOWS:
        raise ValueError(f"how must be one of {', '.join(HOWS)}")
    keys = _key_list(on)
    lk = [left.index(k) for k in keys]
    rk = [right.index(k) for k in keys]
    l_rest = [i for i, c in enumerate(left.columns) if c not in keys]
    r_rest = [i for i, c in enumerate(right.columns) if c not in keys]
    left_names, right_names = _output_columns(left, right, keys, suffixes)
    index: dict[tuple, list[int]] = {}
    for n, row in enumerate(right.rows):
        key = tuple(row[i] for i in rk)
        if None not in key:
            index.setdefault(key, []).append(n)
    used: set[int] = set()
    rows = []
    for row in left.rows:
        key = tuple(row[i] for i in lk)
        matches = index.get(key, []) if None not in key else []
        for n in matches:
            used.add(n)
            other = right.rows[n]
            rows.append(key + tuple(row[i] for i in l_rest) + tuple(other[i] for i in r_rest))
        if not matches and how in ("left", "outer"):
            rows.append(key + tuple(row[i] for i in l_rest) + (None,) * len(r_rest))
    if how in ("right", "outer"):
        for n, other in enumerate(right.rows):
            if n not in used:
                key = tuple(other[i] for i in rk)
                rows.append(key + (None,) * len(l_rest) + tuple(other[i] for i in r_rest))
    return Table(keys + left_names + right_names, rows)


def semi_join(left: Table, right: Table, on: str | Iterable[str]) -> Table:
    """The rows of `left` that have at least one match in `right` (left columns only, left order)."""
    keys = _key_list(on)
    present = {tuple(r[right.index(k)] for k in keys) for r in right.rows}
    lk = [left.index(k) for k in keys]
    return Table(left.columns, [row for row in left.rows
                                if None not in tuple(row[i] for i in lk) and tuple(row[i] for i in lk) in present])


def anti_join(left: Table, right: Table, on: str | Iterable[str]) -> Table:
    """The rows of `left` without any match in `right` (a None key never matches, so such rows are kept)."""
    keys = _key_list(on)
    present = {tuple(r[right.index(k)] for k in keys) for r in right.rows}
    lk = [left.index(k) for k in keys]
    return Table(left.columns, [row for row in left.rows
                                if None in tuple(row[i] for i in lk) or tuple(row[i] for i in lk) not in present])
