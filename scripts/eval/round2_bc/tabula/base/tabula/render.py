"""Rendering a table as aligned plain text or as a Markdown table."""
from __future__ import annotations

from .table import Table


def _cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def render_text(table: Table) -> str:
    """Columns left-aligned and padded to their widest cell, a dashed rule under the header."""
    cells = [[_cell(v) for v in row] for row in table.rows]
    widths = [max([len(c)] + [len(r[i]) for r in cells]) for i, c in enumerate(table.columns)]
    lines = ["  ".join(c.ljust(w) for c, w in zip(table.columns, widths)).rstrip(),
             "  ".join("-" * w for w in widths)]
    lines += ["  ".join(c.ljust(w) for c, w in zip(row, widths)).rstrip() for row in cells]
    return "\n".join(lines) + "\n"


def render_markdown(table: Table) -> str:
    def esc(text: str) -> str:
        return text.replace("|", "\\|")
    lines = ["| " + " | ".join(esc(c) for c in table.columns) + " |",
             "|" + "|".join(" --- " for _ in table.columns) + "|"]
    lines += ["| " + " | ".join(esc(_cell(v)) for v in row) + " |" for row in table.rows]
    return "\n".join(lines) + "\n"
