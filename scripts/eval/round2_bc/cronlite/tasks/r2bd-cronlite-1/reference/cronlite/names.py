"""Three-letter names for months and weekdays, accepted wherever those fields take a number."""
from __future__ import annotations

MONTHS = {name: number for number, name in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}
WEEKDAYS = {name: number for number, name in enumerate(("sun", "mon", "tue", "wed", "thu", "fri", "sat"))}
BY_FIELD = {"month": MONTHS, "weekday": WEEKDAYS}


def lookup(field: str, text: str) -> int | None:
    """The number a name stands for in this field (case-insensitive), or None when it is not a name there."""
    return BY_FIELD.get(field, {}).get(text.strip().lower())
