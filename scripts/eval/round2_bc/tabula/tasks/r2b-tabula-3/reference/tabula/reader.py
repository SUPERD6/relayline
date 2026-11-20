"""Reading delimited text: quoted fields, doubled quotes, line breaks inside quotes, optional comment lines."""
from __future__ import annotations

from .errors import ParseError
from .table import Table


def check_comment(comment, delimiter: str, quote: str) -> None:
    """A comment marker is None or one character that is neither the delimiter nor the quote."""
    if comment is not None and (not isinstance(comment, str) or len(comment) != 1 or comment in (delimiter, quote)):
        raise ValueError("comment must be one character, different from the delimiter and the quote")


def _scan(text: str, delimiter: str, quote: str, comment) -> list[tuple[list[str], int]]:
    """Rows of fields, each with the line of the text on which it starts."""
    if len(delimiter) != 1 or len(quote) != 1 or delimiter == quote:
        raise ValueError("delimiter and quote must be two different single characters")
    check_comment(comment, delimiter, quote)
    rows: list[tuple[list[str], int]] = []
    row: list[str] = []
    field: list[str] = []
    line = 1
    start = 1
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
        if not started and comment is not None and ch == comment:
            while i < n and text[i] not in "\r\n":  # the whole line is a comment; its line break ends it below
                i += 1
            continue
        if not started:
            start = line
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
                rows.append((row, start))
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
        rows.append((row, start))
    return rows


def read_rows(text: str, delimiter: str = ",", quote: str = '"', comment: str | None = None) -> list[list[str]]:
    """Split `text` into rows of fields. A quoted field may contain the delimiter, line breaks and doubled quotes.
    Blank lines between rows are skipped, and so are comment lines: lines whose first character is `comment`."""
    return [row for row, _ in _scan(text, delimiter, quote, comment)]


def read_table(text: str, delimiter: str = ",", quote: str = '"', comment: str | None = None) -> Table:
    """The first row is the header; every other row must have as many fields. Error lines are lines of the text,
    comment lines included."""
    rows = _scan(text, delimiter, quote, comment)
    if not rows:
        raise ParseError(1, "no header row")
    (header, header_line), body = rows[0], rows[1:]
    if len(set(header)) != len(header):
        raise ParseError(header_line, "duplicate column name")
    for row, line in body:
        if len(row) != len(header):
            raise ParseError(line, f"expected {len(header)} fields, found {len(row)}")
    return Table(header, [tuple(r) for r, _ in body])
