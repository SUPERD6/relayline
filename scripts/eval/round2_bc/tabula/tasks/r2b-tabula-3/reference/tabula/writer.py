"""Writing rows and tables back to delimited text, the inverse of `reader`."""
from __future__ import annotations

from typing import Iterable

from .reader import check_comment
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
                 true: str = "true", false: str = "false", comment: str | None = None) -> str:
    """One field as text. `minimal` quotes only when needed (delimiter, quote, line break, or leading/trailing
    space, or text starting with the `comment` marker when one is given), `all` quotes every field, `nonnumeric`
    quotes everything except numbers and empty values, `none` never quotes and refuses values that would need it."""
    if quoting not in QUOTING:
        raise ValueError(f"quoting must be one of {', '.join(QUOTING)}")
    text = _text(value, true, false)
    needs = (delimiter in text or quote in text or "\n" in text or "\r" in text
             or (text != text.strip()) or (comment is not None and text.startswith(comment)))
    if quoting == "none":
        if needs:
            raise ValueError(f"field {text!r} needs quoting")
        return text
    if quoting == "all" or needs or (quoting == "nonnumeric" and value is not None and not _is_number(value)):
        return quote + text.replace(quote, quote * 2) + quote
    return text


def _line(row: Iterable, delimiter: str, quote: str, quoting: str, true: str, false: str, comment) -> str:
    """One row; only its first field can be mistaken for a comment line when read back."""
    return delimiter.join(format_field(v, delimiter, quote, quoting, true, false, comment if k == 0 else None)
                          for k, v in enumerate(row))


def write_rows(rows: Iterable[Iterable], delimiter: str = ",", quote: str = '"', quoting: str = "minimal",
               line_end: str = "\n", true: str = "true", false: str = "false", comment: str | None = None) -> str:
    """Rows of values as delimited text; every row ends with `line_end`. With `comment`, a row whose first field
    starts with that marker has the field quoted, so that reading back with the same marker keeps the row."""
    if len(delimiter) != 1 or len(quote) != 1 or delimiter == quote:
        raise ValueError("delimiter and quote must be two different single characters")
    if line_end not in ("\n", "\r\n"):
        raise ValueError("line_end must be \\n or \\r\\n")
    check_comment(comment, delimiter, quote)
    out = [_line(row, delimiter, quote, quoting, true, false, comment) for row in rows]
    return "".join(line + line_end for line in out)


def _preamble(lines: Iterable[str], comment, line_end: str) -> str:
    out = []
    for text in lines:
        if "\n" in text or "\r" in text:
            raise ValueError("a preamble line cannot contain a line break")
        out.append(comment + (" " + text if text else "") + line_end)
    return "".join(out)


def write_table(table: Table, delimiter: str = ",", quote: str = '"', quoting: str = "minimal",
                line_end: str = "\n", header: bool = True, true: str = "true", false: str = "false",
                comment: str | None = None, preamble: Iterable[str] = ()) -> str:
    """The table as delimited text, header first unless `header` is False. Header cells are always written as text
    (never left unquoted under `nonnumeric` when they look like numbers). `preamble` lines come first, each as a
    comment line (`comment`, a space, the text; an empty line is the marker alone); they need `comment`."""
    preamble = list(preamble)
    if preamble and comment is None:
        raise ValueError("a preamble needs a comment marker")
    check_comment(comment, delimiter, quote)
    lead = _preamble(preamble, comment, line_end)
    rows: list[Iterable] = []
    if header:
        rows.append([str(c) for c in table.columns])
    rows.extend(table.rows)
    if quoting == "nonnumeric" and header:
        head = _line(table.columns, delimiter, quote, "all", true, false, comment) + line_end
        return lead + head + write_rows(table.rows, delimiter, quote, quoting, line_end, true, false, comment)
    return lead + write_rows(rows, delimiter, quote, quoting, line_end, true, false, comment)


def column_widths(table: Table) -> dict[str, int]:
    """The widest written field per column (header included), as `write_table` with minimal quoting writes it."""
    widths = {c: len(format_field(c)) for c in table.columns}
    for row in table.rows:
        for c, v in zip(table.columns, row):
            widths[c] = max(widths[c], len(format_field(v)))
    return widths
