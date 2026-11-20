"""A small filter language for rows: `qty >= 3 and (kind == 'a' or name ~ 'p.*')`.

Grammar (lowest precedence first):

    expr    := or
    or      := and ("or" and)*
    and     := not ("and" not)*
    not     := "not" not | compare
    compare := operand (OP operand)?        OP is one of == != < <= > >= ~ (~ is a full regex match)
    operand := NUMBER | STRING | "null" | "true" | "false" | NAME | "(" expr ")"

Names are column names (letters, digits, underscore, not starting with a digit). Strings use single or double
quotes; a doubled quote inside stands for one. Comparing with null is only allowed with == and !=; any other
comparison involving a None value is false.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable

from .errors import TabulaError
from .table import Table


class QueryError(TabulaError):
    def __init__(self, position: int, message: str):
        super().__init__(f"at {position}: {message}")
        self.position = position
        self.message = message


@dataclass(frozen=True)
class Token:
    kind: str     # NUM, STR, NAME, OP, LP, RP, KW, END
    value: Any
    pos: int


KEYWORDS = {"and", "or", "not", "null", "true", "false"}
OPS = ("==", "!=", "<=", ">=", "<", ">", "~")
_NUM = re.compile(r"-?\d+(\.\d+)?([eE][-+]?\d+)?")
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def tokenize(text: str) -> list[Token]:
    out, i = [], 0
    while i < len(text):
        ch = text[i]
        if ch.isspace():
            i += 1
            continue
        if ch in "()":
            out.append(Token("LP" if ch == "(" else "RP", ch, i))
            i += 1
            continue
        op = next((o for o in OPS if text.startswith(o, i)), None)
        if op:
            out.append(Token("OP", op, i))
            i += len(op)
            continue
        if ch in "'\"":
            j, chars = i + 1, []
            while True:
                if j >= len(text):
                    raise QueryError(i, "unterminated string")
                if text[j] == ch:
                    if j + 1 < len(text) and text[j + 1] == ch:
                        chars.append(ch)
                        j += 2
                        continue
                    break
                chars.append(text[j])
                j += 1
            out.append(Token("STR", "".join(chars), i))
            i = j + 1
            continue
        m = _NUM.match(text, i)
        if m:
            raw = m.group(0)
            out.append(Token("NUM", float(raw) if any(c in raw for c in ".eE") else int(raw), i))
            i = m.end()
            continue
        m = _NAME.match(text, i)
        if m:
            word = m.group(0)
            out.append(Token("KW" if word.lower() in KEYWORDS else "NAME",
                             word.lower() if word.lower() in KEYWORDS else word, i))
            i = m.end()
            continue
        raise QueryError(i, f"unexpected character {ch!r}")
    out.append(Token("END", None, len(text)))
    return out


Node = Callable[[dict], Any]


class _Parser:
    def __init__(self, tokens: list[Token], columns: set[str]):
        self.tokens, self.i, self.columns = tokens, 0, columns

    def peek(self) -> Token:
        return self.tokens[self.i]

    def take(self) -> Token:
        tok = self.tokens[self.i]
        self.i += 1
        return tok

    def expect_end(self) -> None:
        tok = self.peek()
        if tok.kind != "END":
            raise QueryError(tok.pos, f"unexpected {tok.value!r}")

    def parse_or(self) -> Node:
        left = self.parse_and()
        while self.peek().kind == "KW" and self.peek().value == "or":
            self.take()
            right = self.parse_and()
            left = (lambda a, b: lambda r: bool(a(r)) or bool(b(r)))(left, right)
        return left

    def parse_and(self) -> Node:
        left = self.parse_not()
        while self.peek().kind == "KW" and self.peek().value == "and":
            self.take()
            right = self.parse_not()
            left = (lambda a, b: lambda r: bool(a(r)) and bool(b(r)))(left, right)
        return left

    def parse_not(self) -> Node:
        if self.peek().kind == "KW" and self.peek().value == "not":
            self.take()
            inner = self.parse_not()
            return lambda r: not inner(r)
        return self.parse_compare()

    def parse_compare(self) -> Node:
        left, left_null = self.parse_operand()
        if self.peek().kind != "OP":
            return left
        op = self.take()
        right, right_null = self.parse_operand()
        if (left_null or right_null) and op.value not in ("==", "!="):
            raise QueryError(op.pos, f"null can only be compared with == or !=")
        return _compare(op.value, left, right)

    def parse_operand(self) -> tuple[Node, bool]:
        tok = self.take()
        if tok.kind in ("NUM", "STR"):
            return (lambda v: lambda r: v)(tok.value), False
        if tok.kind == "KW" and tok.value in ("null", "true", "false"):
            value = {"null": None, "true": True, "false": False}[tok.value]
            return (lambda v: lambda r: v)(value), tok.value == "null"
        if tok.kind == "NAME":
            if tok.value not in self.columns:
                raise QueryError(tok.pos, f"unknown column {tok.value!r}")
            return (lambda name: lambda r: r[name])(tok.value), False
        if tok.kind == "LP":
            inner = self.parse_or()
            close = self.take()
            if close.kind != "RP":
                raise QueryError(close.pos, "missing closing parenthesis")
            return inner, False
        raise QueryError(tok.pos, "expected a value" if tok.kind != "END" else "unexpected end of query")


def _compare(op: str, left: Node, right: Node) -> Node:
    def run(row):
        a, b = left(row), right(row)
        if op == "==":
            return a == b
        if op == "!=":
            return a != b
        if a is None or b is None:
            return False
        if op == "~":
            return re.fullmatch(str(b), str(a)) is not None
        try:
            return {"<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b}[op]
        except TypeError:
            return False
    return run


def compile_query(text: str, columns) -> Node:
    """A predicate over row dicts (as `Table.where` passes them), checked against the given column names."""
    parser = _Parser(tokenize(text), set(columns))
    node = parser.parse_or()
    parser.expect_end()
    return lambda row: bool(node(row))


def query(table: Table, text: str) -> Table:
    """The rows of `table` for which the query is true."""
    return table.where(compile_query(text, table.columns))
