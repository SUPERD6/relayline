"""One field of a cron expression: `*` or a comma-separated list of numbers."""
from __future__ import annotations

from dataclasses import dataclass

from .errors import CronError

# name -> (lowest, highest)
BOUNDS = {"minute": (0, 59), "hour": (0, 23), "day": (1, 31), "month": (1, 12), "weekday": (0, 6)}


@dataclass(frozen=True)
class FieldSpec:
    name: str
    values: frozenset
    wildcard: bool = False

    def matches(self, value: int) -> bool:
        return value in self.values


def parse_field(name: str, text: str) -> FieldSpec:
    if name not in BOUNDS:
        raise CronError(f"unknown field {name!r}")
    low, high = BOUNDS[name]
    text = text.strip()
    if text == "*":
        return FieldSpec(name, frozenset(range(low, high + 1)), wildcard=True)
    values = set()
    for part in text.split(","):
        part = part.strip()
        if not part.isdigit():
            raise CronError(f"{name}: {part!r} is not a number")
        number = int(part)
        if not low <= number <= high:
            raise CronError(f"{name}: {number} is outside {low}-{high}")
        values.add(number)
    return FieldSpec(name, frozenset(values))
