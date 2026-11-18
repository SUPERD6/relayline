"""Checking rows against rules and reporting every violation."""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Iterable

from .table import Table


@dataclass(frozen=True)
class Violation:
    row: int          # 0-based position in the table
    column: str
    rule: str
    message: str


class Rule:
    """A check on one column; `check_value` returns a message, or None when the value is fine."""
    name = "rule"

    def __init__(self, column: str):
        self.column = column

    def check_value(self, value) -> str | None:  # pragma: no cover - overridden
        return None

    def check(self, table: Table) -> list[Violation]:
        i = table.index(self.column)
        out = []
        for n, row in enumerate(table.rows):
            message = self.check_value(row[i])
            if message:
                out.append(Violation(n, self.column, self.name, message))
        return out


class Required(Rule):
    name = "required"

    def check_value(self, value):
        if value is None or (isinstance(value, str) and value.strip() == ""):
            return "value is missing"
        return None


class Range(Rule):
    """low <= value <= high; either bound may be None. Missing values pass (combine with Required)."""
    name = "range"

    def __init__(self, column: str, low=None, high=None):
        super().__init__(column)
        if low is not None and high is not None and low > high:
            raise ValueError("low must not exceed high")
        self.low, self.high = low, high

    def check_value(self, value):
        if value is None:
            return None
        try:
            if self.low is not None and value < self.low:
                return f"{value!r} is below {self.low!r}"
            if self.high is not None and value > self.high:
                return f"{value!r} is above {self.high!r}"
        except TypeError:
            return f"{value!r} cannot be compared"
        return None


class Pattern(Rule):
    """The whole text value must match the regular expression. Missing values pass."""
    name = "pattern"

    def __init__(self, column: str, regex: str):
        super().__init__(column)
        self.regex = re.compile(regex)

    def check_value(self, value):
        if value is None:
            return None
        if not self.regex.fullmatch(str(value)):
            return f"{value!r} does not match {self.regex.pattern!r}"
        return None


class OneOf(Rule):
    name = "one_of"

    def __init__(self, column: str, allowed: Iterable):
        super().__init__(column)
        self.allowed = set(allowed)

    def check_value(self, value):
        if value is None or value in self.allowed:
            return None
        return f"{value!r} is not one of the allowed values"


class Unique:
    """The combination of `columns` must not repeat; every row after the first of a repeated combination is
    reported. Rows with a None in the combination are not compared."""
    name = "unique"

    def __init__(self, *columns: str):
        if not columns:
            raise ValueError("Unique needs at least one column")
        self.columns = list(columns)

    def check(self, table: Table) -> list[Violation]:
        idx = [table.index(c) for c in self.columns]
        seen: dict[tuple, int] = {}
        out = []
        for n, row in enumerate(table.rows):
            key = tuple(row[i] for i in idx)
            if None in key:
                continue
            if key in seen:
                out.append(Violation(n, ",".join(self.columns), self.name, f"repeats row {seen[key]}"))
            else:
                seen[key] = n
        return out


def validate(table: Table, rules: Iterable) -> list[Violation]:
    """Every violation of every rule, ordered by row, then by the order the rules were given."""
    rules = list(rules)
    found = []
    for order, rule in enumerate(rules):
        found += [(v.row, order, v) for v in rule.check(table)]
    return [v for _, _, v in sorted(found, key=lambda t: (t[0], t[1]))]


def summary(violations: Iterable[Violation]) -> dict[str, int]:
    """Number of violations per rule name, most frequent first (ties by name)."""
    counts = Counter(v.rule for v in violations)
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def clean_rows(table: Table, rules: Iterable) -> Table:
    """The table without the rows that violate any rule."""
    bad = {v.row for v in validate(table, rules)}
    return Table(table.columns, [row for n, row in enumerate(table.rows) if n not in bad])
