"""Tables from and to lists of records (dicts) and JSON Lines text; nested records flattened to dotted columns."""
from __future__ import annotations

import json
from typing import Iterable

from .errors import ParseError
from .table import Table


def _check_sep(sep) -> None:
    if not isinstance(sep, str) or not sep:
        raise ValueError("sep must be a non-empty string")


def _flatten(record: dict, sep: str, prefix: str = "", out: dict | None = None) -> dict:
    """Nested non-empty dicts become `outer<sep>inner` keys, depth first in key order; other values (lists, empty
    dicts) are kept as they are. Two paths giving the same name raise ValueError."""
    out = {} if out is None else out
    for key, value in record.items():
        name = prefix + str(key)
        if isinstance(value, dict) and value:
            _flatten(value, sep, name + sep, out)
            continue
        if name in out:
            raise ValueError(f"flattened name {name!r} appears twice")
        out[name] = value
    return out


def _check_nestable(columns: list[str], sep: str) -> None:
    """A column cannot be both a value and the parent of another column (`a` and `a.b`)."""
    names = set(columns)
    for c in columns:
        parts = c.split(sep)
        for n in range(1, len(parts)):
            if sep.join(parts[:n]) in names:
                raise ValueError(f"column {sep.join(parts[:n])!r} would hold both a value and {c!r}")


def _nest(record: dict, sep: str) -> dict:
    out: dict = {}
    for name, value in record.items():
        *parents, leaf = name.split(sep)
        node = out
        for p in parents:
            node = node.setdefault(p, {})
        node[leaf] = value
    return out


def from_records(records: Iterable[dict], columns: Iterable[str] | None = None, missing=None,
                 flatten: bool = False, sep: str = ".") -> Table:
    """A table from dicts. Columns default to the union of keys in first-seen order; a key a record lacks gets
    `missing`. Keys outside an explicit `columns` list are dropped. With `flatten`, nested dicts become columns
    named by their path joined with `sep`."""
    _check_sep(sep)
    records = [_flatten(r, sep) for r in records] if flatten else list(records)
    if columns is None:
        order: list[str] = []
        for record in records:
            for k in record:
                if k not in order:
                    order.append(k)
        columns = order
    columns = list(columns)
    return Table(columns, [tuple(r.get(c, missing) for c in columns) for r in records])


def to_records(table: Table, drop_none: bool = False, nest: bool = False, sep: str = ".") -> list[dict]:
    """One dict per row; with `drop_none`, keys whose value is None are left out. With `nest`, a column name
    holding `sep` becomes nested dicts (the inverse of flattening); a nested dict is only made for values that are
    kept, so with `drop_none` it never ends up empty."""
    _check_sep(sep)
    if nest:
        _check_nestable(table.columns, sep)
    out = []
    for row in table.rows:
        record = dict(zip(table.columns, row))
        if drop_none:
            record = {k: v for k, v in record.items() if v is not None}
        out.append(_nest(record, sep) if nest else record)
    return out


def to_jsonl(table: Table, drop_none: bool = False, nest: bool = False, sep: str = ".") -> str:
    """JSON Lines: one compact JSON object per row, keys in column order, each line ending in a newline."""
    return "".join(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n"
                   for r in to_records(table, drop_none, nest, sep))


def from_jsonl(text: str, columns: Iterable[str] | None = None, flatten: bool = False, sep: str = ".") -> Table:
    """The inverse of `to_jsonl`. Blank lines are skipped; a line that is not a JSON object raises ParseError with
    its line number."""
    records = []
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ParseError(number, f"invalid JSON ({exc.msg})") from None
        if not isinstance(value, dict):
            raise ParseError(number, "expected a JSON object")
        records.append(value)
    return from_records(records, columns, flatten=flatten, sep=sep)


def rename(table: Table, mapping: dict[str, str]) -> Table:
    """The table with some columns renamed; unknown names raise KeyError, duplicate results ValueError."""
    for old in mapping:
        table.index(old)
    columns = [mapping.get(c, c) for c in table.columns]
    if len(set(columns)) != len(columns):
        raise ValueError("renaming would create duplicate column names")
    return Table(columns, table.rows)


def concat(tables: Iterable[Table], fill=None) -> Table:
    """Rows of several tables one after another; columns are the union in first-seen order, `fill` where a table
    lacks one."""
    tables = list(tables)
    columns: list[str] = []
    for t in tables:
        columns += [c for c in t.columns if c not in columns]
    rows = []
    for t in tables:
        pos = {c: i for i, c in enumerate(t.columns)}
        rows += [tuple(row[pos[c]] if c in pos else fill for c in columns) for row in t.rows]
    return Table(columns, rows)
