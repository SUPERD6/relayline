"""Describing an expression in plain English: `30 9 * * 1,5` -> "at 09:30 on Monday and Friday"."""
from __future__ import annotations

from .expr import CronExpr
from .fields import BOUNDS, FieldSpec

MONTH_NAMES = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
               "November", "December")
DAY_NAMES = ("Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday")


def join_words(words: list[str]) -> str:
    """'a', 'a and b', 'a, b and c'."""
    if not words:
        return ""
    if len(words) == 1:
        return words[0]
    return ", ".join(words[:-1]) + " and " + words[-1]


def runs(values: list[int]) -> list[tuple[int, int]]:
    """Consecutive runs in sorted values: [1, 2, 3, 7] -> [(1, 3), (7, 7)]."""
    out: list[tuple[int, int]] = []
    for v in sorted(values):
        if out and v == out[-1][1] + 1:
            out[-1] = (out[-1][0], v)
        else:
            out.append((v, v))
    return out


def _span_parts(values: list[int], name=lambda v: str(v), min_run: int = 3) -> list[str]:
    """Values as words; runs of at least `min_run` become 'x through y'."""
    parts = []
    for start, end in runs(values):
        if end - start + 1 >= min_run:
            parts.append(f"{name(start)} through {name(end)}")
        else:
            parts += [name(v) for v in range(start, end + 1)]
    return parts


def _span(values: list[int], name=lambda v: str(v), min_run: int = 3) -> str:
    return join_words(_span_parts(values, name, min_run))


def _day_text(spec: FieldSpec) -> str:
    """'on the 1st and 15th of the month', 'on the last day of the month', 'on the 1st and last day of the month'."""
    parts = _span_parts(sorted(spec.values), _ordinal)
    if spec.last:
        parts.append("last day")
    return "on the " + join_words(parts) + " of the month"


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _is_full(spec: FieldSpec) -> bool:
    low, high = BOUNDS[spec.name]
    return spec.wildcard or spec.values == frozenset(range(low, high + 1))


def describe_time(minute: FieldSpec, hour: FieldSpec) -> str:
    minutes, hours = sorted(minute.values), sorted(hour.values)
    if _is_full(minute) and _is_full(hour):
        return "every minute"
    if _is_full(hour):
        if len(minutes) == 1:
            return "every hour at minute " + str(minutes[0])
        return "every hour at minutes " + _span(minutes)
    if _is_full(minute):
        return "every minute during hour " + _span(hours) if len(hours) == 1 else (
            "every minute during hours " + _span(hours))
    if len(minutes) * len(hours) <= 4:
        times = [f"{h:02d}:{m:02d}" for h in hours for m in minutes]
        return "at " + join_words(times)
    return f"at minute {_span(minutes)} past hour {_span(hours)}"


def describe_days(expr: CronExpr) -> str:
    """The date part ('' when every day matches)."""
    f = expr.fields
    parts = []
    day_full, wd_full = _is_full(f["day"]), _is_full(f["weekday"])
    day_text = _day_text(f["day"])
    wd_text = "on " + _span(sorted(f["weekday"].values), lambda v: DAY_NAMES[v])
    if not day_full and not wd_full:
        parts.append(f"{day_text} or {wd_text}")
    elif not day_full:
        parts.append(day_text)
    elif not wd_full:
        parts.append(wd_text)
    if not _is_full(f["month"]):
        parts.append("in " + _span(sorted(f["month"].values), lambda v: MONTH_NAMES[v - 1]))
    return " ".join(parts)


def describe_next(expr: CronExpr | str, when, count: int = 3) -> str:
    """The sentence followed by the next `count` firing times, e.g.
    'at 09:30 on Monday (next: 2026-03-02 09:30, 2026-03-09 09:30)'."""
    from .schedule import upcoming  # local import: schedule does not depend on describe
    if isinstance(expr, str):
        expr = CronExpr.parse(expr)
    if count < 1:
        return describe(expr)
    times = ", ".join(t.strftime("%Y-%m-%d %H:%M") for t in upcoming(expr, when, count))
    return f"{describe(expr)} (next: {times})"


def describe(expr: CronExpr | str) -> str:
    """A sentence for the expression, e.g. 'at 09:30 on Monday and Friday in January'."""
    if isinstance(expr, str):
        expr = CronExpr.parse(expr)
    time_text = describe_time(expr.fields["minute"], expr.fields["hour"])
    day_text = describe_days(expr)
    return f"{time_text} {day_text}".strip()
