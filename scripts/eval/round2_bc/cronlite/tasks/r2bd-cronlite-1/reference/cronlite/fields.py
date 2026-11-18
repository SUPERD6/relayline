"""One field of a cron expression: a comma-separated list of `*`, numbers, ranges `a-b` and steps `/n`."""
from __future__ import annotations

from dataclasses import dataclass

from .errors import CronError
from .names import lookup

# name -> (lowest, highest)
BOUNDS = {"minute": (0, 59), "hour": (0, 23), "day": (1, 31), "month": (1, 12), "weekday": (0, 6)}


@dataclass(frozen=True)
class FieldSpec:
    name: str
    values: frozenset
    wildcard: bool = False

    def matches(self, value: int) -> bool:
        return value in self.values


def _number(name: str, text: str, low: int, high: int) -> int:
    named = lookup(name, text)
    if named is not None:
        return named
    if not text.isdigit():
        raise CronError(f"{name}: {text!r} is not a number")
    number = int(text)
    if not low <= number <= high:
        raise CronError(f"{name}: {number} is outside {low}-{high}")
    return number


def _part(name: str, part: str, low: int, high: int) -> set[int]:
    """The values of one comma-separated part: `*`, `n`, `a-b`, each optionally followed by `/step`; `n/step`
    runs from n to the highest value."""
    base, slash, step_text = part.partition("/")
    step = 1
    if slash:
        if not step_text.isdigit() or int(step_text) == 0:
            raise CronError(f"{name}: step {step_text!r} must be a positive number")
        step = int(step_text)
    if base == "*":
        start, end = low, high
    elif "-" in base:
        first, _, last = base.partition("-")
        start, end = _number(name, first, low, high), _number(name, last, low, high)
        if start > end:
            raise CronError(f"{name}: range {base!r} runs backwards")
    else:
        start = _number(name, base, low, high)
        end = high if slash else start
    return set(range(start, end + 1, step))


def parse_field(name: str, text: str) -> FieldSpec:
    """Parse one field. In the weekday field 7 also means Sunday (stored as 0), also inside ranges. Only a bare `*`
    makes a wildcard; `*/n` is a restriction."""
    if name not in BOUNDS:
        raise CronError(f"unknown field {name!r}")
    low, high = BOUNDS[name]
    if name == "weekday":
        high = 7
    text = text.strip()
    if text == "*":
        return FieldSpec(name, frozenset(range(low, BOUNDS[name][1] + 1)), wildcard=True)
    values: set[int] = set()
    for part in text.split(","):
        part = part.strip()
        if not part:
            raise CronError(f"{name}: empty list item")
        values |= _part(name, part, low, high)
    if name == "weekday" and 7 in values:
        values = (values - {7}) | {0}
    return FieldSpec(name, frozenset(values))
