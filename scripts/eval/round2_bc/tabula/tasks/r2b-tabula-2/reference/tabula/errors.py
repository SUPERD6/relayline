class TabulaError(Exception):
    """Base class for every error tabula raises."""


class ParseError(TabulaError):
    def __init__(self, line: int, message: str):
        super().__init__(f"line {line}: {message}")
        self.line = line
        self.message = message


class CoercionError(TabulaError):
    def __init__(self, column: str, value: str, kind: str):
        super().__init__(f"column {column!r}: cannot read {value!r} as {kind}")
        self.column = column
        self.value = value
        self.kind = kind


class JoinError(TabulaError):
    """A join whose `validate` rule is broken: `side` ("left" or "right") repeats `key` (a tuple)."""

    def __init__(self, side: str, key: tuple):
        super().__init__(f"{side} table repeats join key {key!r}")
        self.side = side
        self.key = key
