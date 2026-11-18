class TabulaError(Exception):
    """Base class for every error tabula raises."""


class ParseError(TabulaError):
    def __init__(self, line: int, message: str):
        super().__init__(f"line {line}: {message}")
        self.line = line
        self.message = message


class CoercionError(TabulaError):
    def __init__(self, column: str, value: str, kind: str, line: int | None = None):
        where = f"line {line}: " if line is not None else ""
        super().__init__(f"{where}column {column!r}: cannot read {value!r} as {kind}")
        self.column = column
        self.value = value
        self.kind = kind
        self.line = line
