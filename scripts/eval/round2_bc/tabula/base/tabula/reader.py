"""Reading delimited text: quoted fields, doubled quotes, line breaks inside quotes."""
from __future__ import annotations

from .errors import ParseError
from .table import Table


def read_rows(text: str, delimiter: str = ",", quote: str = '"') -> list[list[str]]:
    """Split `text` into rows of fields. A quoted field may contain the delimiter, line breaks and doubled quotes.
    Blank lines between rows are skipped."""
    if len(delimiter) != 1 or len(quote) != 1 or delimiter == quote:
        raise ValueError("delimiter and quote must be two different single characters")
    rows: list[list[str]] = []
    row: list[str] = []
    field: list[str] = []
    line = 1
    in_quotes = False
    quoted_line = 0
    started = False  # the current row has at least one character
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if in_quotes:
            if ch == quote:
                if i + 1 < n and text[i + 1] == quote:
                    field.append(quote)
                    i += 2
                    continue
                in_quotes = False
            else:
                if ch == "\n":
                    line += 1
                field.append(ch)
            i += 1
            continue
        if ch == quote:
            if field:
                raise ParseError(line, "quote inside an unquoted field")
            in_quotes, quoted_line, started = True, line, True
        elif ch == delimiter:
            row.append("".join(field))
            field = []
            started = True
        elif ch in "\r\n":
            if ch == "\r" and i + 1 < n and text[i + 1] == "\n":
                i += 1
            if started:
                row.append("".join(field))
                rows.append(row)
            row, field, started = [], [], False
            line += 1
        else:
            field.append(ch)
            started = True
        i += 1
    if in_quotes:
        raise ParseError(quoted_line, "unterminated quoted field")
    if started:
        row.append("".join(field))
        rows.append(row)
    return rows


def read_table(text: str, delimiter: str = ",", quote: str = '"') -> Table:
    """The first row is the header; every other row must have as many fields."""
    rows = read_rows(text, delimiter, quote)
    if not rows:
        raise ParseError(1, "no header row")
    header, body = rows[0], rows[1:]
    if len(set(header)) != len(header):
        raise ParseError(1, "duplicate column name")
    for number, row in enumerate(body, 2):
        if len(row) != len(header):
            raise ParseError(number, f"expected {len(header)} fields, found {len(row)}")
    return Table(header, [tuple(r) for r in body])
