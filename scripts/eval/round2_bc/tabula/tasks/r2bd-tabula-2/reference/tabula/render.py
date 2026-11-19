"""Rendering a table as aligned plain text or as a Markdown table."""
from __future__ import annotations

from .table import Table


def _cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def numeric_columns(table: Table) -> list[bool]:
    """For each column: True when it has at least one value and every value that is not None is an int or a float
    (bool does not count as a number)."""
    out = []
    for i in range(len(table.columns)):
        values = [row[i] for row in table.rows if row[i] is not None]
        out.append(bool(values) and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values))
    return out


def render_text(table: Table) -> str:
    """Columns padded to their widest cell, a dashed rule under the header. Numeric columns (header included) are
    right-aligned, every other column left-aligned; trailing spaces are dropped."""
    cells = [[_cell(v) for v in row] for row in table.rows]
    widths = [max([len(c)] + [len(r[i]) for r in cells]) for i, c in enumerate(table.columns)]
    right = numeric_columns(table)

    def line(values):
        return "  ".join(v.rjust(w) if r else v.ljust(w) for v, w, r in zip(values, widths, right)).rstrip()
    lines = [line(table.columns), "  ".join("-" * w for w in widths)]
    lines += [line(row) for row in cells]
    return "\n".join(lines) + "\n"


def render_markdown(table: Table) -> str:
    """A Markdown table; numeric columns get a right-aligned separator."""
    def esc(text: str) -> str:
        return text.replace("|", "\\|")
    right = numeric_columns(table)
    lines = ["| " + " | ".join(esc(c) for c in table.columns) + " |",
             "|" + "|".join(" ---: " if r else " --- " for r in right) + "|"]
    lines += ["| " + " | ".join(esc(_cell(v)) for v in row) + " |" for row in table.rows]
    return "\n".join(lines) + "\n"
