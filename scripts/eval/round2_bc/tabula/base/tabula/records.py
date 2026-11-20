"""Tables from and to lists of records (dicts) and JSON Lines text."""
from __future__ import annotations

import json
from typing import Iterable

from .errors import ParseError
from .table import Table


def from_records(records: Iterable[dict], columns: Iterable[str] | None = None, missing=None) -> Table:
    """A table from dicts. Columns default to the union of keys in first-seen order; a key a record lacks gets
    `missing`. Keys outside an explicit `columns` list are dropped."""
    records = list(records)
    if columns is None:
        order: list[str] = []
        for record in records:
            for k in record:
                if k not in order:
                    order.append(k)
        columns = order
    columns = list(columns)
    return Table(columns, [tuple(r.get(c, missing) for c in columns) for r in records])


def to_records(table: Table, drop_none: bool = False) -> list[dict]:
    """One dict per row; with `drop_none`, keys whose value is None are left out."""
    out = []
    for row in table.rows:
        record = dict(zip(table.columns, row))
        if drop_none:
            record = {k: v for k, v in record.items() if v is not None}
        out.append(record)
    return out


def to_jsonl(table: Table, drop_none: bool = False) -> str:
    """JSON Lines: one compact JSON object per row, keys in column order, each line ending in a newline."""
    return "".join(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n"
                   for r in to_records(table, drop_none))


def from_jsonl(text: str, columns: Iterable[str] | None = None) -> Table:
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
    return from_records(records, columns)


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
