"""Reading delimited text: quoted fields, doubled quotes, line breaks inside quotes; typed fields under nonnumeric
quoting (the inverse of writing with quoting="nonnumeric")."""
from __future__ import annotations

import re

from .errors import ParseError
from .table import Table

READ_QUOTING = ("minimal", "nonnumeric")
_INT = re.compile(r"-?\d+")
_FLOAT = re.compile(r"-?(\d+(\.\d*)?|\.\d+)([eE][-+]?\d+)?")


def _scan(text: str, delimiter: str, quote: str) -> list[list[tuple[str, bool, int]]]:
    """Rows of (text, was quoted, line) fields."""
    if len(delimiter) != 1 or len(quote) != 1 or delimiter == quote:
        raise ValueError("delimiter and quote must be two different single characters")
    rows: list[list[tuple[str, bool, int]]] = []
    row: list[tuple[str, bool, int]] = []
    field: list[str] = []
    line = 1
    in_quotes = False
    quoted = False  # the current field opened with a quote
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
            in_quotes, quoted, quoted_line, started = True, True, line, True
        elif ch == delimiter:
            row.append(("".join(field), quoted, line))
            field, quoted = [], False
            started = True
        elif ch in "\r\n":
            if ch == "\r" and i + 1 < n and text[i + 1] == "\n":
                i += 1
            if started:
                row.append(("".join(field), quoted, line))
                rows.append(row)
            row, field, quoted, started = [], [], False, False
            line += 1
        else:
            field.append(ch)
            started = True
        i += 1
    if in_quotes:
        raise ParseError(quoted_line, "unterminated quoted field")
    if started:
        row.append(("".join(field), quoted, line))
        rows.append(row)
    return rows


def _typed(field: tuple[str, bool, int], true: str, false: str):
    """Under nonnumeric quoting: quoted fields are text, unquoted ones empty (None), a boolean word or a number."""
    text, quoted, line = field
    if quoted:
        return text
    if text == "":
        return None
    if text == true:
        return True
    if text == false:
        return False
    if _INT.fullmatch(text):
        return int(text)
    if _FLOAT.fullmatch(text):
        return float(text)
    raise ParseError(line, f"unquoted field {text!r} is not a number, a boolean or empty")


def _check_quoting(quoting: str) -> None:
    if quoting not in READ_QUOTING:
        raise ValueError(f"quoting must be one of {', '.join(READ_QUOTING)}")


def read_rows(text: str, delimiter: str = ",", quote: str = '"', quoting: str = "minimal", true: str = "true",
              false: str = "false") -> list[list]:
    """Split `text` into rows of fields. A quoted field may contain the delimiter, line breaks and doubled quotes.
    Blank lines between rows are skipped. With quoting="nonnumeric", fields are typed (see `_typed`)."""
    _check_quoting(quoting)
    rows = _scan(text, delimiter, quote)
    if quoting == "minimal":
        return [[f[0] for f in row] for row in rows]
    return [[_typed(f, true, false) for f in row] for row in rows]


def read_table(text: str, delimiter: str = ",", quote: str = '"', quoting: str = "minimal", true: str = "true",
               false: str = "false") -> Table:
    """The first row is the header; every other row must have as many fields. The header is always text, also
    under nonnumeric quoting."""
    _check_quoting(quoting)
    rows = _scan(text, delimiter, quote)
    if not rows:
        raise ParseError(1, "no header row")
    header, body = [f[0] for f in rows[0]], rows[1:]
    if len(set(header)) != len(header):
        raise ParseError(1, "duplicate column name")
    for number, row in enumerate(body, 2):
        if len(row) != len(header):
            raise ParseError(number, f"expected {len(header)} fields, found {len(row)}")
    if quoting == "minimal":
        return Table(header, [tuple(f[0] for f in row) for row in body])
    return Table(header, [tuple(_typed(f, true, false) for f in row) for row in body])
