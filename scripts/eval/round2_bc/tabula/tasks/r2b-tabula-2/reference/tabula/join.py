"""Joining two tables on key columns."""
from __future__ import annotations

from typing import Iterable

from .errors import JoinError
from .table import Table

HOWS = ("inner", "left", "right", "outer")
VALIDATE = {"1:1": ("left", "right"), "1:m": ("left",), "m:1": ("right",)}


def _key_list(on) -> list[str]:
    keys = [on] if isinstance(on, str) else list(on)
    if not keys:
        raise ValueError("join needs at least one key column")
    return keys


def _key_pairs(on) -> tuple[list[str], list[str]]:
    """Left and right key names: a name or list of names shared by both tables, or a {left: right} mapping."""
    if isinstance(on, dict):
        if not on:
            raise ValueError("join needs at least one key column")
        return list(on), list(on.values())
    keys = _key_list(on)
    return keys, list(keys)


def _output_columns(left: Table, right: Table, keys: list[str], suffixes: tuple[str, str],
                    right_keys: list[str] | None = None) -> tuple[list[str], list[str]]:
    """Names of the left and right non-key columns in the result; a name present on both sides gets the suffixes."""
    right_keys = keys if right_keys is None else right_keys
    left_rest = [c for c in left.columns if c not in keys]
    right_rest = [c for c in right.columns if c not in right_keys]
    both = set(left_rest) & set(right_rest)
    if both and suffixes[0] == suffixes[1]:
        raise ValueError("suffixes must differ when non-key columns share names")
    left_names = [c + suffixes[0] if c in both else c for c in left_rest]
    right_names = [c + suffixes[1] if c in both else c for c in right_rest]
    clash = set(keys) & (set(left_names) | set(right_names))
    if clash or len(set(left_names) | set(right_names)) != len(left_names) + len(right_names):
        raise ValueError("joined column names collide")
    return left_names, right_names


def _check_unique(table: Table, idx: list[int], side: str) -> None:
    """JoinError for the first key that repeats in `table` (row order); keys holding None never match, so they
    are not checked."""
    seen: set[tuple] = set()
    for row in table.rows:
        key = tuple(row[i] for i in idx)
        if None in key:
            continue
        if key in seen:
            raise JoinError(side, key)
        seen.add(key)


def join(left: Table, right: Table, on: str | Iterable[str] | dict, how: str = "inner",
         suffixes: tuple[str, str] = ("_left", "_right"), validate: str | None = None,
         indicator: str | None = None) -> Table:
    """Rows of `left` and `right` whose key columns are equal. Key columns appear once, first (with the left
    names when `on` maps left names to right names); then the other left columns, then the other right columns.
    Rows with a None in any key never match (but `left`/`right`/`outer` keep them unmatched). Order: left rows in
    their order, each followed by its right matches in right order; for `right` and `outer`, unmatched right rows
    come last in right order.

    `validate` ("1:1", "1:m", "m:1") requires the keys of the "1" side(s) to be unique, left checked first, and
    raises JoinError otherwise. `indicator` names an extra last column telling where each row came from: "both",
    "left" or "right"."""
    if how not in HOWS:
        raise ValueError(f"how must be one of {', '.join(HOWS)}")
    if validate is not None and validate not in VALIDATE:
        raise ValueError(f"validate must be one of {', '.join(VALIDATE)}")
    keys, right_keys = _key_pairs(on)
    lk = [left.index(k) for k in keys]
    rk = [right.index(k) for k in right_keys]
    l_rest = [i for i, c in enumerate(left.columns) if c not in keys]
    r_rest = [i for i, c in enumerate(right.columns) if c not in right_keys]
    left_names, right_names = _output_columns(left, right, keys, suffixes, right_keys)
    names = keys + left_names + right_names
    if indicator is not None and indicator in names:
        raise ValueError(f"indicator column {indicator!r} collides with a joined column")
    for side in VALIDATE.get(validate, ()):
        table, idx = (left, lk) if side == "left" else (right, rk)
        _check_unique(table, idx, side)
    tag = (lambda where: (where,)) if indicator is not None else (lambda where: ())
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
            rows.append(key + tuple(row[i] for i in l_rest) + tuple(other[i] for i in r_rest) + tag("both"))
        if not matches and how in ("left", "outer"):
            rows.append(key + tuple(row[i] for i in l_rest) + (None,) * len(r_rest) + tag("left"))
    if how in ("right", "outer"):
        for n, other in enumerate(right.rows):
            if n not in used:
                key = tuple(other[i] for i in rk)
                rows.append(key + (None,) * len(l_rest) + tuple(other[i] for i in r_rest) + tag("right"))
    return Table(names + ([indicator] if indicator is not None else []), rows)


def semi_join(left: Table, right: Table, on: str | Iterable[str] | dict) -> Table:
    """The rows of `left` that have at least one match in `right` (left columns only, left order)."""
    keys, right_keys = _key_pairs(on)
    present = {tuple(r[right.index(k)] for k in right_keys) for r in right.rows}
    lk = [left.index(k) for k in keys]
    return Table(left.columns, [row for row in left.rows
                                if None not in tuple(row[i] for i in lk) and tuple(row[i] for i in lk) in present])


def anti_join(left: Table, right: Table, on: str | Iterable[str] | dict) -> Table:
    """The rows of `left` without any match in `right` (a None key never matches, so such rows are kept)."""
    keys, right_keys = _key_pairs(on)
    present = {tuple(r[right.index(k)] for k in right_keys) for r in right.rows}
    lk = [left.index(k) for k in keys]
    return Table(left.columns, [row for row in left.rows
                                if None in tuple(row[i] for i in lk) or tuple(row[i] for i in lk) not in present])
