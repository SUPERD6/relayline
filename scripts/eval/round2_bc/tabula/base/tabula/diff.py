"""Comparing two versions of a table row by row, matched on key columns."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from .table import Table


@dataclass
class TableDiff:
    key: list[str]
    added: list[dict] = field(default_factory=list)        # rows only in the new table
    removed: list[dict] = field(default_factory=list)      # rows only in the old table
    changed: list[dict] = field(default_factory=list)      # {"key": {...}, "changes": {column: (old, new)}}
    added_columns: list[str] = field(default_factory=list)
    removed_columns: list[str] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not (self.added or self.removed or self.changed or self.added_columns or self.removed_columns)

    def counts(self) -> dict[str, int]:
        return {"added": len(self.added), "removed": len(self.removed), "changed": len(self.changed)}


def _keyed(table: Table, key: list[str]) -> dict[tuple, dict]:
    idx = [table.index(k) for k in key]
    out: dict[tuple, dict] = {}
    for row in table.rows:
        k = tuple(row[i] for i in idx)
        if k in out:
            raise ValueError(f"key {k!r} is not unique")
        out[k] = dict(zip(table.columns, row))
    return out


def diff(old: Table, new: Table, key: str | Iterable[str]) -> TableDiff:
    """Rows are matched on `key` (which must be unique in each table). Only columns present in both tables are
    compared; columns present in one table only are listed as added/removed columns. Added rows follow the new
    table's order; removed and changed rows follow the old table's order."""
    key = [key] if isinstance(key, str) else list(key)
    if not key:
        raise ValueError("diff needs at least one key column")
    a, b = _keyed(old, key), _keyed(new, key)
    shared = [c for c in old.columns if c in new.columns and c not in key]
    result = TableDiff(key, added_columns=[c for c in new.columns if c not in old.columns],
                       removed_columns=[c for c in old.columns if c not in new.columns])
    for k, row in b.items():
        if k not in a:
            result.added.append(row)
    for k, row in a.items():
        if k not in b:
            result.removed.append(row)
            continue
        changes = {c: (row[c], b[k][c]) for c in shared if row[c] != b[k][c]}
        if changes:
            result.changed.append({"key": dict(zip(key, k)), "changes": changes})
    return result


def _key_text(key: dict) -> str:
    return ", ".join(f"{k}={v!r}" for k, v in key.items())


def render_diff(d: TableDiff) -> str:
    """A line per change: `+ ` added rows, `- ` removed rows, `~ ` changed rows with `column: old -> new`."""
    lines = []
    for c in d.added_columns:
        lines.append(f"+ column {c}")
    for c in d.removed_columns:
        lines.append(f"- column {c}")
    for row in d.added:
        lines.append("+ " + _key_text({k: row[k] for k in d.key}))
    for row in d.removed:
        lines.append("- " + _key_text({k: row[k] for k in d.key}))
    for change in d.changed:
        parts = "; ".join(f"{c}: {o!r} -> {n!r}" for c, (o, n) in change["changes"].items())
        lines.append(f"~ {_key_text(change['key'])}: {parts}")
    return "\n".join(lines) + ("\n" if lines else "")


def apply_diff(old: Table, d: TableDiff) -> Table:
    """`old` with the diff applied: changed cells updated, removed rows dropped, added rows appended (columns of
    `old` only; a value an added row lacks becomes None)."""
    removed = {tuple(r[k] for k in d.key) for r in d.removed}
    updates = {tuple(c["key"][k] for k in d.key): c["changes"] for c in d.changed}
    idx = [old.index(k) for k in d.key]
    rows = []
    for row in old.rows:
        k = tuple(row[i] for i in idx)
        if k in removed:
            continue
        if k in updates:
            row = tuple(updates[k][c][1] if c in updates[k] else v for c, v in zip(old.columns, row))
        rows.append(row)
    rows += [tuple(r.get(c) for c in old.columns) for r in d.added]
    return Table(old.columns, rows)
