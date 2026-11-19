"""Writing rows and tables back to delimited text, the inverse of `reader`."""
from __future__ import annotations

from typing import Iterable

from .table import Table

QUOTING = ("minimal", "all", "nonnumeric", "none")


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _text(value, true: str, false: str) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return true if value else false
    if isinstance(value, float) and value.is_integer():
        return repr(value)
    return str(value)


def format_field(value, delimiter: str = ",", quote: str = '"', quoting: str = "minimal",
                 true: str = "true", false: str = "false") -> str:
    """One field as text. `minimal` quotes only when needed (delimiter, quote, line break, or leading/trailing
    space), `all` quotes every field, `nonnumeric` quotes everything except numbers and empty values, `none` never
    quotes and refuses values that would need it."""
    if quoting not in QUOTING:
        raise ValueError(f"quoting must be one of {', '.join(QUOTING)}")
    text = _text(value, true, false)
    needs = (delimiter in text or quote in text or "\n" in text or "\r" in text
             or (text != text.strip()))
    if quoting == "none":
        if needs:
            raise ValueError(f"field {text!r} needs quoting")
        return text
    if quoting == "all" or needs or (quoting == "nonnumeric" and value is not None and not _is_number(value)):
        return quote + text.replace(quote, quote * 2) + quote
    return text


def write_rows(rows: Iterable[Iterable], delimiter: str = ",", quote: str = '"', quoting: str = "minimal",
               line_end: str = "\n", true: str = "true", false: str = "false") -> str:
    """Rows of values as delimited text; every row ends with `line_end`."""
    if len(delimiter) != 1 or len(quote) != 1 or delimiter == quote:
        raise ValueError("delimiter and quote must be two different single characters")
    if line_end not in ("\n", "\r\n"):
        raise ValueError("line_end must be \\n or \\r\\n")
    out = []
    for row in rows:
        out.append(delimiter.join(format_field(v, delimiter, quote, quoting, true, false) for v in row))
    return "".join(line + line_end for line in out)


def write_table(table: Table, delimiter: str = ",", quote: str = '"', quoting: str = "minimal",
                line_end: str = "\n", header: bool = True, true: str = "true", false: str = "false") -> str:
    """The table as delimited text, header first unless `header` is False. Header cells are always written as text
    (never left unquoted under `nonnumeric` when they look like numbers)."""
    rows: list[Iterable] = []
    if header:
        rows.append([str(c) for c in table.columns])
    rows.extend(table.rows)
    if quoting == "nonnumeric" and header:
        head = delimiter.join(format_field(c, delimiter, quote, "all") for c in table.columns) + line_end
        return head + write_rows(table.rows, delimiter, quote, quoting, line_end, true, false)
    return write_rows(rows, delimiter, quote, quoting, line_end, true, false)


def column_widths(table: Table) -> dict[str, int]:
    """The widest written field per column (header included), as `write_table` with minimal quoting writes it."""
    widths = {c: len(format_field(c)) for c in table.columns}
    for row in table.rows:
        for c, v in zip(table.columns, row):
            widths[c] = max(widths[c], len(format_field(v)))
    return widths
